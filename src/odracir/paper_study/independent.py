"""Independent one-PDF-to-one-JSON Odracir 2.2 pipeline."""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from pydantic import Field

from odracir.paper_study.canonicalization import (
    apply_canonicalization_plan,
    plan_canonicalization,
)
from odracir.paper_study.extraction import (
    ExtractionStageFailure,
    JsonCompletionProvider,
    extract_paper_study,
)
from odracir.paper_study.models import (
    PROVENANCE_SOURCE_TEXT_CONTEXT_KEY,
    PaperStudyPacketV2,
    StrictModel,
)
from odracir.paper_study.planning import (
    build_extraction_plan,
    load_chunk_artifact,
)
from odracir.paper_study.quality import evaluate_packet_quality
from odracir.paper_study.run_reporting import (
    PaperRunRecord,
    PricingSnapshot,
    finalize_record,
    stage_metrics,
    write_run_report,
)
from odracir.paper_study.semantic_quality import evaluate_semantic_extraction_quality
from odracir.paper_study.scheduler import PaperIndexEntry


_SAFE_PAPER_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class IndependentRunSummary(StrictModel):
    """Compact stdout result pointing to packets and run telemetry."""

    schema_version: str = "2.2-run.1"
    input_folder: str = Field(min_length=1)
    output_folder: str = Field(min_length=1)
    report_folder: str = Field(min_length=1)
    paper_ids: tuple[str, ...]
    output_paths: dict[str, str]
    failures: dict[str, str]
    report_paths: dict[str, str]

    @property
    def succeeded(self) -> int:
        return len(self.output_paths)

    @property
    def failed(self) -> int:
        return len(self.failures)


def run_independent_extractions(
    entries: list[PaperIndexEntry],
    provider: JsonCompletionProvider,
    *,
    input_folder: str | Path,
    output_folder: str | Path,
    report_folder: str | Path,
    max_chunks: int = 4,
    max_tokens: int = 16_000,
    validation_retries: int = 1,
    minimum_quality_score: float = 0.6,
    pricing: PricingSnapshot | None = None,
) -> IndependentRunSummary:
    """Extract every entry independently, with no shared state or corpus ordering."""

    root = Path(output_folder).expanduser().resolve()
    _prepare_empty_output_folder(root)
    report_root = Path(report_folder).expanduser().resolve()
    if (
        root == report_root
        or root.is_relative_to(report_root)
        or report_root.is_relative_to(root)
    ):
        raise ValueError("output and report folders must be separate, non-nested paths")
    if report_root.exists() and any(report_root.iterdir()):
        raise ValueError(f"report folder must be empty: {report_root}")
    started_at = datetime.now(timezone.utc)
    resolved_pricing = pricing or PricingSnapshot()
    outputs: dict[str, str] = {}
    failures: dict[str, str] = {}
    records: list[PaperRunRecord] = []
    ordered = sorted(entries, key=lambda item: (item.paper_id.casefold(), item.source_path))
    for entry in ordered:
        record = _execute_one_paper(
            entry,
            provider,
            output_folder=root,
            max_chunks=max_chunks,
            max_tokens=max_tokens,
            validation_retries=validation_retries,
            minimum_quality_score=minimum_quality_score,
            pricing=resolved_pricing,
        )
        records.append(record)
        if record.status == "succeeded":
            assert record.output_file is not None
            outputs[entry.paper_id] = record.output_file
        else:
            failures[entry.paper_id] = record.error_message or record.error_type or "failed"
    _, report_paths = write_run_report(
        records,
        report_folder=report_root,
        input_folder=str(Path(input_folder).expanduser().resolve()),
        output_folder=str(root),
        started_at=started_at,
        pricing=resolved_pricing,
    )
    return IndependentRunSummary(
        input_folder=str(Path(input_folder).expanduser().resolve()),
        output_folder=str(root),
        report_folder=str(report_root),
        paper_ids=tuple(entry.paper_id for entry in ordered),
        output_paths=outputs,
        failures=failures,
        report_paths=report_paths,
    )


