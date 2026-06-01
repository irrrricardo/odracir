"""Resumable ingestion pipeline for a folder-backed paper library."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from odracir.parsers import ParserRegistry
from odracir.preparation import LocalPreparationHarness, LocalPreparationResult
from odracir.providers import JsonCompletionProvider
from odracir.research_memory import ResearchCatalogBuildResult, ResearchCatalogBuilder
from odracir.schemas import INGESTION_RUN_SCHEMA_VERSION
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
from odracir.time_utils import now_iso


INGESTION_RUN_POLICY_VERSION = "0.1"


@dataclass(frozen=True)
class PaperLibraryIngestionResult:
    root: str
    index_path: str
    catalog_path: str | None
    run_id: str
    run_artifact: str
    latest_run_artifact: str
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
        self.runs_dir = self.root / ".odracir" / "jobs" / "ingestion"

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

        started_at = now_iso()
        run_id = _run_id(started_at)
        inputs = self._run_inputs(
            dry_run=dry_run,
            force_prepare=force_prepare,
            force_summaries=force_summaries,
            limit=limit,
            paper_id=paper_id,
        )
        stages: dict[str, Any] = {}
        outputs: dict[str, Any] = {}
        try:
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
            stages["preparation"] = _compact_preparation(preparation)
            outputs["index_path"] = preparation.index_path
            outputs["catalog_path"] = preparation.catalog_path

            plan = build_summary_plan(
                self.root,
                papers_dir=self.papers_dir,
                limit=limit,
                paper_id=paper_id,
                skill=self.skill,
            )
            stages["summary_plan"] = plan.as_dict()

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
            stages["summaries"] = summaries.as_dict() if summaries else None

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
            stages["evaluation"] = _compact_evaluation(evaluation)
            outputs["summary_evaluation_artifact"] = evaluation.artifact_path

            memory = ResearchCatalogBuilder(
                self.root,
                papers_dir=self.papers_dir,
            ).build(write_artifact=not dry_run)
            stages["memory"] = _compact_memory(memory)
            outputs["catalog_path"] = memory.catalog_path or preparation.catalog_path

            status = build_research_status(
                self.root,
                papers_dir=self.papers_dir,
                refresh=False,
            )
            stages["status"] = status.as_dict()
        except Exception as exc:
            try:
                self._write_run_artifact(
                    run_id=run_id,
                    status="failed",
                    started_at=started_at,
                    inputs=inputs,
                    outputs=outputs,
                    stages=stages,
                    error={"type": type(exc).__name__, "message": str(exc)},
                )
            except Exception:
                pass
            raise

        run_artifact, latest_run_artifact = self._write_run_artifact(
            run_id=run_id,
            status="completed",
            started_at=started_at,
            inputs=inputs,
            outputs=outputs,
            stages=stages,
            error=None,
        )
        return PaperLibraryIngestionResult(
            root=str(self.root),
            index_path=preparation.index_path,
            catalog_path=memory.catalog_path or preparation.catalog_path,
            run_id=run_id,
            run_artifact=run_artifact,
            latest_run_artifact=latest_run_artifact,
            skill=self.skill.as_dict(),
            dry_run=dry_run,
            preparation=preparation,
            summary_plan=plan,
            summaries=summaries,
            evaluation=evaluation,
            memory=memory,
            status=status,
        )

    def _run_inputs(
        self,
        *,
        dry_run: bool,
        force_prepare: bool,
        force_summaries: bool,
        limit: int | None,
        paper_id: str | None,
    ) -> dict[str, Any]:
        provider = None
        if self.provider is not None:
            provider = {
                "name": self.provider.provider_name,
                "model": self.provider.model,
            }
        return {
            "root": str(self.root),
            "papers_dir": str(self.papers_dir) if self.papers_dir is not None else None,
            "mode": "dry_run" if dry_run else "execute",
            "paper_id": paper_id,
            "limit": limit,
            "skill": self.skill.as_dict(),
            "parser": self.parser_name,
            "provider": provider,
            "force_prepare": force_prepare,
            "force_summaries": force_summaries,
        }

    def _write_run_artifact(
        self,
        *,
        run_id: str,
        status: str,
        started_at: str,
        inputs: dict[str, Any],
        outputs: dict[str, Any],
        stages: dict[str, Any],
        error: dict[str, str] | None,
    ) -> tuple[str, str]:
        artifact = {
            "schema_version": INGESTION_RUN_SCHEMA_VERSION,
            "policy_version": INGESTION_RUN_POLICY_VERSION,
            "run_id": run_id,
            "status": status,
            "mode": inputs["mode"],
            "started_at": started_at,
            "completed_at": now_iso(),
            "inputs": inputs,
            "outputs": outputs,
            "stages": stages,
            "error": error,
        }
        artifact_path = self.runs_dir / f"{run_id}.json"
        latest_path = self.runs_dir / "latest.json"
        _write_json_atomic(artifact_path, artifact)
        _write_json_atomic(latest_path, artifact)
        return (
            artifact_path.relative_to(self.root).as_posix(),
            latest_path.relative_to(self.root).as_posix(),
        )


def format_paper_library_ingestion(result: PaperLibraryIngestionResult) -> str:
    lines = [
        f"Research folder: {result.root}",
        f"Index: {result.index_path}",
        f"Catalog: {result.catalog_path or 'not written'}",
        f"Run artifact: {result.run_artifact}",
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
                    f"raw_captured={result.summaries.raw_captured}, "
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


def _compact_preparation(result: LocalPreparationResult) -> dict[str, Any]:
    return {
        "parser": result.parser,
        "scan": result.scan.as_dict(),
        "extraction": result.extraction.as_dict(),
        "chunking": result.chunking.as_dict(),
        "memory": _compact_memory(result.memory),
        "status": result.status.as_dict(),
    }


def _compact_evaluation(result: SummaryEvaluationReport) -> dict[str, Any]:
    return {
        "artifact_path": result.artifact_path,
        "cached": result.cached,
        "generated_at": result.generated_at,
        "input_sha256": result.input_sha256,
        "total_papers": result.total_papers,
        "status_counts": result.status_counts,
    }


def _compact_memory(result: ResearchCatalogBuildResult) -> dict[str, Any]:
    return {
        "catalog_path": result.catalog_path,
        "cached": result.cached,
        "generated_at": result.generated_at,
        "input_sha256": result.input_sha256,
        "total_papers": result.total_papers,
        "quality_counts": result.quality_counts,
    }


def _run_id(started_at: str) -> str:
    timestamp = re.sub(r"[^0-9A-Za-z]+", "", started_at)
    return f"{timestamp}-{uuid4().hex[:8]}"


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(f"{path.suffix}.{uuid4().hex}.tmp")
    with temporary_path.open("w", encoding="utf-8", newline="\n") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
        file.write("\n")
    temporary_path.replace(path)


def _format_counts(counts: dict[str, int]) -> str:
    return ", ".join(f"{key}={value}" for key, value in sorted(counts.items())) or "none"
