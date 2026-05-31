import pytest

from odracir.pdf_extraction import PdfTextExtractor
from odracir.status import build_research_status, format_research_status


fitz = pytest.importorskip("fitz")


def test_status_reports_ocr_and_extraction_failure(tmp_path) -> None:
    root = tmp_path / "field"
    papers = root / "papers"
    papers.mkdir(parents=True)

    document = fitz.open()
    document.new_page()
    document.save(papers / "scanned.pdf")
    document.close()
    (papers / "broken.pdf").write_bytes(b"not a PDF")

    PdfTextExtractor(root).extract_index()
    report = build_research_status(root, refresh=False)
    output = format_research_status(report)

    assert report.pdf_papers == 2
    assert report.ocr_statuses == {"not_started": 2}
    assert report.extraction_statuses == {"failed": 1, "needs_ocr": 1}
    assert report.summary_statuses == {"not_started": 2}
    assert report.translation_statuses == {"not_started": 2}
    assert report.needs_ocr[0]["source_file"] == "papers/scanned.pdf"
    assert report.failures[0]["stage"] == "extract"
    assert "Needs OCR: 1" in output
    assert "Failures: 1" in output
