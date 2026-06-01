import json
import sys

import pytest

from odracir.cli import main
from odracir.providers import JsonCompletionResult
from odracir.research_folder import ResearchFolderHarness
from odracir.research_memory import ResearchCatalogBuilder
from odracir.skills import get_builtin_skill_registry
from odracir.summarization import EvidenceSummaryGenerator
from odracir.summary_review import SummaryReviewHarness
from odracir.tools import execute_tool


class ReviewStubProvider:
    provider_name = "stub"
    model = "review-model"

    def complete_json(self, *, system_prompt: str, user_prompt: str, max_tokens: int):
        return JsonCompletionResult(
            payload={
                "summary_short": "Short reviewed memory.",
                "summary_detailed": "Detailed reviewed memory.",
                "research_question": "Can evidence guide planning?",
                "methods": ["Method"],
                "findings": [
                    {
                        "claim": "Evidence supports planning.",
                        "citations": ["[paper pp.1 chunk:one]"],
                        "inference": False,
                    }
                ],
                "limitations": ["Limited external validation."],
                "key_terms": ["evidence"],
                "implementation_notes": [],
                "inferences": [],
            },
            usage={"total_tokens": 20},
        )


def _write_summarized_fixture(root):
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
                        "section_hint": "Results",
                        "text": "Longitudinal source evidence supports planning decisions.",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    EvidenceSummaryGenerator(root, ReviewStubProvider()).summarize_index()
    return harness


def _reviewer(root):
    return SummaryReviewHarness(
        root,
        skill_registry=get_builtin_skill_registry(),
    )


def test_summary_review_inspects_summary_provenance_and_cited_evidence(tmp_path) -> None:
    root = tmp_path / "field"
    _write_summarized_fixture(root)

    report = _reviewer(root).inspect("paper")

    assert report.evaluation_status == "passed"
    assert report.review_status == "unreviewed"
    assert report.provenance["model"] == "review-model"
    assert report.summary["summary_short"] == "Short reviewed memory."
    assert report.evidence[0].citation == "[paper pp.1 chunk:one]"
    assert report.evidence[0].section_hint == "Results"
    assert "source evidence supports planning" in report.evidence[0].snippet


def test_summary_review_records_archived_decisions_and_latest_pointer(tmp_path) -> None:
    root = tmp_path / "field"
    _write_summarized_fixture(root)
    reviewer = _reviewer(root)

    accepted = reviewer.record("paper", decision="accepted", reviewer="researcher")
    revised = reviewer.record(
        "paper",
        decision="needs-revision",
        note="Check the population definition.",
        reviewer="researcher",
    )

    review_dir = root / ".odracir" / "reviews" / "summaries" / "paper"
    archives = [path for path in review_dir.glob("*.json") if path.name != "latest.json"]
    latest = json.loads((review_dir / "latest.json").read_text(encoding="utf-8"))
    assert accepted.review_status == "accepted"
    assert revised.review_status == "needs_revision"
    assert len(archives) == 2
    assert latest["decision"] == "needs_revision"
    assert latest["note"] == "Check the population definition."


def test_summary_review_requires_note_for_revision_request(tmp_path) -> None:
    root = tmp_path / "field"
    _write_summarized_fixture(root)

    with pytest.raises(ValueError, match="require a note"):
        _reviewer(root).record("paper", decision="needs-revision")


def test_summary_review_becomes_stale_when_summary_artifact_changes(tmp_path) -> None:
    root = tmp_path / "field"
    harness = _write_summarized_fixture(root)
    reviewer = _reviewer(root)
    reviewer.record("paper", decision="accepted")
    paper = harness.load_index()["papers"][0]
    summary_path = root / paper["summary_artifact"]
    artifact = json.loads(summary_path.read_text(encoding="utf-8"))
    artifact["summary"]["summary_short"] = "Changed after review."
    summary_path.write_text(json.dumps(artifact), encoding="utf-8")

    report = reviewer.inspect("paper")
    catalog = ResearchCatalogBuilder(root).build(write_artifact=False)

    assert report.review_status == "stale"
    assert "current summary artifact changed" in report.review_error
    assert catalog.records[0]["human_review"]["status"] == "stale"


def test_research_catalog_rebuilds_when_human_review_changes(tmp_path) -> None:
    root = tmp_path / "field"
    _write_summarized_fixture(root)
    first = ResearchCatalogBuilder(root).build()

    _reviewer(root).record("paper", decision="accepted")
    second = ResearchCatalogBuilder(root).build()

    assert second.cached is False
    assert second.input_sha256 != first.input_sha256
    assert second.records[0]["human_review"]["status"] == "accepted"
    assert second.records[0]["artifacts"]["summary_review"].endswith("/latest.json")


def test_inspect_research_summary_agent_tool_is_read_only(tmp_path) -> None:
    root = tmp_path / "field"
    _write_summarized_fixture(root)

    result = execute_tool(
        "inspect_research_summary",
        {"folder": str(root), "paper_id": "paper"},
    )

    assert result["review_status"] == "unreviewed"
    assert result["evidence"][0]["chunk_id"] == "one"
    assert not (root / ".odracir" / "reviews").exists()


def test_review_summary_cli_emits_unicode_json(tmp_path, monkeypatch, capsys) -> None:
    root = tmp_path / "field"
    harness = _write_summarized_fixture(root)
    paper = harness.load_index()["papers"][0]
    summary_path = root / paper["summary_artifact"]
    artifact = json.loads(summary_path.read_text(encoding="utf-8"))
    artifact["summary"]["summary_short"] = "Unicode math: − Δ"
    summary_path.write_text(json.dumps(artifact, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "odracir",
            "review-summary",
            str(root),
            "--paper",
            "paper",
            "--json",
        ],
    )

    main()
    result = json.loads(capsys.readouterr().out)

    assert result["summary"]["summary_short"] == "Unicode math: − Δ"


def test_review_summary_cli_records_explicit_decision(tmp_path, monkeypatch, capsys) -> None:
    root = tmp_path / "field"
    _write_summarized_fixture(root)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "odracir",
            "review-summary",
            str(root),
            "--paper",
            "paper",
            "--decision",
            "accepted",
            "--json",
        ],
    )

    main()
    result = json.loads(capsys.readouterr().out)

    assert result["review_status"] == "accepted"
    assert result["review"]["decision"] == "accepted"
