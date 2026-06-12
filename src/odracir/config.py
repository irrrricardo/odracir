"""Runtime configuration for DeepSeek-compatible API calls."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class DeepSeekConfig:
    api_key: str
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-v4-pro"
    thinking: str = "disabled"
    max_tool_turns: int = 4
    timeout_seconds: float = 300.0
    max_retries: int = 2


@dataclass(frozen=True)
class VisionConfig:
    api_key: str
    base_url: str
    model: str
    timeout_seconds: float = 300.0
    max_retries: int = 2


def load_config() -> DeepSeekConfig:
    load_dotenv()

    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "Missing DEEPSEEK_API_KEY. Copy .env.example to .env and set your key."
        )

    return DeepSeekConfig(
        api_key=api_key,
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip(),
        model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro").strip(),
        thinking=os.getenv("DEEPSEEK_THINKING", "disabled").strip(),
        max_tool_turns=int(os.getenv("ODRACIR_MAX_TOOL_TURNS", "4")),
        timeout_seconds=float(os.getenv("DEEPSEEK_TIMEOUT_SECONDS", "300")),
        max_retries=int(os.getenv("DEEPSEEK_MAX_RETRIES", "2")),
    )


def load_vision_config() -> VisionConfig:
    load_dotenv()
    api_key = os.getenv("VISION_API_KEY", "").strip()
    base_url = os.getenv("VISION_BASE_URL", "").strip()
    model = os.getenv("VISION_MODEL", "").strip()
    if not api_key or not base_url or not model:
        raise RuntimeError(
            "Missing vision configuration. Set VISION_API_KEY, VISION_BASE_URL, "
            "and VISION_MODEL for an OpenAI-compatible multimodal endpoint."
        )
    return VisionConfig(
        api_key=api_key,
        base_url=base_url,
        model=model,
        timeout_seconds=float(os.getenv("VISION_TIMEOUT_SECONDS", "300")),
        max_retries=int(os.getenv("VISION_MAX_RETRIES", "2")),
    )
