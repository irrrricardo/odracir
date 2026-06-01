"""LLM provider adapters for Odracir processing workflows."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Protocol

from openai import OpenAI

from odracir.config import DeepSeekConfig, load_config


@dataclass(frozen=True)
class JsonCompletionResult:
    payload: dict[str, Any]
    usage: dict[str, int]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class JsonCompletionProvider(Protocol):
    provider_name: str
    model: str

    def complete_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
    ) -> JsonCompletionResult: ...


class DeepSeekProvider:
    """OpenAI-compatible adapter for DeepSeek chat and JSON completions."""

    provider_name = "deepseek"

    def __init__(
        self,
        config: DeepSeekConfig | None = None,
        *,
        client: Any | None = None,
    ) -> None:
        self.config = config or load_config()
        self.model = self.config.model
        self.client = client or OpenAI(
            api_key=self.config.api_key,
            base_url=self.config.base_url,
        )

    def chat_completion(self, **kwargs: Any) -> Any:
        request = {
            "model": self.model,
            **kwargs,
        }
        extra_body = self._extra_body()
        if extra_body:
            request["extra_body"] = extra_body
        return self.client.chat.completions.create(**request)

    def complete_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
    ) -> JsonCompletionResult:
        response = self.chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            max_tokens=max_tokens,
        )
        content = response.choices[0].message.content
        if not content:
            raise RuntimeError("DeepSeek returned empty JSON content.")
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError("DeepSeek returned invalid JSON content.") from exc
        if not isinstance(payload, dict):
            raise ValueError("DeepSeek JSON content must decode to an object.")
        return JsonCompletionResult(payload=payload, usage=_usage_dict(response))

    def _extra_body(self) -> dict[str, Any] | None:
        thinking = self.config.thinking.strip()
        if not thinking:
            return None
        if thinking not in {"enabled", "disabled"}:
            raise ValueError(
                "DEEPSEEK_THINKING must be 'enabled', 'disabled', or empty."
            )
        return {"thinking": {"type": thinking}}


def _usage_dict(response: Any) -> dict[str, int]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return {}
    if hasattr(usage, "model_dump"):
        payload = usage.model_dump(exclude_none=True)
    elif isinstance(usage, dict):
        payload = usage
    else:
        return {}
    return {
        key: int(value)
        for key, value in payload.items()
        if isinstance(value, int) and not isinstance(value, bool)
    }