def _execute_one_paper(
    entry: PaperIndexEntry,
    provider: JsonCompletionProvider,
    *,
    output_folder: Path,
    max_chunks: int,
    max_tokens: int,
    validation_retries: int,
    minimum_quality_score: float,
    pricing: PricingSnapshot,
) -> PaperRunRecord:
    record = PaperRunRecord(
        paper_id=entry.paper_id,
        source_file=entry.source_path,
        status="failed",
    )
    try:
        if not _SAFE_PAPER_ID_RE.fullmatch(entry.paper_id) or entry.paper_id in {".", ".."}:
            raise ValueError(f"unsafe paper_id: {entry.paper_id!r}")
        artifact = load_chunk_artifact(entry.source_path)
        if artifact.paper_id != entry.paper_id:
            raise ValueError("chunk artifact paper_id does not match its input entry")
        plan = build_extraction_plan(
            artifact,
            source_chunk_artifact=entry.source_path,
            max_chunks=max_chunks,
        )
        record = record.model_copy(
            update={
                "source_file": artifact.source_file,
                "source_sha256": artifact.source_sha256,
                "pages": max(chunk.page_end for chunk in artifact.chunks),
                "source_chunks": len(artifact.chunks),
                "selected_chunks": len(plan.selected_chunk_ids),
            }
        )
        extraction_started = time.perf_counter()
        try:
            extracted = extract_paper_study(
                artifact,
                plan,
                provider,
                max_tokens=max_tokens,
                validation_retries=validation_retries,
            )
        except ExtractionStageFailure as exc:
            record = record.model_copy(
                update={
                    "extraction": stage_metrics(
                        model=exc.model,
                        attempts=exc.attempts,
                        usage=exc.usage,
                        latency_seconds=time.perf_counter() - extraction_started,
                        pricing=pricing,
                        finish_reason=exc.finish_reason,
                        usage_complete=exc.usage_complete,
                    )
                }
            )
            raise
        record = record.model_copy(
            update={
                "extraction": stage_metrics(
                    model=extracted.model,
                    attempts=extracted.attempts,
                    usage=extracted.usage,
                    latency_seconds=time.perf_counter() - extraction_started,
                    pricing=pricing,
                    finish_reason=extracted.finish_reason,
                    usage_complete=extracted.usage_complete,
                )
            }
        )
        canonical = apply_canonicalization_plan(
            extracted.packet,
            plan_canonicalization(extracted.packet),
        )
        selected_ids = set(plan.selected_chunk_ids)
        canonical = PaperStudyPacketV2.model_validate(
            canonical.model_dump(mode="python"),
            context={
                PROVENANCE_SOURCE_TEXT_CONTEXT_KEY: {
                    chunk.chunk_id: chunk.text
                    for chunk in artifact.chunks
                    if chunk.chunk_id in selected_ids
                }
            },
        )
        rule_report = evaluate_packet_quality(canonical)
        judge_started = time.perf_counter()
        judged = evaluate_semantic_extraction_quality(
            canonical,
            tuple(artifact.chunks),
            provider,
            deterministic_rule_score=rule_report.score,
            max_tokens=min(max_tokens, 4_000),
        )
        record = record.model_copy(
            update={
                "quality_judge": stage_metrics(
                    model=provider.model,
                    attempts=judged.attempts,
                    usage=judged.usage,
                    latency_seconds=time.perf_counter() - judge_started,
                    pricing=pricing,
                    finish_reason=judged.finish_reason,
                    usage_complete=judged.usage_complete,
                )
            }
        )
        if judged.assessment is None:
            raise ValueError(judged.error_message or "semantic quality judge failed")
        assessment = judged.assessment
        record = record.model_copy(
            update={
                "quality_score": assessment.f1,
                "precision": assessment.precision,
                "recall": assessment.recall,
                "deterministic_rule_score": assessment.deterministic_rule_score,
                "incorrect_item_count": assessment.incorrect_item_count,
                "missed_core_item_count": assessment.missed_core_item_count,
            }
        )
        canonical.quality_assessment = assessment
        canonical.quality_score = assessment.f1
        if assessment.f1 < minimum_quality_score:
            raise ValueError(
                f"semantic F1 {assessment.f1:.4f} is below {minimum_quality_score:.4f}"
            )
        path = _write_packet(canonical, output_folder / f"{entry.paper_id}.json")
        record = record.model_copy(
            update={"status": "succeeded", "output_file": str(path)}
        )
    except Exception as exc:
        record = record.model_copy(
            update={
                "status": "failed",
                "error_type": type(exc).__name__,
                "error_message": str(exc) or repr(exc),
            }
        )
    return finalize_record(record)


