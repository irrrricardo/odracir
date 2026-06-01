"""Resumable ingestion pipeline for a folder-backed paper library."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from odracir.parsers import ParserRegistry
from odracir.preparation import LocalPreparationHarness, LocalPreparationResult
from odracir.providers import JsonCompletionProvider
from odracir.research_memory import ResearchCatalogBuildResult, ResearchCatalogBuilder
from odracir.status import ResearchStatusReport, build_research_status
from odracir.summarization import (
    EvidenceSummaryGenerator,
    SummaryPlan,
    SummaryRunResult,
    build_summary_plan,
)
from odracir.summary_evaluation import SummaryEvaluationHarness, SummaryEvaluationReport
from odracir.skills import (
    DEFAULT_RESEARCH_SKILL,
    ResearchSkillManifest,
    get_builtin_skill_registry,
)


@dataclass(frozen=True)
class PaperLibraryIngestionResult:
    root: str
    index_path: str
    catalog_path: str | None
    skill: dict[str, Any]
    dry_run: bool
    preparation: LocalPreparationResult
    summary_plan: SummaryPlan
    summaries: SummaryRunResult | None
    evaluation: SummaryEvaluationReport
    memory: ResearchCatalogBuildResult
    status: ResearchStatusReport

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class PaperLibraryIngestionHarness:
    """Prepare, summarize, audit, and persist one folder-backed paper library."""

    def __init__(
        self,
        root: str | Path,
        provider: JsonCompletionProvider | None = None,
        papers_dir: str | Path | None = None,
        *,
        skill: ResearchSkillManifest = DEFAULT_RESEARCH_SKILL,
        parser_name: str = "pymupdf",
        parser_registry: ParserRegistry | None = None,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.papers_dir = papers_dir
        self.provider = provider
        self.skill = skill
        self.parser_name = parser_name
        self.parser_registry = parser_registry

    def ingest(
        self,
        *,
        dry_run: bool = False,
        force_prepare: bool = False,
        force_summaries: bool = False,
        limit: int | None = None,
        paper_id: str | None = None,
    ) -> PaperLibraryIngestionResult:
        if limit is not None and limit < 1:
            raise ValueError("Library ingestion limit must be at least 1.")
        if not dry_run and self.provider is None:
            raise ValueError("Library ingestion requires a provider unless dry_run=True.")

        preparation = LocalPreparationHarness(
            self.root,
            papers_dir=self.papers_dir,
            parser_name=self.parser_name,
            parser_registry=self.parser_registry,
        ).prepare(
            force=force_prepare,
            limit=limit,
            paper_id=paper_id,
        )
        plan = build_summary_plan(
            self.root,
            papers_dir=self.papers_dir,
            limit=limit,
            paper_id=paper_id,
            skill=self.skill,
        )

        summaries: SummaryRunResult | None = None
        if not dry_run:
            summaries = EvidenceSummaryGenerator(
                self.root,
                self.provider,  # type: ignore[arg-type]
                papers_dir=self.papers_dir,
                skill=self.skill,
            ).summarize_index(
                force=force_summaries,
                limit=limit,
                paper_id=paper_id,
            )

        evaluation = SummaryEvaluationHarness(
            self.root,
            papers_dir=self.papers_dir,
            skill_registry=get_builtin_skill_registry(),
        ).evaluate(
            paper_id=paper_id,
            limit=limit,
            expected_skill=self.skill,
            write_artifact=not dry_run,
        )
        memory = ResearchCatalogBuilder(
            self.root,
            papers_dir=self.papers_dir,
        ).build(write_artifact=not dry_run)
        status = build_research_status(
            self.root,
            papers_dir=self.papers_dir,
            refresh=False,
        )
        return PaperLibraryIngestionResult(
            root=str(self.root),
            index_path=preparation.index_path,
            catalog_path=memory.catalog_path or preparation.catalog_path,
            skill=self.skill.as_dict(),
            dry_run=dry_run,
            preparation=preparation,
            summary_plan=plan,
            summaries=summaries,
            evaluation=evaluation,
            memory=memory,
            status=status,
        )


def format_paper_library_ingestion(result: PaperLibraryIngestionResult) -> str:
    lines = [
        f"Research folder: {result.root}",
        f"Index: {result.index_path}",
        f"Catalog: {result.catalog_path or 'not written'}",
        f"Research skill: {result.skill['name']}@{result.skill['version']}",
        (
            "Preparation: "
            f"PDFs={result.preparation.extraction.total_pdf_papers}, "
            f"extracted={result.preparation.extraction.extracted}, "
            f"chunked={result.preparation.chunking.chunked}, "
            f"needs_ocr={len(result.preparation.status.needs_ocr)}"
        ),
        (
            "Summary plan: "
            f"papers={len(result.summary_plan.papers)}, "
            f"ready={result.summary_plan.ready}, "
            f"blocked={result.summary_plan.blocked}, "
            f"failed={result.summary_plan.failed}"
        ),
    ]
    if result.summaries is None:
        lines.append("Summaries: dry run, no DeepSeek API call made")
    else:
        lines.extend(
            [
                (
                    "Summaries: "
                    f"eligible={result.summaries.eligible_papers}, "
                    f"summarized={result.summaries.summarized}, "
                    f"skipped={result.summaries.skipped}, "
                    f"blocked={result.summaries.blocked}, "
                    f"failed={result.summaries.failed}"
                ),
                f"Summary strategies: {_format_counts(result.summaries.strategy_counts)}",
                f"API usage: {_format_counts(result.summaries.usage)}",
            ]
        )
    lines.extend(
        [
            f"Summary quality: {_format_counts(result.evaluation.status_counts)}",
            f"Folder state: {_format_counts(result.memory.quality_counts)}",
            f"Failures: {len(result.status.failures)}",
        ]
    )
    for item in result.status.failures:
        lines.append(
            f"- {item['stage']} {item['id']}: {item['error']} ({item['source_file']})"
        )
    return "\n".join(lines)


def _format_counts(counts: dict[str, int]) -> str:
    return ", ".join(f"{key}={value}" for key, value in sorted(counts.items())) or "none"
