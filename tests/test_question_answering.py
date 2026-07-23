import json

import pytest

from odracir.providers import JsonCompletionResult
from odracir.question_answering import (
    EvidenceQuestionAnswerer,
    build_ask_plan,
    format_answer_result,
)
from odracir.research_folder import ResearchFolderHarness


class StubProvider:
    provider_name = "stub"
    model = "stub-model"

    def __init__(
        self,
        *,
        claim_citation: str = "[paper pp.2 chunk:method]",
        answer_citation: str = "[paper pp.2 chunk:method]",
    ) -> None:
        self.calls = []
        self.claim_citation = claim_citation
        self.answer_citation = answer_citation

    def complete_json(self, *, system_prompt: str, user_prompt: str, max_tokens: int):
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "max_tokens": max_tokens,
            }
        )
        return JsonCompletionResult(
            payload={
                "answer": (
                    "The model predicts longitudinal patient states "
                    f"{self.answer_citation}."
                ),
                "claims": [
                    {
                        "claim": "The model predicts longitudinal patient states.",
                        "citations": [self.claim_citation],
                        "inference": False,
                    }
                ],
                "limitations": ["The fixture contains limited evidence."],
                "missing_evidence": [],
                "follow_up_queries": ["clinical action simulation"],
            },
            usage={"total_tokens": 30},
        )


def _write_answer_fixture(root, *, long_text: bool = False) -> None:
    papers = root / "papers"
    papers.mkdir(parents=True)
    (papers / "paper.pdf").write_bytes(b"%PDF-1.4\n")
    harness = ResearchFolderHarness(root)
    harness.sync_index()
    index = harness.load_index()
    paper = index["papers"][0]
    paper["chunking_status"] = "chunked"
    paper["chunk_artifact"] = ".odracir/chunks/paper.json"
    harness.write_index(index)

    chunks_dir = root / ".odracir" / "chunks"
    chunks_dir.mkdir(parents=True)
    method_text = (
        "world model " * 30000
        if long_text
        else "The world model predicts longitudinal patient states from clinical history."
    )
    (chunks_dir / "paper.json").write_text(
        json.dumps(
            {
                "chunks": [
                    {
                        "id": "background",
                        "page_start": 1,
                        "page_end": 1,
                        "section_hint": "1 Introduction",
                        "content_sha256": "a" * 64,
                        "text": "Clinical world model background.",
                    },
                    {
                        "id": "method",
                        "page_start": 2,
                        "page_end": 2,
                        "section_hint": "2 Methods",
                        "content_sha256": "b" * 64,
                        "text": method_text,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )


def test_ask_dry_run_previews_ranked_full_evidence_without_provider(tmp_path) -> None:
    root = tmp_path / "field"
    _write_answer_fixture(root)

    plan = build_ask_plan(
        root,
        "How does the model work?",
        retrieval_query="longitudinal patient states",
        limit=1,
    )

    assert len(plan.evidence) == 1
    assert plan.evidence[0]["chunk_id"] == "method"
    assert plan.evidence[0]["citation"] == "[paper pp.2 chunk:method]"
    assert plan.total_context_chars == plan.evidence[0]["char_count"]
    assert "longitudinal patient states" in plan.evidence[0]["snippet"]


def test_ask_writes_artifact_and_uses_cached_answer(tmp_path) -> None:
    root = tmp_path / "field"
    _write_answer_fixture(root)
    provider = StubProvider()
    answerer = EvidenceQuestionAnswerer(root, provider)

    first = answerer.answer("What does the world model predict?", limit=1)
    second = answerer.answer("What does the world model predict?", limit=1)
    artifact = json.loads((root / first.artifact_path).read_text(encoding="utf-8"))

    assert first.status == "answered"
    assert first.cached is False
    assert second.cached is True
    assert len(provider.calls) == 1
    assert artifact["provider"] == "stub"
    assert artifact["usage"]["total_tokens"] == 30
    assert artifact["evidence"][0]["chunk_id"] == "method"
    assert "[paper pp.2 chunk:method]" in format_answer_result(first)


def test_ask_does_not_call_provider_without_matching_evidence(tmp_path) -> None:
    root = tmp_path / "field"
    _write_answer_fixture(root)
    provider = StubProvider()

    result = EvidenceQuestionAnswerer(root, provider).answer("unfindable")

    assert result.status == "missing_evidence"
    assert result.answer is None
    assert result.artifact_path is None
    assert provider.calls == []


def test_ask_does_not_create_provider_without_matching_evidence(tmp_path) -> None:
    root = tmp_path / "field"
    _write_answer_fixture(root)
    providers = []

    def create_provider():
        providers.append(StubProvider())
        return providers[0]

    result = EvidenceQuestionAnswerer(
        root,
        provider_factory=create_provider,
    ).answer("unfindable")

    assert result.status == "missing_evidence"
    assert providers == []


def test_ask_rejects_claim_citation_outside_retrieved_evidence(tmp_path) -> None:
    root = tmp_path / "field"
    _write_answer_fixture(root)

    with pytest.raises(ValueError, match="outside retrieved evidence"):
        EvidenceQuestionAnswerer(
            root,
            StubProvider(claim_citation="[paper pp.99 chunk:invented]"),
        ).answer("What does the world model predict?", limit=1)


def test_ask_rejects_inline_citation_outside_retrieved_evidence(tmp_path) -> None:
    root = tmp_path / "field"
    _write_answer_fixture(root)

    with pytest.raises(ValueError, match="outside retrieved evidence"):
        EvidenceQuestionAnswerer(
            root,
            StubProvider(answer_citation="[paper pp.99 chunk:invented]"),
        ).answer("What does the world model predict?", limit=1)


def test_ask_rejects_oversized_retrieval_context(tmp_path) -> None:
    root = tmp_path / "field"
    _write_answer_fixture(root, long_text=True)

    with pytest.raises(ValueError, match="exceeding"):
        build_ask_plan(root, "How does the world model work?", limit=1)


def test_ask_revalidates_cached_answer_before_using_it(tmp_path) -> None:
    root = tmp_path / "field"
    _write_answer_fixture(root)
    answerer = EvidenceQuestionAnswerer(root, StubProvider())
    first = answerer.answer("What does the world model predict?", limit=1)
    artifact_path = root / first.artifact_path
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    artifact["answer"]["claims"][0]["citations"] = ["[paper pp.99 chunk:invented]"]
    artifact_path.write_text(json.dumps(artifact), encoding="utf-8")

    with pytest.raises(ValueError, match="outside retrieved evidence"):
        answerer.answer("What does the world model predict?", limit=1)
