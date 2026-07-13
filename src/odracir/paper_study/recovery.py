"""Append-only, auditable recovery of failed papers in a Stage 3 run."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import Field

from odracir.paper_study.assembly import (
    extend_corpus_assembly,
    load_corpus_assembly,
    write_corpus_assembly,
)
from odracir.paper_study.extraction import JsonCompletionProvider
from odracir.paper_study.models import StrictModel
from odracir.paper_study.pipeline import (
    PaperStudyPipeline,
    PaperStudyPipelineConfig,
    PipelinePaperOutcome,
    PipelineRunManifest,
    build_run_manifest,
    write_run_manifest,
)
from odracir.paper_study.scheduler import (
    PaperIndexEntry,
    SchedulerRunResult,
    run_paper_study_scheduler,
)


class Stage3RecoveryConfig(StrictModel):
    """Runtime settings absent from the v1 run manifest."""

    max_chunks: int | None = Field(default=None, ge=1)
    max_tokens: int = Field(default=16_000, ge=1)
    validation_retries: int = Field(default=1, ge=0)
    minimum_quality_score: float = Field(default=0.6, ge=0.0, le=1.0)
    max_claims_per_paper: int = Field(default=3, ge=0)
    max_context_findings: int = Field(default=100, ge=1)


class Stage3RecoveryManifest(StrictModel):
    """Standalone audit tying an appended recovery batch to its parent ledger."""

    schema_version: Literal["1.0"] = "1.0"
    status: Literal["completed", "failed"]
    initial_run_manifest_path: str = Field(min_length=1)
    initial_run_manifest_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    preserved_initial_manifest_path: str = Field(min_length=1)
    parent_assembly_manifest_path: str = Field(min_length=1)
    parent_ledger_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    parent_ledger_revision: int = Field(ge=0)
    output_root: str = Field(min_length=1)
    recovery_context_digest: str = Field(min_length=1)
    recovery_batch_number: int = Field(ge=1)
    attempted_paper_ids: tuple[str, ...] = Field(min_length=1)
    succeeded_paper_ids: tuple[str, ...] = Field(default_factory=tuple)
    failed_paper_ids: tuple[str, ...] = Field(default_factory=tuple)
    failure_messages: dict[str, str] = Field(default_factory=dict)
    final_run_manifest_path: str | None = None
    assembly_manifest_path: str | None = None
    global_state_ledger_path: str | None = None
    delivery_paths: dict[str, str] = Field(default_factory=dict)


class Stage3RecoveryResult(StrictModel):
    """Programmatic recovery result; no caller needs to parse console text."""

    recovery_manifest: Stage3RecoveryManifest
    recovery_manifest_path: str = Field(min_length=1)
    final_manifest: PipelineRunManifest | None = None


def recover_stage3_run(
    run_manifest_path: str | Path,
    provider: JsonCompletionProvider,
    *,
    output_root: str | Path,
    config: Stage3RecoveryConfig | None = None,
    corpus_id: str | None = None,
) -> Stage3RecoveryResult:
    """Append one recovery batch without replaying or rewriting prior batches.

    Old snapshots and deliveries are loaded from their assembly manifest and
    cryptographically validated. The failed papers alone are processed against the
    old final context. A successful recovery is reduced from the old final ledger,
    so its first new snapshot has the exact old digest as ``parent_digest``.
    Existing Delivery packet, packet digest, and generation receipt fields remain
    unchanged; only Alignment receipts are regenerated against the new final ledger.
    No Claim-to-Result link is synthesized by this orchestration layer.
    """

    settings = config or Stage3RecoveryConfig()
    source_manifest_path = Path(run_manifest_path).expanduser().resolve()
    source_bytes = source_manifest_path.read_bytes()
    initial = PipelineRunManifest.model_validate_json(source_bytes)
    parent_output_root = Path(initial.output_root).expanduser().resolve()
    target_output_root = Path(output_root).expanduser().resolve()
    _validate_new_output_root(parent_output_root, target_output_root)

    parent_assembly_path = _parent_assembly_path(initial)
    parent_assembly = load_corpus_assembly(parent_assembly_path)
    parent_ledger = parent_assembly.final_ledger
    if corpus_id is not None and parent_assembly.corpus_id != corpus_id:
        raise ValueError("explicit corpus_id does not match the parent assembly")
    if initial.final_context.through_batch != parent_ledger.revision:
        raise ValueError(
            "initial final_context batch does not match parent ledger revision"
        )

    initial_success_ids = {
        outcome.paper_id for outcome in initial.papers if outcome.status == "succeeded"
    }
    parent_delivery_ids = {
        delivery.packet.paper_id for delivery in parent_assembly.deliveries
    }
    if parent_delivery_ids != initial_success_ids:
        raise ValueError(
            "parent assembly deliveries do not match initial successful papers"
        )

    failed_outcomes = tuple(
        outcome for outcome in initial.papers if outcome.status == "failed"
    )
    if not failed_outcomes:
        raise ValueError("run manifest contains no failed papers to recover")
    failed_ids = tuple(outcome.paper_id for outcome in failed_outcomes)
    if len(failed_ids) != len(set(failed_ids)):
        raise ValueError("run manifest contains duplicate failed paper IDs")

    target_output_root.mkdir(parents=True, exist_ok=True)
    initial_digest = _sha256_bytes(source_bytes)
    recovery_root = target_output_root / "recovery"
    preserved_path = recovery_root / (
        "run_manifest.initial-"
        f"{initial_digest.removeprefix('sha256:')[:16]}.json"
    )
    _preserve_exact_bytes(source_bytes, preserved_path)

    recovery_entries = tuple(
        PaperIndexEntry(
            paper_id=outcome.paper_id,
            source_path=outcome.source_path,
            metadata={"stage3_recovery": "true"},
        )
        for outcome in failed_outcomes
    )
    pipeline = PaperStudyPipeline(
        provider,
        PaperStudyPipelineConfig(
            output_root=str(target_output_root),
            max_chunks=(
                settings.max_chunks
                if settings.max_chunks is not None
                else _infer_prior_max_chunks(failed_outcomes)
            ),
            max_tokens=settings.max_tokens,
            validation_retries=settings.validation_retries,
            minimum_quality_score=settings.minimum_quality_score,
        ),
    )
    recovery_scheduler = run_paper_study_scheduler(
        recovery_entries,
        pipeline,
        batch_size=len(recovery_entries),
        max_claims_per_paper=settings.max_claims_per_paper,
        max_context_findings=settings.max_context_findings,
        initial_context=initial.final_context,
    )
    if len(recovery_scheduler.batches) != 1:
        raise RuntimeError("targeted recovery must produce exactly one appended batch")
    _validate_recovery_plans(failed_outcomes, pipeline)
    recovery_batch = recovery_scheduler.batches[0]
    if recovery_batch.batch_number != parent_ledger.revision + 1:
        raise ValueError("recovery batch does not immediately follow parent ledger")

    succeeded_ids = tuple(
        audit.paper_id for audit in recovery_batch.papers if audit.status == "succeeded"
    )
    recovery_failed = tuple(
        audit.paper_id for audit in recovery_batch.papers if audit.status == "failed"
    )
    failure_messages = {
        audit.paper_id: audit.error_message or "unknown recovery failure"
        for audit in recovery_batch.papers
        if audit.status == "failed"
    }
    recovery_manifest_path = recovery_root / "recovery_manifest.json"
    common_audit = {
        "initial_run_manifest_path": str(source_manifest_path),
        "initial_run_manifest_digest": initial_digest,
        "preserved_initial_manifest_path": str(preserved_path.resolve()),
        "parent_assembly_manifest_path": str(parent_assembly_path.resolve()),
        "parent_ledger_digest": parent_ledger.digest(),
        "parent_ledger_revision": parent_ledger.revision,
        "output_root": str(target_output_root),
        "recovery_context_digest": initial.final_context.digest(),
        "recovery_batch_number": recovery_batch.batch_number,
        "attempted_paper_ids": failed_ids,
        "succeeded_paper_ids": succeeded_ids,
    }

    if recovery_failed:
        audit = Stage3RecoveryManifest(
            **common_audit,
            status="failed",
            failed_paper_ids=recovery_failed,
            failure_messages=failure_messages,
        )
        _write_json(audit.model_dump(mode="json"), recovery_manifest_path)
        return Stage3RecoveryResult(
            recovery_manifest=audit,
            recovery_manifest_path=str(recovery_manifest_path.resolve()),
        )

    extended_assembly = extend_corpus_assembly(
        parent_assembly,
        recovery_scheduler,
    )
    if extended_assembly.final_ledger.parent_digest != parent_ledger.digest():
        raise ValueError("extended ledger does not directly reference its parent")
    assembly_paths = write_corpus_assembly(extended_assembly, target_output_root)
    final_manifest = _build_recovered_manifest(
        initial=initial,
        pipeline=pipeline,
        recovery_scheduler=recovery_scheduler,
        target_output_root=target_output_root,
        assembly_paths=assembly_paths,
    )
    final_manifest_path = target_output_root / "run_manifest.json"
    write_run_manifest(final_manifest, final_manifest_path)

    audit = Stage3RecoveryManifest(
        **common_audit,
        status="completed",
        failed_paper_ids=(),
        final_run_manifest_path=str(final_manifest_path.resolve()),
        assembly_manifest_path=assembly_paths["assembly_manifest"],
        global_state_ledger_path=assembly_paths["ledger"],
        delivery_paths={
            key.removeprefix("delivery:"): value
            for key, value in assembly_paths.items()
            if key.startswith("delivery:")
        },
    )
    _write_json(audit.model_dump(mode="json"), recovery_manifest_path)
    return Stage3RecoveryResult(
        recovery_manifest=audit,
        recovery_manifest_path=str(recovery_manifest_path.resolve()),
        final_manifest=final_manifest,
    )


def _build_recovered_manifest(
    *,
    initial: PipelineRunManifest,
    pipeline: PaperStudyPipeline,
    recovery_scheduler: SchedulerRunResult,
    target_output_root: Path,
    assembly_paths: dict[str, str],
) -> PipelineRunManifest:
    recovery_projection = build_run_manifest(
        paper_folder=initial.paper_folder,
        pipeline=pipeline,
        scheduler_result=recovery_scheduler,
    )
    recovered = {outcome.paper_id: outcome for outcome in recovery_projection.papers}
    active_outcomes: list[PipelinePaperOutcome] = []
    for prior in initial.papers:
        replacement = recovered.get(prior.paper_id)
        active_outcomes.append(prior if replacement is None else replacement)
    if {outcome.paper_id for outcome in active_outcomes} != set(
        initial.ordered_paper_ids
    ):
        raise ValueError("recovered active outcomes do not cover the original corpus")
    if any(outcome.status != "succeeded" for outcome in active_outcomes):
        raise ValueError("a final recovery manifest requires every paper to succeed")

    return PipelineRunManifest.model_validate(
        {
            **initial.model_dump(mode="python"),
            "output_root": str(target_output_root),
            # Prior batch summaries are copied without alteration. The appended
            # recovery batch records the new context transition explicitly.
            "batches": (*initial.batches, *recovery_projection.batches),
            "papers": tuple(active_outcomes),
            "final_context": recovery_projection.final_context,
            "succeeded": len(active_outcomes),
            "failed": 0,
            "assembly_manifest_path": assembly_paths["assembly_manifest"],
            "global_state_ledger_path": assembly_paths["ledger"],
            "delivery_paths": {
                key.removeprefix("delivery:"): value
                for key, value in assembly_paths.items()
                if key.startswith("delivery:")
            },
        }
    )


def _parent_assembly_path(manifest: PipelineRunManifest) -> Path:
    candidates = (
        manifest.assembly_manifest_path,
        str(Path(manifest.output_root) / "assembly_manifest.json"),
    )
    for raw_path in candidates:
        if raw_path and Path(raw_path).is_file():
            return Path(raw_path).expanduser().resolve()
    raise ValueError("parent assembly_manifest.json is unavailable")


def _validate_new_output_root(parent: Path, target: Path) -> None:
    if target == parent or target.is_relative_to(parent) or parent.is_relative_to(target):
        raise ValueError("recovery output_root must be a separate new directory")
    if target.exists() and any(target.iterdir()):
        raise ValueError("recovery output_root must not contain existing artifacts")


def _infer_prior_max_chunks(
    failed_outcomes: tuple[PipelinePaperOutcome, ...],
) -> int:
    """Reuse the failed papers' prior selection width when its plans survive."""

    selected_counts: list[int] = []
    for outcome in failed_outcomes:
        raw_path = outcome.artifact_paths.get("planning")
        if not raw_path or not Path(raw_path).is_file():
            continue
        payload = json.loads(Path(raw_path).read_text(encoding="utf-8"))
        selected = payload.get("selected_chunk_ids") if isinstance(payload, dict) else None
        if isinstance(selected, list) and selected:
            selected_counts.append(len(selected))
    return max(selected_counts, default=4)


def _validate_recovery_plans(
    failed_outcomes: tuple[PipelinePaperOutcome, ...],
    pipeline: PaperStudyPipeline,
) -> None:
    """Reject source-selection drift when an earlier planning artifact exists."""

    for outcome in failed_outcomes:
        prior_path = outcome.artifact_paths.get("planning")
        record = pipeline.records.get(outcome.paper_id)
        failure_record = pipeline.failure_records.get(outcome.paper_id)
        new_paths = {
            **({} if failure_record is None else failure_record.artifact_paths),
            **({} if record is None else record.artifact_paths),
        }
        new_path = new_paths.get("planning")
        if not prior_path or not new_path:
            continue
        prior = json.loads(Path(prior_path).read_text(encoding="utf-8"))
        current = json.loads(Path(new_path).read_text(encoding="utf-8"))
        for field in ("selected_chunk_ids", "selected_chunk_ordinals"):
            if prior.get(field) != current.get(field):
                raise ValueError(
                    f"recovery planning drift for {outcome.paper_id}: {field} changed"
                )


def _sha256_bytes(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _preserve_exact_bytes(payload: bytes, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise ValueError(f"preserved initial manifest conflicts with {path}")
        return
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)


def _write_json(payload: object, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
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
    temporary.replace(path)
