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
