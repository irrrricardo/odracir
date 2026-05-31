import json

import pytest

from odracir.chunking import TextChunker
from odracir.pdf_extraction import PdfTextExtractor


fitz = pytest.importorskip("fitz")


def _write_pdf(path, text: str | None) -> None:
    document = fitz.open()
    page = document.new_page()
    if text:
        page.insert_text((72, 72), text)
    document.save(path)
    document.close()


def test_chunking_writes_traceable_artifact_and_skips_unchanged_text(tmp_path) -> None:
    root = tmp_path / "field"
    papers = root / "papers"
    papers.mkdir(parents=True)
    _write_pdf(
        papers / "paper-a.pdf",
        "1 Introduction\n"
        "This paper describes a stable research method with enough extractable text. "
        "The chunk must preserve a page-level citation for later retrieval.",
    )

    PdfTextExtractor(root).extract_index()
    first = TextChunker(root).chunk_index()
    index = json.loads((root / "odracir_index.json").read_text(encoding="utf-8"))
    paper = index["papers"][0]
    artifact = json.loads((root / paper["chunk_artifact"]).read_text(encoding="utf-8"))
    chunk_ids = [chunk["id"] for chunk in artifact["chunks"]]

    second = TextChunker(root).chunk_index()
    forced = TextChunker(root).chunk_index(force=True)
    unchanged = json.loads((root / paper["chunk_artifact"]).read_text(encoding="utf-8"))

    assert first.chunked == 1
    assert second.skipped == 1
    assert forced.chunked == 1
    assert paper["chunking_status"] == "chunked"
    assert artifact["chunk_count"] == 1
    assert artifact["chunks"][0]["page_start"] == 1
    assert artifact["chunks"][0]["page_end"] == 1
    assert [chunk["id"] for chunk in unchanged["chunks"]] == chunk_ids


def test_chunking_blocks_pdf_that_needs_ocr(tmp_path) -> None:
    root = tmp_path / "field"
    papers = root / "papers"
    papers.mkdir(parents=True)
    _write_pdf(papers / "scanned.pdf", None)

    PdfTextExtractor(root).extract_index()
    result = TextChunker(root).chunk_index()
    paper = json.loads((root / "odracir_index.json").read_text(encoding="utf-8"))[
        "papers"
    ][0]

    assert result.blocked == 1
    assert paper["chunking_status"] == "blocked"


def test_failed_forced_chunking_removes_stale_downstream_artifacts(tmp_path) -> None:
    root = tmp_path / "field"
    papers = root / "papers"
    papers.mkdir(parents=True)
    _write_pdf(
        papers / "paper.pdf",
        "Stable extracted text with enough content for the first chunking pass.",
    )
    PdfTextExtractor(root).extract_index()
    chunker = TextChunker(root)
    chunker.chunk_index()
    index = chunker.harness.load_index()
    paper = index["papers"][0]
    paper["summary_status"] = "summarized"
    paper["summary_artifact"] = ".odracir/summaries/paper.json"
    paper["translation_status"] = "translated"
    paper["translation_artifact"] = ".odracir/translations/paper.zh-CN.json"
    chunker.harness.write_index(index)
    (root / paper["text_artifact"]).write_text("[]", encoding="utf-8")

    result = chunker.chunk_index(force=True)
    paper = chunker.harness.load_index()["papers"][0]

    assert result.failed == 1
    assert paper["chunking_status"] == "failed"
    assert "chunk_artifact" not in paper
    assert paper["summary_status"] == "not_started"
    assert "summary_artifact" not in paper
    assert paper["translation_status"] == "not_started"
    assert "translation_artifact" not in paper
