"""Folder-level status reporting for Odracir research projects."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from odracir.research_folder import ResearchFolderHarness


@dataclass(frozen=True)
class ResearchStatusReport:
    root: str
    index_path: str
    total_papers: int
    pdf_papers: int
    ocr_statuses: dict[str, int]
    extraction_statuses: dict[str, int]
    chunking_statuses: dict[str, int]
    summary_statuses: dict[str, int]
    needs_ocr: list[dict[str, str]]
    failures: list[dict[str, str]]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_research_status(
    root: str | Path,
    papers_dir: str | Path | None = None,
    *,
    refresh: bool = True,
) -> ResearchStatusReport:
    """Summarize processing states and actionable exceptions for one folder."""
    harness = ResearchFolderHarness(root, papers_dir=papers_dir)
    if refresh:
        harness.sync_index()
    index = harness.load_index()
    papers = [
        paper
        for paper in index.get("papers", [])
        if isinstance(paper, dict) and paper.get("status") != "missing"
    ]
    pdf_papers = [paper for paper in papers if paper.get("file_type") == "pdf"]

    ocr_statuses = _count_statuses(pdf_papers, "ocr_status")
    extraction_statuses = _count_statuses(pdf_papers, "text_extraction_status")
    chunking_statuses = _count_statuses(pdf_papers, "chunking_status")
    summary_statuses = _count_statuses(pdf_papers, "summary_status")
    needs_ocr = [
        {
            "id": str(paper.get("id", "")),
            "source_file": str(paper.get("source_file", "")),
            "reason": str(paper.get("ocr_reason", "")),
        }
        for paper in pdf_papers
        if paper.get("text_extraction_status") == "needs_ocr"
    ]
    failures = [
        {
            "id": str(paper.get("id", "")),
            "source_file": str(paper.get("source_file", "")),
            "stage": stage,
            "error": error,
        }
        for paper in pdf_papers
        for stage, error in _paper_failures(paper)
    ]
    return ResearchStatusReport(
        root=str(harness.root),
        index_path=str(harness.index_path),
        total_papers=len(papers),
        pdf_papers=len(pdf_papers),
        ocr_statuses=ocr_statuses,
        extraction_statuses=extraction_statuses,
        chunking_statuses=chunking_statuses,
        summary_statuses=summary_statuses,
        needs_ocr=needs_ocr,
        failures=failures,
    )


def format_research_status(report: ResearchStatusReport) -> str:
    lines = [
        f"Research folder: {report.root}",
        f"Index: {report.index_path}",
        f"Papers: {report.total_papers} active, {report.pdf_papers} PDF",
        f"OCR preprocessing: {_format_counts(report.ocr_statuses)}",
        f"Extraction: {_format_counts(report.extraction_statuses)}",
        f"Chunking: {_format_counts(report.chunking_statuses)}",
        f"Summaries: {_format_counts(report.summary_statuses)}",
        f"Needs OCR: {len(report.needs_ocr)}",
        f"Failures: {len(report.failures)}",
    ]
    for item in report.needs_ocr:
        lines.append(f"- OCR {item['id']}: {item['reason']} ({item['source_file']})")
    for item in report.failures:
        lines.append(
            f"- {item['stage']} {item['id']}: {item['error']} ({item['source_file']})"
        )
    return "\n".join(lines)


def _count_statuses(papers: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts = Counter(str(paper.get(field, "not_started")) for paper in papers)
    return dict(sorted(counts.items()))


def _format_counts(counts: dict[str, int]) -> str:
    if not counts:
        return "none"
    return ", ".join(f"{status}={count}" for status, count in counts.items())


def _paper_failures(paper: dict[str, Any]) -> list[tuple[str, str]]:
    failures: list[tuple[str, str]] = []
    if paper.get("text_extraction_status") == "failed":
        failures.append(("extract", str(paper.get("text_extraction_error", ""))))
    if paper.get("ocr_status") == "failed":
        failures.append(("ocr", str(paper.get("ocr_error", ""))))
    if paper.get("chunking_status") == "failed":
        failures.append(("chunk", str(paper.get("chunking_error", ""))))
    return failures
