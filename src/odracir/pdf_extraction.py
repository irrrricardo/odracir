"""PDF text extraction for Odracir research folders."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from odracir.parsers import ParserRegistration, ParserRegistry
from odracir.research_folder import ResearchFolderHarness
from odracir.schemas import ExtractionStatus, TEXT_SCHEMA_VERSION
from odracir.time_utils import now_iso


MIN_TEXT_CHARS_PER_PAGE = 40
OCR_PAGE_RATIO_THRESHOLD = 0.8


@dataclass(frozen=True)
class PdfExtractionSummary:
    root: str
    index_path: str
    total_pdf_papers: int
    extracted: int
    skipped: int
    failed: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class PdfTextExtractor:
    """Extract page-level text artifacts and update folder-level paper records."""

    def __init__(
        self,
        root: str | Path,
        papers_dir: str | Path | None = None,
        *,
        parser_name: str = "pymupdf",
        parser_registry: ParserRegistry | None = None,
    ) -> None:
        self.harness = ResearchFolderHarness(root, papers_dir=papers_dir)
        self.root = self.harness.root
        self.texts_dir = self.root / ".odracir" / "texts"
        self.parser_name = parser_name
        self.parser_registry = parser_registry or build_pdf_parser_registry()

    def extract_index(
        self,
        *,
        force: bool = False,
        limit: int | None = None,
        paper_id: str | None = None,
    ) -> PdfExtractionSummary:
        self.harness.sync_index()
        self.texts_dir.mkdir(parents=True, exist_ok=True)

        index = self.harness.load_index()
        pdf_records = [
            paper
            for paper in index.get("papers", [])
            if isinstance(paper, dict)
            and paper.get("file_type") == "pdf"
            and paper.get("status") != "missing"
            and (paper_id is None or paper.get("id") == paper_id)
        ]
        if limit is not None:
            pdf_records = pdf_records[:limit]

        extracted = 0
        skipped = 0
        failed = 0

        for paper in pdf_records:
            artifact_path = self._artifact_path(paper)
            if self._can_skip(paper, artifact_path, force):
                skipped += 1
                continue

            source_path = self.root / str(paper["source_file"])
            try:
                artifact = self.parser_registry.parse(source_path, self.parser_name)
            except Exception as exc:  # noqa: BLE001 - keep batch extraction resilient.
                failed += 1
                _mark_failed(paper, exc)
                continue

            self._write_artifact(artifact_path, paper, artifact)
            _mark_extracted(
                paper=paper,
                artifact_path=artifact_path,
                root=self.root,
                artifact=artifact,
            )
            extracted += 1

        index["updated_at"] = now_iso()
        self.harness.write_index(index)

        return PdfExtractionSummary(
            root=str(self.root),
            index_path=str(self.harness.index_path),
            total_pdf_papers=len(pdf_records),
            extracted=extracted,
            skipped=skipped,
            failed=failed,
        )

    def _artifact_path(self, paper: dict[str, Any]) -> Path:
        paper_id = str(paper.get("id") or paper.get("file_name") or "paper")
        return self.texts_dir / f"{_safe_name(paper_id)}.json"

    def _can_skip(self, paper: dict[str, Any], artifact_path: Path, force: bool) -> bool:
        if force or not artifact_path.exists():
            return False

        return (
            paper.get("text_extraction_status") in {"extracted", "needs_ocr"}
            and paper.get("text_extraction_sha256") == paper.get("sha256")
        )

    def _write_artifact(
        self,
        artifact_path: Path,
        paper: dict[str, Any],
        artifact: dict[str, Any],
    ) -> None:
        payload = {
            "schema_version": TEXT_SCHEMA_VERSION,
            "paper_id": paper.get("id"),
            "source_file": paper.get("source_file"),
            "source_sha256": paper.get("sha256"),
            **artifact,
        }
        with artifact_path.open("w", encoding="utf-8", newline="\n") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)
            file.write("\n")


def extract_pdf_text(source_path: Path) -> dict[str, Any]:
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("PyMuPDF is required. Install with `pip install pymupdf`.") from exc

    pages: list[dict[str, Any]] = []
    metadata: dict[str, Any]
    parser_version = str(getattr(fitz, "version", "unknown"))

    with fitz.open(source_path) as document:
        metadata = dict(document.metadata or {})
        for page_index, page in enumerate(document, start=1):
            text = page.get_text("text")
            pages.append(
                {
                    "page_number": page_index,
                    "text": text.strip(),
                    "char_count": len(text.strip()),
                }
            )

    text_char_count = sum(page["char_count"] for page in pages)
    empty_text_page_count = sum(
        1 for page in pages if page["char_count"] < MIN_TEXT_CHARS_PER_PAGE
    )
    needs_ocr, ocr_reason = _detect_ocr_need(
        page_count=len(pages),
        text_char_count=text_char_count,
        empty_text_page_count=empty_text_page_count,
    )
    return {
        "parser": "pymupdf",
        "parser_version": parser_version,
        "extracted_at": now_iso(),
        "page_count": len(pages),
        "text_char_count": text_char_count,
        "empty_text_page_count": empty_text_page_count,
        "needs_ocr": needs_ocr,
        "ocr_reason": ocr_reason,
        "metadata": metadata,
        "pages": pages,
    }


def build_pdf_parser_registry() -> ParserRegistry:
    """Build the default registry while keeping future parser adapters pluggable."""
    registry = ParserRegistry()
    registry.register(
        ParserRegistration(
            name="pymupdf",
            file_types=("pdf",),
            parse=extract_pdf_text,
        )
    )
    return registry


def _mark_extracted(
    *,
    paper: dict[str, Any],
    artifact_path: Path,
    root: Path,
    artifact: dict[str, Any],
) -> None:
    status = (
        ExtractionStatus.NEEDS_OCR.value
        if artifact["needs_ocr"]
        else ExtractionStatus.EXTRACTED.value
    )
    paper["text_extraction_status"] = status
    paper["text_extraction_sha256"] = paper.get("sha256")
    paper["text_artifact"] = artifact_path.relative_to(root).as_posix()
    paper["page_count"] = artifact["page_count"]
    paper["text_char_count"] = artifact["text_char_count"]
    paper["empty_text_page_count"] = artifact["empty_text_page_count"]
    paper["needs_ocr"] = artifact["needs_ocr"]
    paper["ocr_reason"] = artifact["ocr_reason"]
    paper["text_extracted_at"] = artifact["extracted_at"]
    paper["text_parser"] = artifact["parser"]
    paper["text_parser_version"] = artifact["parser_version"]
    paper.pop("text_extraction_error", None)
    _invalidate_downstream(paper)
    paper["updated_at"] = now_iso()


def _mark_failed(paper: dict[str, Any], exc: Exception) -> None:
    paper["text_extraction_status"] = ExtractionStatus.FAILED.value
    paper["text_extraction_error"] = str(exc)
    _invalidate_downstream(paper)
    paper["updated_at"] = now_iso()


def _safe_name(value: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value).strip("-")
    return safe or "paper"


def _detect_ocr_need(
    *,
    page_count: int,
    text_char_count: int,
    empty_text_page_count: int,
) -> tuple[bool, str]:
    if page_count == 0:
        return True, "pdf_has_no_pages"
    if text_char_count == 0:
        return True, "no_extractable_text"
    if empty_text_page_count / page_count >= OCR_PAGE_RATIO_THRESHOLD:
        return True, "most_pages_have_little_extractable_text"
    return False, ""


def _invalidate_downstream(paper: dict[str, Any]) -> None:
    paper["chunking_status"] = "not_started"
    paper.pop("chunking_sha256", None)
    paper.pop("chunk_artifact", None)
    paper.pop("chunk_count", None)
    paper.pop("chunked_at", None)
    paper.pop("chunking_error", None)
    paper["summary_status"] = "not_started"
    paper["translation_status"] = "not_started"
