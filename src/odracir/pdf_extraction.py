"""PDF text extraction for Odracir research folders."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from odracir.research_folder import ResearchFolderHarness


TEXT_SCHEMA_VERSION = "0.1"


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

    def __init__(self, root: str | Path, papers_dir: str | Path | None = None) -> None:
        self.harness = ResearchFolderHarness(root, papers_dir=papers_dir)
        self.root = self.harness.root
        self.texts_dir = self.root / ".odracir" / "texts"

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
                artifact = extract_pdf_text(source_path)
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

        index["updated_at"] = _now_iso()
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
    parser_version = getattr(fitz, "version", None)

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
    return {
        "parser": "pymupdf",
        "parser_version": parser_version,
        "extracted_at": _now_iso(),
        "page_count": len(pages),
        "text_char_count": text_char_count,
        "needs_ocr": text_char_count == 0,
        "metadata": metadata,
        "pages": pages,
    }


def _mark_extracted(
    *,
    paper: dict[str, Any],
    artifact_path: Path,
    root: Path,
    artifact: dict[str, Any],
) -> None:
    status = "needs_ocr" if artifact["needs_ocr"] else "extracted"
    paper["text_extraction_status"] = status
    paper["text_extraction_sha256"] = paper.get("sha256")
    paper["text_artifact"] = artifact_path.relative_to(root).as_posix()
    paper["page_count"] = artifact["page_count"]
    paper["text_char_count"] = artifact["text_char_count"]
    paper["needs_ocr"] = artifact["needs_ocr"]
    paper["text_extracted_at"] = artifact["extracted_at"]
    paper["text_parser"] = artifact["parser"]
    paper["updated_at"] = _now_iso()


def _mark_failed(paper: dict[str, Any], exc: Exception) -> None:
    paper["text_extraction_status"] = "failed"
    paper["text_extraction_error"] = str(exc)
    paper["updated_at"] = _now_iso()


def _safe_name(value: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value).strip("-")
    return safe or "paper"


def _now_iso() -> str:
    return datetime.now(_china_tz()).isoformat(timespec="seconds")


def _china_tz() -> timezone:
    return timezone(timedelta(hours=8), name="Asia/Shanghai")
