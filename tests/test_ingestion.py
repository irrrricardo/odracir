from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from odracir.paper_study.ingestion import ensure_pdf_chunk_artifacts
from odracir.paper_study.planning import load_chunk_artifact


def _write_pdf(path: Path, text: str | None) -> None:
    document = fitz.open()
    page = document.new_page()
    if text is not None:
        page.insert_text((72, 72), text)
    document.save(path)
    document.close()


def test_pdf_ingestion_is_reusable_and_produces_valid_chunks(tmp_path: Path) -> None:
    pdf = tmp_path / "Paper One.pdf"
    _write_pdf(pdf, "Abstract: A knockout experiment caused a rescue response.")

    first = ensure_pdf_chunk_artifacts(tmp_path)
    second = ensure_pdf_chunk_artifacts(tmp_path)

    assert first == second
    assert len(first) == 1
    artifact = load_chunk_artifact(first[0])
    assert artifact.paper_id == "Paper-One"
    assert artifact.source_file == "Paper One.pdf"
    assert artifact.chunk_count == 1
    assert artifact.chunks[0].section_hint == "abstract"
    assert artifact.chunks[0].page_start == 1


def test_pdf_ingestion_rejects_a_scan_without_extractable_text(tmp_path: Path) -> None:
    _write_pdf(tmp_path / "scan.pdf", None)

    with pytest.raises(ValueError, match="requires OCR"):
        ensure_pdf_chunk_artifacts(tmp_path)
