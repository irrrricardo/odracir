from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from odracir.paper_study.extraction import DeepSeekJsonProvider


DEEPSEEK_ENV_KEYS = (
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_MODEL",
    "DEEPSEEK_BASE_URL",
    "DEEPSEEK_TIMEOUT_SECONDS",
    "DEEPSEEK_MAX_RETRIES",
    "DEEPSEEK_THINKING",
)


def _clear_deepseek_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in DEEPSEEK_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def _capture_provider_init(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    def fake_init(self: DeepSeekJsonProvider, **kwargs: Any) -> None:
        captured.update(kwargs)
        self.model = str(kwargs["model"])
        self.thinking = str(kwargs["thinking"])

    monkeypatch.setattr(DeepSeekJsonProvider, "__init__", fake_init)
    return captured


def test_from_environment_auto_discovers_dotenv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_deepseek_environment(monkeypatch)
    captured = _capture_provider_init(monkeypatch)
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def fake_load_dotenv(*args: Any, **kwargs: Any) -> bool:
        calls.append((args, kwargs))
        monkeypatch.setenv("DEEPSEEK_API_KEY", "auto-test-key")
        return True

    monkeypatch.setattr("dotenv.load_dotenv", fake_load_dotenv)

    DeepSeekJsonProvider.from_environment()

    assert calls == [((), {"override": False})]
    assert captured["api_key"] == "auto-test-key"


def test_from_environment_loads_explicit_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _clear_deepseek_environment(monkeypatch)
    captured = _capture_provider_init(monkeypatch)
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    env_path = tmp_path / "explicit.env"

    def fake_load_dotenv(*args: Any, **kwargs: Any) -> bool:
        calls.append((args, kwargs))
        monkeypatch.setenv("DEEPSEEK_API_KEY", "explicit-test-key")
        return True

    monkeypatch.setattr("dotenv.load_dotenv", fake_load_dotenv)

    DeepSeekJsonProvider.from_environment(env_file=env_path)

    assert calls == [
        ((), {"dotenv_path": env_path, "override": False}),
    ]
    assert captured["api_key"] == "explicit-test-key"


def test_from_environment_preserves_process_values(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _clear_deepseek_environment(monkeypatch)
    captured = _capture_provider_init(monkeypatch)
    env_path = tmp_path / "precedence.env"
    env_path.write_text(
        "DEEPSEEK_API_KEY=file-test-key\nDEEPSEEK_MODEL=file-test-model\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "process-test-key")

    DeepSeekJsonProvider.from_environment(env_file=env_path)

    assert captured["api_key"] == "process-test-key"
    assert captured["model"] == "file-test-model"


def test_from_environment_reports_missing_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_deepseek_environment(monkeypatch)
    monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: False)

    with pytest.raises(RuntimeError, match="Missing DEEPSEEK_API_KEY"):
        DeepSeekJsonProvider.from_environment()
