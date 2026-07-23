"""Explicit OCRmyPDF preprocessing for PDFs that need a text layer."""

from __future__ import annotations

import hashlib
import importlib.util
import os
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

from odracir.processing_state import invalidate_ocr, invalidate_text_extraction
from odracir.research_folder import ResearchFolderHarness
from odracir.time_utils import now_iso


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class OcrmyPdfCapability:
    name: str
    available: bool
    command: tuple[str, ...] | None
    version: str | None
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OcrPreprocessSummary:
    root: str
    index_path: str
    eligible_papers: int
    processed: int
    skipped: int
    failed: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def detect_ocrmypdf_capability(
    *,
    command: Sequence[str] | None = None,
    runner: CommandRunner = subprocess.run,
) -> OcrmyPdfCapability:
    resolved_command = tuple(command) if command else _find_ocrmypdf_command()
    if resolved_command is None:
        return OcrmyPdfCapability(
            name="ocrmypdf",
            available=False,
            command=None,
            version=None,
            detail=(
                'Install optional support with `pip install -e ".[ocr]"`, then install '
                "the required OCRmyPDF system dependencies."
            ),
        )

    try:
        result = runner(
            [*resolved_command, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return OcrmyPdfCapability(
            name="ocrmypdf",
            available=False,
            command=resolved_command,
            version=None,
            detail=f"OCRmyPDF command could not run: {exc}",
        )

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "unknown error").strip()
        return OcrmyPdfCapability(
            name="ocrmypdf",
            available=False,
            command=resolved_command,
            version=None,
            detail=f"OCRmyPDF command failed its version check: {detail}",
        )

    return OcrmyPdfCapability(
        name="ocrmypdf",
        available=True,
        command=resolved_command,
        version=result.stdout.strip() or result.stderr.strip() or "unknown",
        detail=(
            "CLI version check succeeded; available for explicit preprocessing of PDFs "
            "marked as needs_ocr. Full system dependency readiness is verified on use."
        ),
    )


class OcrmyPdfPreprocessor:
    """Create OCR-enhanced local derivatives without modifying source PDFs."""

    def __init__(
        self,
        root: str | Path,
        papers_dir: str | Path | None = None,
        *,
        capability: OcrmyPdfCapability | None = None,
        runner: CommandRunner = subprocess.run,
    ) -> None:
        self.harness = ResearchFolderHarness(root, papers_dir=papers_dir)
        self.root = self.harness.root
        self.ocr_dir = self.root / ".odracir" / "ocr"
        self.capability = capability or detect_ocrmypdf_capability()
        self.runner = runner

    def preprocess_index(
        self,
        *,
        force: bool = False,
        limit: int | None = None,
        paper_id: str | None = None,
        languages: Sequence[str] = ("eng",),
        deskew: bool = False,
        all_pdfs: bool = False,
    ) -> OcrPreprocessSummary:
        normalized_languages = _normalize_languages(languages)
        self.harness.sync_index()
        index = self.harness.load_index()
        papers = [
            paper
            for paper in index.get("papers", [])
            if isinstance(paper, dict)
            and paper.get("file_type") == "pdf"
            and paper.get("status") != "missing"
            and (
                all_pdfs
                or paper.get("text_extraction_status") == "needs_ocr"
                or paper.get("ocr_status") == "processed"
            )
            and (paper_id is None or paper.get("id") == paper_id)
        ]
        if limit is not None:
            papers = papers[:limit]

        if papers and not self.capability.available:
            raise RuntimeError(self.capability.detail)
        if papers and not self.capability.command:
            raise RuntimeError("OCRmyPDF capability is missing its command.")

        self.ocr_dir.mkdir(parents=True, exist_ok=True)
        processed = skipped = failed = 0
        for paper in papers:
            artifact_path = self._artifact_path(paper)
            if self._can_skip(paper, artifact_path, normalized_languages, deskew, force):
                skipped += 1
                continue

            source_path = self.root / str(paper["source_file"])
            temporary_path = artifact_path.with_suffix(".tmp.pdf")
            temporary_path.unlink(missing_ok=True)
            command = [
                *self.capability.command,
                "--skip-text",
                "--output-type",
                "pdf",
                "--language",
                "+".join(normalized_languages),
            ]
            if deskew:
                command.append("--deskew")
            command.extend([str(source_path), str(temporary_path)])
            try:
                result = self.runner(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=None,
                    check=False,
                )
                if result.returncode != 0:
                    detail = (result.stderr or result.stdout or "unknown error").strip()
                    raise RuntimeError(detail)
                if not temporary_path.is_file():
                    raise RuntimeError("OCRmyPDF did not create its output PDF.")
                os.replace(temporary_path, artifact_path)
            except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
                temporary_path.unlink(missing_ok=True)
                failed += 1
                _mark_failed(paper, exc)
                continue

            _mark_processed(
                paper=paper,
                artifact_path=artifact_path,
                root=self.root,
                languages=normalized_languages,
                deskew=deskew,
                capability=self.capability,
            )
            processed += 1

        index["updated_at"] = now_iso()
        self.harness.write_index(index)
        return OcrPreprocessSummary(
            root=str(self.root),
            index_path=str(self.harness.index_path),
            eligible_papers=len(papers),
            processed=processed,
            skipped=skipped,
            failed=failed,
        )

    def _artifact_path(self, paper: dict[str, Any]) -> Path:
        return self.ocr_dir / f"{_safe_name(str(paper['id']))}.pdf"

    def _can_skip(
        self,
        paper: dict[str, Any],
        artifact_path: Path,
        languages: tuple[str, ...],
        deskew: bool,
        force: bool,
    ) -> bool:
        return (
            not force
            and artifact_path.is_file()
            and paper.get("ocr_status") == "processed"
            and paper.get("ocr_source_sha256") == paper.get("sha256")
            and paper.get("ocr_languages") == list(languages)
            and paper.get("ocr_deskew") is deskew
        )


def _mark_processed(
    *,
    paper: dict[str, Any],
    artifact_path: Path,
    root: Path,
    languages: tuple[str, ...],
    deskew: bool,
    capability: OcrmyPdfCapability,
) -> None:
    invalidate_text_extraction(paper)
    paper["ocr_status"] = "processed"
    paper["ocr_artifact"] = artifact_path.relative_to(root).as_posix()
    paper["ocr_artifact_sha256"] = _sha256_file(artifact_path)
    paper["ocr_source_sha256"] = paper["sha256"]
    paper["ocr_provider"] = "ocrmypdf"
    paper["ocr_provider_version"] = capability.version or "unknown"
    paper["ocr_languages"] = list(languages)
    paper["ocr_deskew"] = deskew
    paper["ocr_processed_at"] = now_iso()
    paper.pop("ocr_error", None)
    paper["updated_at"] = now_iso()


def _mark_failed(paper: dict[str, Any], exc: Exception) -> None:
    invalidate_ocr(paper)
    paper["ocr_status"] = "failed"
    paper["ocr_error"] = str(exc)
    paper["updated_at"] = now_iso()


def _find_ocrmypdf_command() -> tuple[str, ...] | None:
    executable = shutil.which("ocrmypdf")
    if executable:
        return (executable,)
    if importlib.util.find_spec("ocrmypdf") is not None:
        return (sys.executable, "-m", "ocrmypdf")
    return None


def _normalize_languages(languages: Sequence[str]) -> tuple[str, ...]:
    normalized = tuple(language.strip() for language in languages if language.strip())
    if not normalized:
        raise ValueError("At least one OCR language is required.")
    return normalized


def _safe_name(value: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value).strip("-")
    return safe or "paper"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
