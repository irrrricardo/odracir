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
    )