def extract_one_paper(
    entry: PaperIndexEntry,
    provider: JsonCompletionProvider,
    *,
    output_folder: str | Path,
    max_chunks: int = 4,
    max_tokens: int = 16_000,
    validation_retries: int = 1,
    minimum_quality_score: float = 0.6,
) -> Path:
    """Convert one prepared source artifact to exactly one final JSON file."""

    if not _SAFE_PAPER_ID_RE.fullmatch(entry.paper_id) or entry.paper_id in {".", ".."}:
        raise ValueError(f"unsafe paper_id: {entry.paper_id!r}")
    artifact = load_chunk_artifact(entry.source_path)
    if artifact.paper_id != entry.paper_id:
        raise ValueError("chunk artifact paper_id does not match its input entry")
    plan = build_extraction_plan(
        artifact,
        source_chunk_artifact=entry.source_path,
        max_chunks=max_chunks,
    )
    extracted = extract_paper_study(
        artifact,
        plan,
        provider,
        max_tokens=max_tokens,
        validation_retries=validation_retries,
    )
    canonical = apply_canonicalization_plan(
        extracted.packet,
        plan_canonicalization(extracted.packet),
    )
    selected_ids = set(plan.selected_chunk_ids)
    canonical = PaperStudyPacketV2.model_validate(
        canonical.model_dump(mode="python"),
        context={
            PROVENANCE_SOURCE_TEXT_CONTEXT_KEY: {
                chunk.chunk_id: chunk.text
                for chunk in artifact.chunks
                if chunk.chunk_id in selected_ids
            }
        },
    )
    rule_report = evaluate_packet_quality(canonical)
    # Recall is evaluated against the complete paper, not merely the chunks that
    # produced the extraction. Otherwise a narrow extraction scope could earn a
    # misleadingly perfect score by hiding omitted sections from the judge.
    quality_source_chunks = tuple(artifact.chunks)
    judged = evaluate_semantic_extraction_quality(
        canonical,
        quality_source_chunks,
        provider,
        deterministic_rule_score=rule_report.score,
        max_tokens=min(max_tokens, 4_000),
    )
    if judged.assessment is None:
        raise ValueError(judged.error_message or "semantic quality judge failed")
    assessment = judged.assessment
    canonical.quality_assessment = assessment
    canonical.quality_score = assessment.f1
    if assessment.f1 < minimum_quality_score:
        raise ValueError(
            f"semantic F1 {assessment.f1:.4f} is below {minimum_quality_score:.4f}"
        )
    return _write_packet(canonical, Path(output_folder) / f"{entry.paper_id}.json")


def _prepare_empty_output_folder(root: Path) -> None:
    if root.exists() and any(root.iterdir()):
        raise ValueError(f"output folder must be empty: {root}")
    root.mkdir(parents=True, exist_ok=True)


def _write_packet(packet: PaperStudyPacketV2, target: Path) -> Path:
    # Admission/reconciliation and canonical merge audits belong to the old
    # corpus workflow. The 2.2 public artifact is only the independent paper.
    payload = packet.model_dump(
        mode="json",
        exclude={"status", "requires_reconciliation", "merge_decisions"},
    )
    temporary = target.with_name(f".{target.name}.tmp")
    temporary.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)
    return target.resolve()
