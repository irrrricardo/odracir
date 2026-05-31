"""Local, resumable preparation pipeline for one research folder."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from odracir.chunking import ChunkingSummary, TextChunker
from odracir.parsers import ParserRegistry
from odracir.pdf_extraction import PdfExtractionSummary, PdfTextExtractor
from odracir.research_folder import ResearchFolderHarness, ResearchFolderSyncResult
from odracir.research_memory import ResearchCatalogBuildResult, ResearchCatalogBuilder
from odracir.status import ResearchStatusReport, build_research_status


@dataclass(frozen=True)
class LocalPreparationResult:
    root: str
    index_path: str
    catalog_path: str | None
    parser: str
    scan: ResearchFolderSyncResult
    extraction: PdfExtractionSummary
    chunking: ChunkingSummary
    memory: ResearchCatalogBuildResult
    status: ResearchStatusReport

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class LocalPreparationHarness:
    """Prepare local research artifacts without invoking an LLM or OCR backend."""

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
        self.parser_name = parser_name
        self.parser_registry = parser_registry

    def prepare(
        self,
        *,
        force: bool = False,
        limit: int | None = None,
        paper_id: str | None = None,
    ) -> LocalPreparationResult:
        if limit is not None and limit < 1:
            raise ValueError("Preparation limit must be at least 1.")

        scan = self.harness.sync_index()
        extraction = PdfTextExtractor(
            self.root,
            papers_dir=self.harness.papers_dir,
            parser_name=self.parser_name,
            parser_registry=self.parser_registry,
        ).extract_index(
            force=force,
            limit=limit,
            paper_id=paper_id,
        )
        chunking = TextChunker(
            self.root,
            papers_dir=self.harness.papers_dir,
        ).chunk_index(
            force=force,
            limit=limit,
            paper_id=paper_id,
        )
        memory = ResearchCatalogBuilder(
            self.root,
            papers_dir=self.harness.papers_dir,
        ).build()
        status = build_research_status(
            self.root,
            papers_dir=self.harness.papers_dir,
            refresh=False,
        )
        return LocalPreparationResult(
            root=str(self.root),
            index_path=str(self.harness.index_path),
            catalog_path=memory.catalog_path,
            parser=self.parser_name,
            scan=scan,
            extraction=extraction,
            chunking=chunking,
            memory=memory,
            status=status,
        )


def format_local_preparation(result: LocalPreparationResult) -> str:
    lines = [
        f"Research folder: {result.root}",
        f"Index: {result.index_path}",
        f"Catalog: {result.catalog_path}",
        f"Parser: {result.parser}",
        (
            "Scan: "
            f"{result.scan.total_papers} papers, "
            f"new={result.scan.new_papers}, "
            f"updated={result.scan.updated_papers}, "
            f"missing={result.scan.missing_papers}"
        ),
        (
            "Extraction: "
            f"{result.extraction.total_pdf_papers} PDFs, "
            f"extracted={result.extraction.extracted}, "
            f"skipped={result.extraction.skipped}, "
            f"failed={result.extraction.failed}"
        ),
        (
            "Chunking: "
            f"{result.chunking.eligible_papers} PDFs, "
            f"chunked={result.chunking.chunked}, "
            f"skipped={result.chunking.skipped}, "
            f"blocked={result.chunking.blocked}, "
            f"failed={result.chunking.failed}"
        ),
        (
            "Research memory: "
            f"{result.memory.total_papers} papers, "
            f"cached={'yes' if result.memory.cached else 'no'}, "
            f"{_format_counts(result.memory.quality_counts)}"
        ),
        f"Needs OCR: {len(result.status.needs_ocr)}",
        f"Failures: {len(result.status.failures)}",
        "API usage: none",
    ]
    for item in result.status.needs_ocr:
        lines.append(f"- OCR {item['id']}: {item['reason']} ({item['source_file']})")
    for item in result.status.failures:
        lines.append(
            f"- {item['stage']} {item['id']}: {item['error']} ({item['source_file']})"
        )
    return "\n".join(lines)


def _format_counts(counts: dict[str, int]) -> str:
    return ", ".join(f"{key}={value}" for key, value in sorted(counts.items())) or "none"
