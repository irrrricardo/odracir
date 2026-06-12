from pathlib import Path

from odracir.providers import JsonCompletionResult
from odracir.vision_providers import ConsensusVisionProvider


class VisionStub:
    provider_name = "stub"

    def __init__(self, model: str, payload: dict) -> None:
        self.model = model
        self.payload = payload
        self.prompts = []

    def analyze_json(self, *, image_path, system_prompt, user_prompt, max_tokens):
        self.prompts.append(user_prompt)
        return JsonCompletionResult(
            payload=self.payload,
            usage={"total_tokens": 10},
            finish_reason="stop",
        )


def test_consensus_vision_sends_independent_outputs_to_verifier() -> None:
    first = VisionStub("first", {"observations": ["A"]})
    second = VisionStub("second", {"observations": ["B"]})
    verifier = VisionStub("verifier", {"observations": ["verified"]})
    provider = ConsensusVisionProvider([first, second], verifier)

    result = provider.analyze_json(
        image_path=Path("figure.png"),
        system_prompt="system",
        user_prompt="request",
        max_tokens=100,
    )

    assert result.payload == {"observations": ["verified"]}
    assert result.usage == {"total_tokens": 30}
    assert result.metadata["analyzer_candidates"][0]["analysis"] == {
        "observations": ["A"]
    }
    assert result.metadata["verifier"]["model"] == "verifier"
    assert "Independent candidate analyses JSON" in verifier.prompts[0]
    assert '"model": "first"' in verifier.prompts[0]
    assert '"model": "second"' in verifier.prompts[0]
