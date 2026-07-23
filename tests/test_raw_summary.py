import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from odracir.config import DeepSeekConfig
from odracir.providers import (
    DeepSeekProvider,
    JsonCompletionError,
    JsonCompletionResult,
)
from odracir.research_folder import ResearchFolderHarness
from odracir.skills import get_builtin_skill_registry
from odracir.summarization import EvidenceSummaryGenerator
from odracir.summary_evaluation import SummaryEvaluationHarness
from odracir.summary_normalization import RawSummaryNormalizer


RAW_READING = """The model read the paper but returned prose.
Evidence supports planning [paper pp.1 chunk:one].
"""


class RawCaptureProvider:
    provider_name = "stub"
    model = "raw-reader"

    def complete_json(self, *, system_prompt: str, user_prompt: str, max_tokens: int):
        raise JsonCompletionError(
            "fixture raw output",
            content=RAW_READING,
            usage={"total_tokens": 33},
            finish_reason="length",
            max_tokens=max_tokens,
        )


class NormalizeProvider:
    provider_name = "stub"
    model = "normalizer"

    def complete_json(self, *, system_prompt: str, user_prompt: str, max_tokens: int):
        return JsonCompletionResult(
            payload={
                "summary_short": "Normalized summary.",
                "summary_detailed": "Normalized detailed summary.",
                "research_question": "Can evidence guide planning?",
                "methods": ["Method"],
                "findings": [
                    {
                        "claim": "Evidence supports planning.",
                        "citations": ["[paper pp.1 chunk:one]"],
                        "inference": False,
                    }
                ],
                "limitations": ["Fixture limitation."],
                "key_terms": ["evidence"],
                "implementation_notes": [],
                "inferences": [],
            },
            usage={"total_tokens": 21},
        )


def _write_chunked_fixture(root):
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
    (chunks_dir / "paper.json").write_text(
        json.dumps(
            {
                "chunks": [
                    {
                        "id": "one",
                        "page_start": 1,
                        "page_end": 1,
                        "text": "Evidence supports planning.",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return harness


def test_deepseek_provider_preserves_invalid_json_content() -> None:
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="unfinished {"),
                finish_reason="length",
            )
        ],
        usage={"total_tokens": 99},
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **kwargs: response)
        )
    )
    provider = DeepSeekProvider(
        DeepSeekConfig(api_key="test", model="deepseek-test"), client=client
    )

    with pytest.raises(JsonCompletionError) as raised:
        provider.complete_json(
            system_prompt="Return json.",
            user_prompt="Read.",
            max_tokens=64,
        )

    assert raised.value.content == "unfinished {"
    assert raised.value.finish_reason == "length"
    assert raised.value.usage == {"total_tokens": 99}
    assert "truncated at max_tokens=64" in str(raised.value)


def test_summary_preserves_raw_output_as_portable_artifact(tmp_path) -> None:
    root = tmp_path / "field"
    _write_chunked_fixture(root)

    result = EvidenceSummaryGenerator(root, RawCaptureProvider()).summarize_index()
    paper = ResearchFolderHarness(root).load_index()["papers"][0]
    artifact = json.loads(
        (root / paper["raw_summary_artifact"]).read_text(encoding="utf-8")
    )

    assert result.raw_captured == 1
    assert result.failed == 0
    assert paper["summary_status"] == "raw_captured"
    assert paper["raw_summary_artifact"].startswith(".odracir/raw-summaries/paper/")
    assert not Path(paper["raw_summary_artifact"]).is_absolute()
    assert artifact["content"] == RAW_READING
    assert artifact["stage"] == "single_pass"
    assert artifact["finish_reason"] == "length"
    assert (root / ".odracir/raw-summaries/paper/latest.json").is_file()


def test_summary_evaluation_reports_raw_capture_for_normalization(tmp_path) -> None:
    root = tmp_path / "field"
    _write_chunked_fixture(root)
    EvidenceSummaryGenerator(root, RawCaptureProvider()).summarize_index()

    report = SummaryEvaluationHarness(
        root,
        skill_registry=get_builtin_skill_registry(),
    ).evaluate(write_artifact=False)

    assert report.status_counts == {"raw_captured": 1}
    assert "needs summary normalization" in report.records[0].warnings[0]


def test_normalizer_promotes_raw_output_and_preserves_source_artifact(tmp_path) -> None:
    root = tmp_path / "field"
    _write_chunked_fixture(root)
    EvidenceSummaryGenerator(root, RawCaptureProvider()).summarize_index()
    raw_path = ResearchFolderHarness(root).load_index()["papers"][0][
        "raw_summary_artifact"
    ]

    result = RawSummaryNormalizer(root, NormalizeProvider()).normalize_index()
    paper = ResearchFolderHarness(root).load_index()["papers"][0]
    summary = json.loads((root / paper["summary_artifact"]).read_text(encoding="utf-8"))

    assert result.normalized == 1
    assert result.failed == 0
    assert paper["summary_status"] == "summarized"
    assert summary["summary_strategy"] == "normalized_raw"
    assert summary["source_raw_artifact"] == raw_path
    assert (root / raw_path).is_file()
