import json
from types import SimpleNamespace

from odracir.config import DeepSeekConfig
from odracir.providers import DeepSeekProvider


class _FakeCompletions:
    def __init__(self) -> None:
        self.request = None

    def create(self, **kwargs):
        self.request = kwargs
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=json.dumps({"answer": "ok"}))
                )
            ],
            usage={"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
        )


def test_deepseek_provider_requests_json_object_output() -> None:
    completions = _FakeCompletions()
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    provider = DeepSeekProvider(
        DeepSeekConfig(api_key="test", model="deepseek-test"),
        client=client,
    )

    result = provider.complete_json(
        system_prompt="Return json.",
        user_prompt='Use this json shape: {"answer": "string"}',
        max_tokens=100,
    )

    assert result.payload == {"answer": "ok"}
    assert result.usage["total_tokens"] == 12
    assert completions.request["response_format"] == {"type": "json_object"}
    assert completions.request["model"] == "deepseek-test"


def test_deepseek_provider_sends_enabled_thinking_mode() -> None:
    completions = _FakeCompletions()
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    provider = DeepSeekProvider(
        DeepSeekConfig(api_key="test", thinking="enabled"),
        client=client,
    )

    provider.complete_json(
        system_prompt="Return json.",
        user_prompt='Use this json shape: {"answer": "string"}',
        max_tokens=100,
    )

    assert completions.request["extra_body"] == {"thinking": {"type": "enabled"}}


def test_deepseek_provider_rejects_unknown_thinking_mode() -> None:
    completions = _FakeCompletions()
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    provider = DeepSeekProvider(
        DeepSeekConfig(api_key="test", thinking="sometimes"),
        client=client,
    )

    try:
        provider.complete_json(
            system_prompt="Return json.",
            user_prompt='Use this json shape: {"answer": "string"}',
            max_tokens=100,
        )
    except ValueError as exc:
        assert "DEEPSEEK_THINKING" in str(exc)
    else:
        raise AssertionError("Expected invalid thinking mode to fail.")
