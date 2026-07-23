from types import SimpleNamespace

from odracir.agent import OdracirAgent
from odracir.config import DeepSeekConfig


class _FakeMessage:
    def __init__(
        self,
        *,
        content: str | None,
        tool_calls: list | None = None,
        reasoning_content: str | None = None,
    ) -> None:
        self.content = content
        self.tool_calls = tool_calls or []
        self.reasoning_content = reasoning_content

    def model_dump(self, *, exclude_none: bool) -> dict:
        payload = {"role": "assistant", "content": self.content}
        if self.tool_calls:
            payload["tool_calls"] = [
                {
                    "id": tool_call.id,
                    "type": "function",
                    "function": {
                        "name": tool_call.function.name,
                        "arguments": tool_call.function.arguments,
                    },
                }
                for tool_call in self.tool_calls
            ]
        if exclude_none:
            return {key: value for key, value in payload.items() if value is not None}
        return payload


class _FakeProvider:
    def __init__(self) -> None:
        self.config = DeepSeekConfig(api_key="test", thinking="enabled")
        self.calls: list[dict] = []
        tool_call = SimpleNamespace(
            id="call-1",
            function=SimpleNamespace(name="list_research_skills", arguments="{}"),
        )
        self.responses = [
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=_FakeMessage(
                            content=None,
                            tool_calls=[tool_call],
                            reasoning_content="Need to inspect available skills.",
                        )
                    )
                ]
            ),
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=_FakeMessage(content="Use the generic skill.")
                    )
                ]
            ),
        ]

    def chat_completion(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


def test_agent_preserves_reasoning_content_across_tool_turns(monkeypatch) -> None:
    provider = _FakeProvider()
    monkeypatch.setattr(
        "odracir.agent.execute_tool",
        lambda name, arguments: {"tool": name, "arguments": arguments},
    )

    result = OdracirAgent(provider=provider).run("Which skill should I use?")

    assert result == "Use the generic skill."
    second_turn_messages = provider.calls[1]["messages"]
    assistant_payload = second_turn_messages[2]
    assert assistant_payload["reasoning_content"] == "Need to inspect available skills."
