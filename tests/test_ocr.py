import json
import subprocess
from pathlib import Path

import pytest

from odracir.ocr import (
    OcrmyPdfCapability,
    OcrmyPdfPreprocessor,
    detect_ocrmypdf_capability,
)
from odracir.pdf_extraction import PdfTextExtractor


fitz = pytest.importorskip("fitz")


def _write_blank_pdf(path: Path) -> None:
    document = fitz.open()
    document.new_page()
    document.save(path)
    document.close()


def _write_text_pdf(path: Path) -> None:
    document = fitz.open()
    document.new_page().insert_text(
        (72, 72),
        "OCRmyPDF derivative text is now visible to the extraction pipeline.",
    )
    document.save(path)
    document.close()


def _available_capability() -> OcrmyPdfCapability:
    return OcrmyPdfCapability(
        name="ocrmypdf",
        available=True,
        command=("ocrmypdf",),
        version="test",
        detail="available",
    )


def test_detect_ocrmypdf_capability_reports_version() -> None:
    def runner(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, stdout="17.1.0\n", stderr="")

    capability = detect_ocrmypdf_capability(command=("ocrmypdf",), runner=runner)

    assert capability.available is True
    assert capability.version == "17.1.0"
    assert capability.command == ("ocrmypdf",)


def test_ocr_preprocessor_writes_derivative_then_extract_uses_it(tmp_path) -> None:
    root = tmp_path / "field"
    papers = root / "papers"
    papers.mkdir(parents=True)
    original_path = papers / "scanned.pdf"
    _write_blank_pdf(original_path)
    PdfTextExtractor(root).extract_index()
    original_bytes = original_path.read_bytes()
    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        _write_text_pdf(Path(command[-1]))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    preprocessor = OcrmyPdfPreprocessor(
        root,
        capability=_available_capability(),
        runner=runner,
    )
    first = preprocessor.preprocess_index(languages=("eng", "chi_sim"), deskew=True)
    second = preprocessor.preprocess_index(languages=("eng", "chi_sim"), deskew=True)
    extracted = PdfTextExtractor(root).extract_index()
    paper = json.loads((root / "odracir_index.json").read_text(encoding="utf-8"))[
        "papers"
    ][0]
    text_artifact = json.loads(
        (root / paper["text_artifact"]).read_text(encoding="utf-8")
    )

    assert first.processed == 1
    assert second.skipped == 1
    assert len(calls) == 1
    assert "--deskew" in calls[0]
    assert "eng+chi_sim" in calls[0]
    assert original_path.read_bytes() == original_bytes
    assert extracted.extracted == 1
    assert paper["ocr_status"] == "processed"
    assert paper["text_extraction_status"] == "extracted"
    assert paper["text_extracted_from"] == ".odracir/ocr/scanned.pdf"
    assert text_artifact["extracted_from"] == ".odracir/ocr/scanned.pdf"


def test_ocr_preprocessor_requires_available_tool_for_eligible_pdf(tmp_path) -> None:
    root = tmp_path / "field"
    papers = root / "papers"
    papers.mkdir(parents=True)
    _write_blank_pdf(papers / "scanned.pdf")
    PdfTextExtractor(root).extract_index()
    capability = OcrmyPdfCapability(
        name="ocrmypdf",
        available=False,
        command=None,
        version=None,
        detail="OCRmyPDF is not available.",
    )

    with pytest.raises(RuntimeError, match="not available"):
        OcrmyPdfPreprocessor(root, capability=capability).preprocess_index()


def test_extraction_reports_missing_current_ocr_derivative(tmp_path) -> None:
    root = tmp_path / "field"
    papers = root / "papers"
    papers.mkdir(parents=True)
    _write_blank_pdf(papers / "scanned.pdf")
    PdfTextExtractor(root).extract_index()

    def runner(command, **kwargs):
        _write_text_pdf(Path(command[-1]))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    OcrmyPdfPreprocessor(
        root,
        capability=_available_capability(),
        runner=runner,
    ).preprocess_index()
    ocr_artifact = root / ".odracir" / "ocr" / "scanned.pdf"
    ocr_artifact.unlink()

    result = PdfTextExtractor(root).extract_index()
    paper = json.loads((root / "odracir_index.json").read_text(encoding="utf-8"))[
        "papers"
    ][0]

    assert result.failed == 1
    assert paper["text_extraction_status"] == "failed"
    assert "Current OCR derivative is missing" in paper["text_extraction_error"]


def test_failed_forced_ocr_run_invalidates_previous_extraction(tmp_path) -> None:
    root = tmp_path / "field"
    papers = root / "papers"
    papers.mkdir(parents=True)
    _write_blank_pdf(papers / "scanned.pdf")
    PdfTextExtractor(root).extract_index()

    def successful_runner(command, **kwargs):
        _write_text_pdf(Path(command[-1]))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    preprocessor = OcrmyPdfPreprocessor(
        root,
        capability=_available_capability(),
        runner=successful_runner,
    )
    preprocessor.preprocess_index()
    PdfTextExtractor(root).extract_index()

    def failed_runner(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="OCR failed")

    result = OcrmyPdfPreprocessor(
        root,
        capability=_available_capability(),
        runner=failed_runner,
    ).preprocess_index(force=True)
    paper = json.loads((root / "odracir_index.json").read_text(encoding="utf-8"))[
        "papers"
    ][0]

    assert result.failed == 1
    assert paper["ocr_status"] == "failed"
    assert paper["text_extraction_status"] == "not_started"
    assert "text_artifact" not in paper
