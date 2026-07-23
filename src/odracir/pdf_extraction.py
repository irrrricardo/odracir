"""PDF text extraction for Odracir research folders."""

from __future__ import annotations

import json
import re
import hashlib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from odracir.docling_adapter import extract_pdf_text_with_docling
from odracir.parsers import ParserRegistration, ParserRegistry
from odracir.pdf_artifacts import build_pdf_text_artifact
from odracir.processing_state import invalidate_chunking, invalidate_text_extraction
from odracir.pymupdf4llm_adapter import extract_pdf_text_with_pymupdf4llm
from odracir.research_folder import ResearchFolderHarness
from odracir.schemas import ExtractionStatus, TEXT_SCHEMA_VERSION
from odracir.time_utils import now_iso


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
            try:
                source_path = self._extraction_source_path(paper)
                input_sha256 = _sha256_file(source_path)
                if self._can_skip(paper, artifact_path, input_sha256, force):
                    skipped += 1
                    continue
                artifact = self.parser_registry.parse(source_path, self.parser_name)
                self._write_artifact(
                    artifact_path,
                    paper,
                    artifact,
                    source_path=source_path,
                    input_sha256=input_sha256,
                )
                _mark_extracted(
                    paper=paper,
                    artifact_path=artifact_path,
                    root=self.root,
                    artifact=artifact,
                    source_path=source_path,
                    input_sha256=input_sha256,
                )
            except Exception as exc:  # noqa: BLE001 - keep batch extraction resilient.
                failed += 1
                _mark_failed(paper, exc)
                continue
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

    def _extraction_source_path(self, paper: dict[str, Any]) -> Path:
        ocr_artifact = paper.get("ocr_artifact")
        if (
            paper.get("ocr_status") == "processed"
            and paper.get("ocr_source_sha256") == paper.get("sha256")
        ):
            if not isinstance(ocr_artifact, str) or not (self.root / ocr_artifact).is_file():
                raise FileNotFoundError(
                    "Current OCR derivative is missing. Re-run `odracir ocr --force`."
                )
            return self.root / ocr_artifact
        return self.root / str(paper["source_file"])

    def _can_skip(
        self,
        paper: dict[str, Any],
        artifact_path: Path,
        input_sha256: str,
        force: bool,
    ) -> bool:
        if force or not artifact_path.exists():
            return False

        return (
            paper.get("text_extraction_status") in {"extracted", "needs_ocr"}
            and paper.get("text_extraction_sha256") == paper.get("sha256")
            and paper.get("text_extraction_input_sha256") == input_sha256
            and paper.get("text_parser") == self.parser_name
        )

    def _write_artifact(
        self,
        artifact_path: Path,
        paper: dict[str, Any],
        artifact: dict[str, Any],
        *,
        source_path: Path,
        input_sha256: str,
    ) -> None:
        payload = {
            "schema_version": TEXT_SCHEMA_VERSION,
            "paper_id": paper.get("id"),
            "source_file": paper.get("source_file"),
            "source_sha256": paper.get("sha256"),
            "extracted_from": source_path.relative_to(self.root).as_posix(),
            "extraction_input_sha256": input_sha256,
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
    parser_version = _pymupdf_version(fitz)

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

    return build_pdf_text_artifact(
        parser="pymupdf",
        parser_version=parser_version,
        metadata=metadata,
        pages=pages,
    )


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
    registry.register(
        ParserRegistration(
            name="docling",
            file_types=("pdf",),
            parse=extract_pdf_text_with_docling,
        )
    )
    registry.register(
        ParserRegistration(
            name="pymupdf4llm",
            file_types=("pdf",),
            parse=extract_pdf_text_with_pymupdf4llm,
        )
    )
    return registry


def _mark_extracted(
    *,
    paper: dict[str, Any],
    artifact_path: Path,
    root: Path,
    artifact: dict[str, Any],
    source_path: Path,
    input_sha256: str,
) -> None:
    status = (
        ExtractionStatus.NEEDS_OCR.value
        if artifact["needs_ocr"]
        else ExtractionStatus.EXTRACTED.value
    )
    paper["text_extraction_status"] = status
    paper["text_extraction_sha256"] = paper.get("sha256")
    paper["text_extraction_input_sha256"] = input_sha256
    paper["text_extracted_from"] = source_path.relative_to(root).as_posix()
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
    invalidate_text_extraction(paper)
    paper["text_extraction_status"] = ExtractionStatus.FAILED.value
    paper["text_extraction_error"] = str(exc)
    paper["updated_at"] = now_iso()


def _safe_name(value: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value).strip("-")
    return safe or "paper"


def _invalidate_downstream(paper: dict[str, Any]) -> None:
    invalidate_chunking(paper)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _pymupdf_version(fitz: Any) -> str:
    value = getattr(fitz, "version", "unknown")
    if isinstance(value, (tuple, list)) and value:
        value = value[0]
    return str(value)
