import json

import pytest

from odracir.pdf_extraction import PdfTextExtractor


fitz = pytest.importorskip("fitz")


def test_pdf_text_extractor_writes_artifact_and_updates_index(tmp_path) -> None:
    root = tmp_path / "field"
    papers = root / "papers"
    papers.mkdir(parents=True)
    pdf_path = papers / "paper-a.pdf"

    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "Hello Odracir PDF extraction.")
    document.save(pdf_path)
    document.close()

    result = PdfTextExtractor(root).extract_index()

    assert result.total_pdf_papers == 1
    assert result.extracted == 1
    assert result.failed == 0

    index = json.loads((root / "odracir_index.json").read_text(encoding="utf-8"))
    paper = index["papers"][0]
    assert paper["text_extraction_status"] == "extracted"
    assert paper["page_count"] == 1
    assert paper["text_char_count"] > 0

    artifact = json.loads((root / paper["text_artifact"]).read_text(encoding="utf-8"))
    assert artifact["paper_id"] == paper["id"]
    assert "Hello Odracir" in artifact["pages"][0]["text"]


def test_pdf_text_extractor_skips_current_artifact(tmp_path) -> None:
    root = tmp_path / "field"
    papers = root / "papers"
    papers.mkdir(parents=True)
    pdf_path = papers / "paper-a.pdf"

    document = fitz.open()
    document.new_page().insert_text((72, 72), "Stable text.")
    document.save(pdf_path)
    document.close()

    PdfTextExtractor(root).extract_index()
    result = PdfTextExtractor(root).extract_index()

    assert result.extracted == 0
    assert result.skipped == 1
