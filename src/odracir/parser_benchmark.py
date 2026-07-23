"""Read-only parser benchmarks over indexed research PDFs."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from odracir.parsers import ParserRegistry
from odracir.pdf_extraction import build_pdf_parser_registry
from odracir.research_folder import ResearchFolderHarness


DEFAULT_BENCHMARK_PARSERS = ("pymupdf", "pymupdf4llm")


@dataclass(frozen=True)
class ParserBenchmarkRecord:
    paper_id: str
    source_file: str
    parser: str
    status: str
    duration_seconds: float
    parser_version: str | None
    page_count: int | None
    text_char_count: int | None
    empty_text_page_count: int | None
    needs_ocr: bool | None
    ocr_reason: str
    content_sha256: str | None
    error: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ParserBenchmarkSummary:
    parser: str
    attempted: int
    succeeded: int
    failed: int
    total_seconds: float
    mean_seconds: float | None
    total_text_chars: int
    compared_to_baseline_papers: int
    text_char_delta_vs_baseline: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ParserBenchmarkReport:
    root: str
    baseline_parser: str
    parsers: list[str]
    papers: int
    records: list[ParserBenchmarkRecord]
    summaries: list[ParserBenchmarkSummary]

    def as_dict(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "baseline_parser": self.baseline_parser,
            "parsers": self.parsers,
            "papers": self.papers,
            "records": [record.as_dict() for record in self.records],
            "summaries": [summary.as_dict() for summary in self.summaries],
        }


class ParserBenchmarkHarness:
    """Compare registered parsers without updating extraction artifacts or index state."""

    def __init__(
        self,
        root: str | Path,
        papers_dir: str | Path | None = None,
        *,
        parser_registry: ParserRegistry | None = None,
    ) -> None:
        self.harness = ResearchFolderHarness(root, papers_dir=papers_dir)
        self.root = self.harness.root
        self.parser_registry = parser_registry or build_pdf_parser_registry()

    def run(
        self,
        *,
        parser_names: tuple[str, ...] = DEFAULT_BENCHMARK_PARSERS,
        paper_id: str | None = None,
        limit: int | None = None,
    ) -> ParserBenchmarkReport:
        parsers = _normalize_parser_names(parser_names)
        for parser_name in parsers:
            self.parser_registry.get(parser_name)
        if limit is not None and limit < 1:
            raise ValueError("Benchmark limit must be at least 1.")

        index = self.harness.load_index()
        papers = [
            paper
            for paper in index.get("papers", [])
            if isinstance(paper, dict)
            and paper.get("file_type") == "pdf"
            and paper.get("status") != "missing"
            and (paper_id is None or paper.get("id") == paper_id)
        ]
        if limit is not None:
            papers = papers[:limit]
        if not papers:
            raise ValueError("No indexed PDF papers matched. Run `odracir scan` first.")

        records = [
            self._run_one(paper, parser_name)
            for paper in papers
            for parser_name in parsers
        ]
        return ParserBenchmarkReport(
            root=str(self.root),
            baseline_parser=parsers[0],
            parsers=list(parsers),
            papers=len(papers),
            records=records,
            summaries=_summarize(records, baseline_parser=parsers[0]),
        )

    def _run_one(
        self,
        paper: dict[str, Any],
        parser_name: str,
    ) -> ParserBenchmarkRecord:
        source_file = str(paper["source_file"])
        source_path = self.root / source_file
        started = time.perf_counter()
        try:
            artifact = self.parser_registry.parse(source_path, parser_name)
        except Exception as exc:  # noqa: BLE001 - preserve comparable batch results.
            return ParserBenchmarkRecord(
                paper_id=str(paper["id"]),
                source_file=source_file,
                parser=parser_name,
                status="failed",
                duration_seconds=_duration(started),
                parser_version=None,
                page_count=None,
                text_char_count=None,
                empty_text_page_count=None,
                needs_ocr=None,
                ocr_reason="",
                content_sha256=None,
                error=str(exc),
            )

        return ParserBenchmarkRecord(
            paper_id=str(paper["id"]),
            source_file=source_file,
            parser=parser_name,
            status="succeeded",
            duration_seconds=_duration(started),
            parser_version=str(artifact.get("parser_version", "unknown")),
            page_count=int(artifact["page_count"]),
            text_char_count=int(artifact["text_char_count"]),
            empty_text_page_count=int(artifact["empty_text_page_count"]),
            needs_ocr=bool(artifact["needs_ocr"]),
            ocr_reason=str(artifact["ocr_reason"]),
            content_sha256=_content_sha256(artifact),
            error="",
        )


def format_parser_benchmark(report: ParserBenchmarkReport) -> str:
    lines = [
        f"Research folder: {report.root}",
        f"Parser benchmark: {report.papers} papers, baseline={report.baseline_parser}",
        "Read-only: extraction artifacts and index state were not modified.",
    ]
    for summary in report.summaries:
        mean = (
            f"{summary.mean_seconds:.3f}s"
            if summary.mean_seconds is not None
            else "n/a"
        )
        lines.append(
            f"- {summary.parser}: {summary.succeeded}/{summary.attempted} succeeded, "
            f"{summary.failed} failed, total={summary.total_seconds:.3f}s, mean={mean}, "
            f"chars={summary.total_text_chars}, "
            f"delta_vs_{report.baseline_parser}={summary.text_char_delta_vs_baseline:+d} "
            f"over {summary.compared_to_baseline_papers} papers"
        )
    failures = [record for record in report.records if record.status == "failed"]
    for record in failures:
        lines.append(f"- FAILED {record.parser} {record.paper_id}: {record.error}")
    return "\n".join(lines)


def _normalize_parser_names(parser_names: tuple[str, ...]) -> tuple[str, ...]:
    parsers = tuple(dict.fromkeys(name.strip() for name in parser_names if name.strip()))
    if not parsers:
        raise ValueError("At least one parser is required.")
    return parsers


def _summarize(
    records: list[ParserBenchmarkRecord],
    *,
    baseline_parser: str,
) -> list[ParserBenchmarkSummary]:
    baseline = {
        record.paper_id: record
        for record in records
        if record.parser == baseline_parser and record.status == "succeeded"
    }
    parser_names = tuple(dict.fromkeys(record.parser for record in records))
    summaries: list[ParserBenchmarkSummary] = []
    for parser_name in parser_names:
        parser_records = [record for record in records if record.parser == parser_name]
        succeeded = [record for record in parser_records if record.status == "succeeded"]
        comparisons = [
            (record, baseline[record.paper_id])
            for record in succeeded
            if record.paper_id in baseline
        ]
        total_seconds = sum(record.duration_seconds for record in parser_records)
        summaries.append(
            ParserBenchmarkSummary(
                parser=parser_name,
                attempted=len(parser_records),
                succeeded=len(succeeded),
                failed=len(parser_records) - len(succeeded),
                total_seconds=round(total_seconds, 6),
                mean_seconds=(
                    round(total_seconds / len(parser_records), 6)
                    if parser_records
                    else None
                ),
                total_text_chars=sum(record.text_char_count or 0 for record in succeeded),
                compared_to_baseline_papers=len(comparisons),
                text_char_delta_vs_baseline=sum(
                    (record.text_char_count or 0) - (baseline_record.text_char_count or 0)
                    for record, baseline_record in comparisons
                ),
            )
        )
    return summaries


def _content_sha256(artifact: dict[str, Any]) -> str:
    pages = [
        {
            "page_number": page["page_number"],
            "text": page["text"],
        }
        for page in artifact.get("pages", [])
    ]
    payload = json.dumps(pages, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _duration(started: float) -> float:
    return round(time.perf_counter() - started, 6)
