"""Vision provider adapters for traceable scientific-figure analysis."""

from __future__ import annotations

import base64
import json
import mimetypes
import os
from pathlib import Path
from typing import Any, Protocol

from openai import OpenAI

from odracir.config import VisionConfig, load_vision_config
from odracir.providers import JsonCompletionError, JsonCompletionResult, _usage_dict


class VisionAnalysisProvider(Protocol):
    provider_name: str
    model: str

    def analyze_json(
        self,
        *,
        image_path: Path,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
    ) -> JsonCompletionResult: ...


class OpenAICompatibleVisionProvider:
    """Call an OpenAI-compatible vision endpoint with an image data URL."""

    provider_name = "openai-compatible-vision"
    verification_mode = "single_model"

    def __init__(
        self,
        config: VisionConfig | None = None,
        *,
        client: Any | None = None,
        provider_name: str | None = None,
    ) -> None:
        self.config = config or load_vision_config()
        self.provider_name = provider_name or type(self).provider_name
        self.model = self.config.model
        self.client = client or OpenAI(
            api_key=self.config.api_key,
            base_url=self.config.base_url,
            timeout=self.config.timeout_seconds,
            max_retries=self.config.max_retries,
        )

    def analyze_json(
        self,
        *,
        image_path: Path,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
    ) -> JsonCompletionResult:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": _image_data_url(image_path)},
                        },
                    ],
                },
            ],
            response_format={"type": "json_object"},
            max_tokens=max_tokens,
        )
        choice = response.choices[0]
        content = choice.message.content or ""
        finish_reason = getattr(choice, "finish_reason", None) or "unknown"
        usage = _usage_dict(response)
        if finish_reason == "length":
            raise JsonCompletionError(
                "Vision provider output was truncated at the token limit.",
                content=content,
                usage=usage,
                finish_reason=finish_reason,
                max_tokens=max_tokens,
            )
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            raise JsonCompletionError(
                "Vision provider returned invalid JSON content.",
                content=content,
                usage=usage,
                finish_reason=finish_reason,
                max_tokens=max_tokens,
            ) from exc
        if not isinstance(payload, dict):
            raise JsonCompletionError(
                "Vision provider JSON content must decode to an object.",
                content=content,
                usage=usage,
                finish_reason=finish_reason,
                max_tokens=max_tokens,
            )
        return JsonCompletionResult(payload=payload, usage=usage, finish_reason=finish_reason)


class ConsensusVisionProvider:
    """Use multiple vision APIs and a verifier API to produce one evidence result."""

    provider_name = "consensus-vision"
    verification_mode = "multi_model_consensus"

    def __init__(
        self,
        analyzers: list[VisionAnalysisProvider],
        verifier: VisionAnalysisProvider,
    ) -> None:
        if len(analyzers) < 2:
            raise ValueError("Consensus vision requires at least two analyzer APIs.")
        self.analyzers = analyzers
        self.verifier = verifier
        self.model = f"{verifier.model}-verifying-{len(analyzers)}-analyses"

    def analyze_json(
        self,
        *,
        image_path: Path,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
    ) -> JsonCompletionResult:
        candidates: list[dict[str, Any]] = []
        usage: dict[str, int] = {}
        for analyzer in self.analyzers:
            response = analyzer.analyze_json(
                image_path=image_path,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=max_tokens,
            )
            candidates.append(
                {
                    "provider": analyzer.provider_name,
                    "model": analyzer.model,
                    "analysis": response.payload,
                }
            )
            _merge_usage(usage, response.usage)
        verification_prompt = (
            f"{user_prompt}\n\n"
            "Independent candidate analyses JSON:\n"
            f"{json.dumps(candidates, ensure_ascii=False)}\n\n"
            "Act as a strict verifier. Return the required analysis JSON shape. "
            "Keep a claim only when image pixels or supplied source context support it. "
            "Resolve disagreement conservatively, lower confidence when needed, and "
            "put rejected claims under uncertainties or unsupported evidence_items."
        )
        verified = self.verifier.analyze_json(
            image_path=image_path,
            system_prompt=system_prompt,
            user_prompt=verification_prompt,
            max_tokens=max_tokens,
        )
        _merge_usage(usage, verified.usage)
        return JsonCompletionResult(
            payload=verified.payload,
            usage=usage,
            finish_reason=verified.finish_reason,
            metadata={
                "analyzer_candidates": candidates,
                "verifier": {
                    "provider": self.verifier.provider_name,
                    "model": self.verifier.model,
                },
            },
        )


def build_configured_vision_provider() -> VisionAnalysisProvider:
    """Build one API provider or a multi-API consensus provider from environment."""
    raw = os.getenv("VISION_ENSEMBLE_JSON", "").strip()
    if not raw:
        return OpenAICompatibleVisionProvider()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("VISION_ENSEMBLE_JSON must contain valid JSON.") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("VISION_ENSEMBLE_JSON must contain a JSON object.")
    analyzers_config = payload.get("analyzers")
    verifier_config = payload.get("verifier")
    if not isinstance(analyzers_config, list) or not isinstance(verifier_config, dict):
        raise RuntimeError(
            "VISION_ENSEMBLE_JSON requires analyzers list and verifier object."
        )
    analyzers = [_provider_from_mapping(item) for item in analyzers_config]
    verifier = _provider_from_mapping(verifier_config)
    return ConsensusVisionProvider(analyzers, verifier)


def _provider_from_mapping(value: Any) -> OpenAICompatibleVisionProvider:
    if not isinstance(value, dict):
        raise RuntimeError("Each vision endpoint configuration must be an object.")
    key_env = str(value.get("api_key_env", "")).strip()
    api_key = (
        os.getenv(key_env, "").strip()
        if key_env
        else str(value.get("api_key", "")).strip()
    )
    base_url = str(value.get("base_url", "")).strip()
    model = str(value.get("model", "")).strip()
    name = str(value.get("name", "")).strip() or "openai-compatible-vision"
    if not api_key or not base_url or not model:
        raise RuntimeError(
            f"Vision endpoint {name!r} requires api key, base_url, and model."
        )
    return OpenAICompatibleVisionProvider(
        VisionConfig(api_key=api_key, base_url=base_url, model=model),
        provider_name=name,
    )


def _image_data_url(path: Path) -> str:
    mime_type = mimetypes.guess_type(path.name)[0] or "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _merge_usage(total: dict[str, int], usage: dict[str, int]) -> None:
    for key, value in usage.items():
        total[key] = total.get(key, 0) + value
