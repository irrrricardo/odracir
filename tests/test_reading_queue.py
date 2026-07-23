import json

import pytest

from odracir.reading_queue import ReadingQueueBuilder
from odracir.research_folder import ResearchFolderHarness


def _write_queue_fixture(root, papers: dict[str, str]) -> ResearchFolderHarness:
    papers_dir = root / "papers"
    papers_dir.mkdir(parents=True)
    for paper_name in papers:
        (papers_dir / f"{paper_name}.pdf").write_bytes(b"%PDF-1.4\n")
    harness = ResearchFolderHarness(root)
    harness.sync_index()
    index = harness.load_index()
    chunks_dir = root / ".odracir" / "chunks"
    chunks_dir.mkdir(parents=True)
    for paper in index["papers"]:
        paper_id = paper["id"]
        paper["text_extraction_status"] = "extracted"
        paper["chunking_status"] = "chunked"
        paper["chunk_artifact"] = f".odracir/chunks/{paper_id}.json"
        (root / paper["chunk_artifact"]).write_text(
            json.dumps(
                {
                    "chunks": [
                        {
                            "id": "one",
                            "page_start": 1,
                            "page_end": 1,
                            "text": papers[paper_id],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
    harness.write_index(index)
    return harness


def test_reading_queue_prioritizes_central_ready_summary_gaps(tmp_path) -> None:
    root = tmp_path / "field"
    _write_queue_fixture(
        root,
        {
            "clinical-world-model": "Clinical trajectory prediction evidence.",
            "world-model-foundations": "General world model foundations.",
            "unrelated-assay": "Assay measurement evidence.",
        },
    )

    report = ReadingQueueBuilder(root).build(limit=3)
    entries = {entry.paper_id: entry for entry in report.entries}

    assert report.action_counts == {"summarize": 3}
    assert report.entries[-1].paper_id == "unrelated-assay"
    assert entries["clinical-world-model"].centrality_score > 0
    assert entries["clinical-world-model"].action == "summarize"
    assert "--skill generic --dry-run" in entries["clinical-world-model"].next_commands[0]
    assert report.artifact_path is not None
    assert (root / report.artifact_path).is_file()


def test_reading_queue_query_prioritizes_relevant_traceable_chunks(tmp_path) -> None:
    root = tmp_path / "field"
    _write_queue_fixture(
        root,
        {
            "general-world-model": "World model overview.",
            "sepsis-treatment": "Sepsis treatment policy with clinical outcomes.",
        },
    )

    report = ReadingQueueBuilder(root).build(
        query="sepsis treatment",
        skill_name="biomedical-paper",
    )
    first = report.entries[0]

    assert first.paper_id == "sepsis-treatment"
    assert first.query_score > 0
    assert first.query_evidence[0]["citation"] == "[sepsis-treatment pp.1 chunk:one]"
    assert "--skill biomedical-paper" in first.next_commands[0]


def test_reading_queue_cache_invalidates_when_chunk_content_changes(tmp_path) -> None:
    root = tmp_path / "field"
    harness = _write_queue_fixture(root, {"paper": "Initial local evidence."})

    first = ReadingQueueBuilder(root).build()
    second = ReadingQueueBuilder(root).build()
    paper = harness.load_index()["papers"][0]
    chunk_path = root / paper["chunk_artifact"]
    chunk_path.write_text(
        '{"chunks": [{"id": "one", "page_start": 1, "page_end": 1, '
        '"text": "Updated local evidence."}]}',
        encoding="utf-8",
    )
    third = ReadingQueueBuilder(root).build()
    ephemeral = ReadingQueueBuilder(root).build(write_artifact=False)

    assert second.cached is True
    assert third.cached is False
    assert third.input_sha256 != first.input_sha256
    assert ephemeral.artifact_path is None


def test_reading_queue_isolates_ocr_and_malformed_chunk_artifacts(tmp_path) -> None:
    root = tmp_path / "field"
    harness = _write_queue_fixture(
        root,
        {
            "good": "Good local evidence for a supervised summary.",
            "malformed": "Temporary content.",
            "scanned": "Temporary OCR placeholder.",
        },
    )
    index = harness.load_index()
    by_id = {paper["id"]: paper for paper in index["papers"]}
    by_id["scanned"]["text_extraction_status"] = "needs_ocr"
    (root / by_id["malformed"]["chunk_artifact"]).write_text("[]", encoding="utf-8")
    harness.write_index(index)

    report = ReadingQueueBuilder(root).build(limit=3)
    entries = {entry.paper_id: entry for entry in report.entries}

    assert entries["good"].action == "summarize"
    assert entries["scanned"].action == "run_ocr"
    assert entries["malformed"].action == "repair_pipeline"
    assert "odracir ocr" in entries["scanned"].next_commands[0]
    assert "--force" in entries["malformed"].next_commands[0]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"limit": 0}, "at least 1"),
        ({"query": "   "}, "must not be empty"),
        ({"skill_name": "imaginary"}, "Unknown research skill"),
    ],
)
def test_reading_queue_validates_arguments(tmp_path, kwargs, message) -> None:
    root = tmp_path / "field"
    _write_queue_fixture(root, {"paper": "Local evidence."})

    with pytest.raises(ValueError, match=message):
        ReadingQueueBuilder(root).build(**kwargs)


def test_reading_queue_prioritizes_raw_capture_normalization(tmp_path) -> None:
    root = tmp_path / "field"
    harness = _write_queue_fixture(root, {"paper": "Preserved raw reading evidence."})
    index = harness.load_index()
    paper = index["papers"][0]
    paper["summary_status"] = "raw_captured"
    paper["raw_summary_artifact"] = ".odracir/raw-summaries/paper/latest.json"
    raw_dir = root / ".odracir" / "raw-summaries" / "paper"
    raw_dir.mkdir(parents=True)
    (raw_dir / "latest.json").write_text('{"content": "Raw reading."}', encoding="utf-8")
    harness.write_index(index)

    entry = ReadingQueueBuilder(root).build(limit=1).entries[0]

    assert entry.action == "normalize_summary"
    assert entry.summary_quality == "raw_captured"
    assert "normalize-summaries" in entry.next_commands[0]
