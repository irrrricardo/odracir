"""Composable end-to-end paper-study pipeline used by the CLI.

All scientific processing remains under :mod:`odracir.paper_study`; the CLI is
only responsible for argument parsing and provider construction.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal

from pydantic import Field

from odracir.paper_study.canonicalization import (
    apply_canonicalization_plan,
    plan_canonicalization,
)
from odracir.paper_study.extraction import (
    JsonCompletionProvider,
    PaperExtractionResult,
    extract_paper_study,
    write_extraction_report,
)
from odracir.paper_study.models import (
    PROVENANCE_SOURCE_TEXT_CONTEXT_KEY,
    PacketStatus,
    PaperStudyPacketV2,
    StrictModel,
)
from odracir.paper_study.planning import (
    build_extraction_plan,
    load_chunk_artifact,
    write_extraction_plan,
)
from odracir.paper_study.quality import evaluate_packet_quality
from odracir.paper_study.scheduler import (
    GlobalContext,
    PaperIndexEntry,
    SchedulerRunResult,
    load_paper_index,
)


_SAFE_PAPER_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class QualityGateError(ValueError):
    """Raised after artifacts are written when a packet misses the quality floor."""


class PaperStudyPipelineConfig(StrictModel):
    """Validated settings for one corpus pipeline invocation."""

    output_root: str = Field(min_length=1)
    max_chunks: int = Field(default=4, ge=1)
    max_tokens: int = Field(default=16_000, ge=1)
    validation_retries: int = Field(default=1, ge=0)
    minimum_quality_score: float = Field(default=0.6, ge=0.0, le=1.0)


class PaperArtifactRecord(StrictModel):
    """Successful per-paper artifacts and QualityGate decision."""

    paper_id: str = Field(min_length=1)
    quality_score: float = Field(ge=0.0, le=1.0)
    quality_passed: bool
    packet_status: PacketStatus = "accepted"
    requires_reconciliation: bool = False
    admitted_provisionally: bool = False
    warning_codes: tuple[str, ...] = Field(default_factory=tuple)
    artifact_paths: dict[str, str] = Field(default_factory=dict)


class PipelineFailureRecord(StrictModel):
    """Artifacts completed before a failed per-paper stage."""

    paper_id: str = Field(min_length=1)
    failed_stage: str = Field(min_length=1)
    artifact_paths: dict[str, str] = Field(default_factory=dict)


class PipelinePaperOutcome(StrictModel):
    """Compact corpus-level audit without duplicating the full packet."""

    paper_id: str = Field(min_length=1)
    source_path: str = Field(min_length=1)
    batch_number: int = Field(ge=1)
    position_in_batch: int = Field(ge=1)
    status: Literal["succeeded", "failed"]
    input_context_digest: str = Field(min_length=1)
    quality_score: float | None = Field(default=None, ge=0.0, le=1.0)
    quality_passed: bool | None = None
    packet_status: PacketStatus | None = None
    requires_reconciliation: bool | None = None
    admitted_provisionally: bool = False
    warning_codes: tuple[str, ...] = Field(default_factory=tuple)
    artifact_paths: dict[str, str] = Field(default_factory=dict)
    failed_stage: str | None = None
    error_type: str | None = None
    error_message: str | None = None


class PipelineBatchSummary(StrictModel):
    """Context transition and counts for one completed batch."""

    batch_number: int = Field(ge=1)
    input_context_digest: str = Field(min_length=1)
    output_context_digest: str = Field(min_length=1)
    input_context: GlobalContext
    output_context: GlobalContext
    succeeded: int = Field(ge=0)
    failed: int = Field(ge=0)
    extracted_finding_count: int = Field(ge=0)


class PipelineRunManifest(StrictModel):
    """Stable, strongly typed audit manifest for a corpus run."""

    schema_version: Literal["1.0"] = "1.0"
    paper_folder: str = Field(min_length=1)
    output_root: str = Field(min_length=1)
    ordered_paper_ids: tuple[str, ...]
    undated_paper_ids: tuple[str, ...]
    batches: tuple[PipelineBatchSummary, ...]
    papers: tuple[PipelinePaperOutcome, ...]
    final_context: GlobalContext
    succeeded: int = Field(ge=0)
    failed: int = Field(ge=0)
    corpus_manifest_path: str | None = None
    strategic_batch_plan_path: str | None = None
    assembly_manifest_path: str | None = None
    global_state_ledger_path: str | None = None
    delivery_paths: dict[str, str] = Field(default_factory=dict)


class PaperStudyPipeline:
    """Callable per-paper processor suitable for the deterministic scheduler."""

    def __init__(
        self,
        provider: JsonCompletionProvider,
        config: PaperStudyPipelineConfig,
    ) -> None:
        self.provider = provider
        self.config = config
        self.output_root = Path(config.output_root).expanduser().resolve()
        self.records: dict[str, PaperArtifactRecord] = {}
        self.failure_records: dict[str, PipelineFailureRecord] = {}
        self._partial_paths: dict[str, dict[str, str]] = {}
        self._current_stage: dict[str, str] = {}

    def __call__(
        self,
        entry: PaperIndexEntry,
        global_context: GlobalContext,
    ) -> PaperStudyPacketV2:
        """Run Planning -> Extraction -> Canonicalization -> QualityGate."""

        _validate_safe_paper_id(entry.paper_id)
        self.records.pop(entry.paper_id, None)
        self.failure_records.pop(entry.paper_id, None)
        self._partial_paths[entry.paper_id] = {}
        self._current_stage[entry.paper_id] = "input_validation"
        try:
            return self._process(entry, global_context)
        except Exception as exc:
            paper_output = self.output_root / entry.paper_id
            attempt_path = _write_json(
                {
                    "error_message": str(exc) or repr(exc),
                    "error_type": type(exc).__name__,
                    "failed_stage": self._current_stage.get(
                        entry.paper_id, "paper_pipeline"
                    ),
                    "paper_id": entry.paper_id,
                    "status": "failed",
                },
                paper_output / "pipeline_attempt.json",
            )
            paths = dict(self._partial_paths.get(entry.paper_id, {}))
            paths["pipeline_attempt"] = str(attempt_path)
            self.failure_records[entry.paper_id] = PipelineFailureRecord(
                paper_id=entry.paper_id,
                failed_stage=self._current_stage.get(
                    entry.paper_id, "paper_pipeline"
                ),
                artifact_paths=paths,
            )
            raise

    def _process(
        self,
        entry: PaperIndexEntry,
        global_context: GlobalContext,
    ) -> PaperStudyPacketV2:
        """Execute stages while recording the last attempted stage."""

        _validate_safe_paper_id(entry.paper_id)
        self._current_stage[entry.paper_id] = "load_chunk_artifact"
        artifact = load_chunk_artifact(entry.source_path)
        if artifact.paper_id != entry.paper_id:
            raise ValueError(
                "Chunk artifact paper_id does not match scheduler entry: "
                f"{artifact.paper_id!r} != {entry.paper_id!r}"
            )

        paper_output = self.output_root / entry.paper_id
        paper_output.mkdir(parents=True, exist_ok=True)
        self._current_stage[entry.paper_id] = "planning"
        extraction_plan = build_extraction_plan(
            artifact,
            source_chunk_artifact=entry.source_path,
            max_chunks=self.config.max_chunks,
        )
        planning_path = write_extraction_plan(
            extraction_plan,
            paper_output / "planning.json",
        )
        self._partial_paths[entry.paper_id]["planning"] = str(planning_path)

        context_payload = global_context.prompt_projection()
        self._current_stage[entry.paper_id] = "extraction"
        extraction_result = extract_paper_study(
            artifact,
            extraction_plan,
            self.provider,
            global_context=context_payload,
            max_tokens=self.config.max_tokens,
            validation_retries=self.config.validation_retries,
        )
        extraction_result.packet.metadata.update(
            {
                "input_global_context_digest": global_context.digest(),
                "input_global_context_through_batch": str(global_context.through_batch),
            }
        )

        self._current_stage[entry.paper_id] = "canonicalization_plan"
        canonicalization_plan = plan_canonicalization(extraction_result.packet)
        canonical_plan_path = _write_json(
            canonicalization_plan.model_dump(mode="json"),
            paper_output / "canonicalization_plan.json",
        )
        self._partial_paths[entry.paper_id]["canonicalization_plan"] = str(
            canonical_plan_path
        )
        self._current_stage[entry.paper_id] = "canonicalization_apply"
        canonical_packet = apply_canonicalization_plan(
            extraction_result.packet,
            canonicalization_plan,
        )
        selected_chunk_ids = set(extraction_plan.selected_chunk_ids)
        canonical_packet = PaperStudyPacketV2.model_validate(
            canonical_packet.model_dump(mode="python"),
            context={
                PROVENANCE_SOURCE_TEXT_CONTEXT_KEY: {
                    chunk.chunk_id: chunk.text
                    for chunk in artifact.chunks
                    if chunk.chunk_id in selected_chunk_ids
                }
            },
        )
        self._current_stage[entry.paper_id] = "quality_evaluation"
        quality_report = evaluate_packet_quality(canonical_packet)
        canonical_packet.quality_score = quality_report.score

        self._current_stage[entry.paper_id] = "write_packet"
        packet_path = _write_json(
            canonical_packet.model_dump(mode="json"),
            paper_output / "PaperStudyCard.json",
        )
        self._partial_paths[entry.paper_id]["packet"] = str(packet_path)
        packet_v2_path = _write_json(
            canonical_packet.model_dump(mode="json"),
            paper_output / "PaperStudyPacketV2.json",
        )
        self._partial_paths[entry.paper_id]["packet_v2"] = str(packet_v2_path)
        self._current_stage[entry.paper_id] = "write_quality_report"
        quality_path = _write_json(
            quality_report.model_dump(mode="json"),
            paper_output / "quality_report.json",
        )
        self._partial_paths[entry.paper_id]["quality_report"] = str(quality_path)
        canonical_extraction_result = PaperExtractionResult.model_validate(
            {
                **extraction_result.model_dump(mode="python"),
                "packet": canonical_packet.model_dump(mode="python"),
            }
        )
        self._current_stage[entry.paper_id] = "write_extraction_report"
        extraction_report_path = write_extraction_report(
            canonical_extraction_result,
            paper_output / "extraction_report.json",
        )
        self._partial_paths[entry.paper_id]["extraction_report"] = str(
            extraction_report_path
        )
        paths = {
            "canonicalization_plan": str(canonical_plan_path),
            "extraction_report": str(extraction_report_path),
            "packet": str(packet_path),
            "packet_v2": str(packet_v2_path),
            "planning": str(planning_path),
            "quality_report": str(quality_path),
        }
        self.records[entry.paper_id] = PaperArtifactRecord(
            paper_id=entry.paper_id,
            quality_score=quality_report.score,
            quality_passed=(
                quality_report.score >= self.config.minimum_quality_score
            ),
            packet_status=canonical_packet.status,
            requires_reconciliation=canonical_packet.requires_reconciliation,
            admitted_provisionally=(
                canonical_packet.status == "provisional"
                and _has_complete_core_evidence_chain(canonical_packet)
            ),
            warning_codes=tuple(
                sorted(
                    {
                        *(warning.code for warning in quality_report.warnings),
                        *(warning.code for warning in canonical_packet.validation_warnings),
                    }
                )
            ),
            artifact_paths=paths,
        )
        self._current_stage[entry.paper_id] = "quality_gate"
        if (
            canonical_packet.status == "provisional"
            and not self.records[entry.paper_id].admitted_provisionally
        ):
            raise QualityGateError(
                "A provisional packet requires at least one complete "
                "Claim-to-Result evidence chain"
            )
        if (
            quality_report.score < self.config.minimum_quality_score
            and not self.records[entry.paper_id].admitted_provisionally
        ):
            raise QualityGateError(
                f"Packet quality score {quality_report.score:.4f} is below the "
                f"configured minimum {self.config.minimum_quality_score:.4f}"
            )
        self._current_stage[entry.paper_id] = "complete"
        return canonical_packet


def discover_paper_entries(
    paper_folder: str | Path,
    *,
    index_path: str | Path | None = None,
) -> list[PaperIndexEntry]:
    """Load the legacy index when present, otherwise discover chunk artifacts."""

    folder = Path(paper_folder).expanduser().resolve()
    if not folder.is_dir():
        raise ValueError(f"paper_folder is not a directory: {folder}")

    selected_index: Path | None
    if index_path is None:
        conventional = folder / "odracir_index.json"
        selected_index = conventional if conventional.is_file() else None
    else:
        candidate = Path(index_path).expanduser()
        selected_index = candidate if candidate.is_absolute() else folder / candidate
        selected_index = selected_index.resolve()
        if not selected_index.is_file():
            raise ValueError(f"paper index does not exist: {selected_index}")
    if selected_index is not None:
        entries = load_paper_index(selected_index, paper_folder=folder)
        if not entries:
            raise ValueError(f"Paper index contains no entries: {selected_index}")
        return entries

    if folder.name == "chunks":
        candidates = sorted(folder.glob("*.json"))
    elif (folder / ".odracir" / "chunks").is_dir():
        candidates = sorted((folder / ".odracir" / "chunks").glob("*.json"))
    else:
        candidates = sorted(folder.glob("**/.odracir/chunks/*.json"))
    if not candidates:
        raise ValueError(
            "No odracir_index.json or .odracir/chunks/*.json artifacts were found; "
            "the v2 pipeline cannot process bare PDFs."
        )

    entries = [
        PaperIndexEntry(
            paper_id=load_chunk_artifact(path).paper_id,
            source_path=str(path.resolve()),
            metadata={"discovery": "chunk_glob"},
        )
        for path in candidates
    ]
    paper_ids = [entry.paper_id for entry in entries]
    duplicates = sorted({paper_id for paper_id in paper_ids if paper_ids.count(paper_id) > 1})
    if duplicates:
        raise ValueError(f"Discovered duplicate paper IDs: {duplicates}")
    return sorted(entries, key=lambda entry: (entry.paper_id.casefold(), entry.source_path))


def build_run_manifest(
    *,
    paper_folder: str | Path,
    pipeline: PaperStudyPipeline,
    scheduler_result: SchedulerRunResult,
) -> PipelineRunManifest:
    """Project scheduler and pipeline audit data into a compact run manifest."""

    outcomes: list[PipelinePaperOutcome] = []
    batch_summaries: list[PipelineBatchSummary] = []
    for batch in scheduler_result.batches:
        succeeded = sum(paper.status == "succeeded" for paper in batch.papers)
        failed = len(batch.papers) - succeeded
        batch_summaries.append(
            PipelineBatchSummary(
                batch_number=batch.batch_number,
                input_context_digest=batch.input_context.digest(),
                output_context_digest=batch.output_context.digest(),
                input_context=batch.input_context,
                output_context=batch.output_context,
                succeeded=succeeded,
                failed=failed,
                extracted_finding_count=batch.extracted_finding_count,
            )
        )
        for paper in batch.papers:
            record = pipeline.records.get(paper.paper_id)
            failure_record = pipeline.failure_records.get(paper.paper_id)
            outcomes.append(
                PipelinePaperOutcome(
                    paper_id=paper.paper_id,
                    source_path=paper.source_path,
                    batch_number=paper.batch_number,
                    position_in_batch=paper.position_in_batch,
                    status=paper.status,
                    input_context_digest=paper.input_context_digest,
                    quality_score=None if record is None else record.quality_score,
                    quality_passed=None if record is None else record.quality_passed,
                    packet_status=(
                        None if record is None else record.packet_status
                    ),
                    requires_reconciliation=(
                        None if record is None else record.requires_reconciliation
                    ),
                    admitted_provisionally=(
                        False if record is None else record.admitted_provisionally
                    ),
                    warning_codes=() if record is None else record.warning_codes,
                    artifact_paths={
                        **(
                            {}
                            if failure_record is None
                            else failure_record.artifact_paths
                        ),
                        **({} if record is None else record.artifact_paths),
                    },
                    failed_stage=(
                        None
                        if failure_record is None
                        else failure_record.failed_stage
                    ),
                    error_type=paper.error_type,
                    error_message=paper.error_message,
                )
            )
    succeeded = sum(outcome.status == "succeeded" for outcome in outcomes)
    return PipelineRunManifest(
        paper_folder=str(Path(paper_folder).expanduser().resolve()),
        output_root=str(pipeline.output_root),
        ordered_paper_ids=tuple(
            entry.paper_id for entry in scheduler_result.ordered_entries
        ),
        undated_paper_ids=tuple(
            entry.paper_id
            for entry in scheduler_result.ordered_entries
            if entry.published_at is None
        ),
        batches=tuple(batch_summaries),
        papers=tuple(outcomes),
        final_context=scheduler_result.final_context,
        succeeded=succeeded,
        failed=len(outcomes) - succeeded,
    )


def write_run_manifest(
    manifest: PipelineRunManifest,
    path: str | Path,
) -> Path:
    """Persist a corpus-level scheduler and artifact audit."""

    return _write_json(manifest.model_dump(mode="json"), path)


def _validate_safe_paper_id(paper_id: str) -> None:
    if not _SAFE_PAPER_ID_RE.fullmatch(paper_id) or paper_id in {".", ".."}:
        raise ValueError(
            "paper_id must contain only letters, digits, '.', '_', or '-' and "
            "must not contain path traversal"
        )


def _has_complete_core_evidence_chain(packet: PaperStudyPacketV2) -> bool:
    """Return whether a provisional packet retains a usable Claim→Result chain."""

    result_ids = {
        result.result_id
        for question in packet.research_questions
        for unit in question.study_units
        for result in unit.results
    }
    claims = [
        claim
        for question in packet.research_questions
        for unit in question.study_units
        for claim in unit.claims
    ]
    linked_claims = [claim for claim in claims if claim.inference_basis_ids]
    return bool(result_ids and linked_claims) and all(
        set(claim.inference_basis_ids).issubset(result_ids)
        for claim in linked_claims
    )


def _write_json(payload: object, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
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
    return target
