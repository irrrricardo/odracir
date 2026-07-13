"""Deterministic batch scheduling and cross-paper context propagation.

The scheduler deliberately knows nothing about model providers or network calls.  A
caller supplies a :class:`PaperStudyProcessor`, which makes the orchestration easy
to exercise with local fixtures and lets the CLI compose planning, extraction,
canonicalization, and quality evaluation without coupling those stages here.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import Field, field_validator, model_validator

from odracir.paper_study.models import ClaimPolarity, PaperStudyPacketV2, StrictModel
from odracir.paper_study.recon import CorpusManifest, PaperProfile, profile_distance


_YEAR_RE = re.compile(r"^\d{4}$")
_YEAR_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")
_INDEX_COLLECTION_KEYS = ("papers", "items")
_PATH_KEYS = (
    "source_path",
    "chunk_path",
    "chunk_artifact",
    "artifact_path",
    "path",
    "file",
)
_DATE_KEYS = ("published_at", "publication_date", "published", "date", "year")
_ID_KEYS = ("paper_id", "id")


class PaperIndexEntry(StrictModel):
    """Normalized scheduler input independent of the source index vocabulary."""

    paper_id: str = Field(min_length=1)
    source_path: str = Field(min_length=1)
    published_at: datetime | None = None
    metadata: dict[str, str] = Field(default_factory=dict)

    @field_validator("published_at")
    @classmethod
    def normalize_timezone(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class ContextFinding(StrictModel):
    """Compact, traceable claim passed as prior knowledge to later batches."""

    paper_id: str = Field(min_length=1)
    claim_id: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    polarity: ClaimPolarity
    inference_basis_ids: tuple[str, ...] = Field(default_factory=tuple)
    source_chunk_ids: tuple[str, ...] = Field(min_length=1)


class GlobalContext(StrictModel):
    """Bounded cross-batch memory suitable for direct prompt injection."""

    schema_version: Literal["1.0"] = "1.0"
    through_batch: int = Field(default=0, ge=0)
    findings: tuple[ContextFinding, ...] = Field(default_factory=tuple)
    dropped_finding_count: int = Field(default=0, ge=0)

    def render_for_prompt(self) -> str:
        """Render a stable, concise prior-context block for an extraction prompt."""

        if not self.findings:
            return "No findings from earlier batches are available."
        lines = [
            "Prior findings from papers processed in earlier batches; treat them as "
            "context, not as evidence for the current paper:"
        ]
        for finding in self.findings:
            basis = ", ".join(finding.inference_basis_ids) or "no linked result"
            lines.append(
                f"- [{finding.paper_id}/{finding.claim_id}; {finding.polarity}; "
                f"basis: {basis}] {finding.statement}"
            )
        if self.dropped_finding_count:
            lines.append(
                f"- [context audit] {self.dropped_finding_count} older findings were "
                "removed by the configured context bound."
            )
        return "\n".join(lines)

    def digest(self) -> str:
        """Return a deterministic identifier for audit and cache correlation."""

        payload = self.model_dump_json(exclude_none=False)
        return f"sha256:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"

    def prompt_projection(self) -> dict[str, Any]:
        """Return the exact prior-context object embedded in the model request."""

        payload = self.model_dump(mode="json")
        payload["rendered_summary"] = self.render_for_prompt()
        return payload

    def prompt_projection_digest(self) -> str:
        """Digest the canonical bytes of the actual prompt context projection."""

        encoded = json.dumps(
            self.prompt_projection(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


class PaperStudyProcessor(Protocol):
    """Injectable implementation of the per-paper pipeline."""

    def __call__(
        self,
        entry: PaperIndexEntry,
        global_context: GlobalContext,
    ) -> PaperStudyPacketV2:
        """Process one index entry using context from completed prior batches."""


StrategicAssignmentRole = Literal[
    "seed_medoid",
    "skeleton_neighbor",
    "conflict_interleave",
]


class BatchAssignment(StrictModel):
    """One paper's deterministic position and role in a strategic batch plan."""

    paper_id: str = Field(min_length=1)
    batch_number: int = Field(ge=1)
    position_in_batch: int = Field(ge=1)
    role: StrategicAssignmentRole
    anchor_paper_id: str = Field(min_length=1)
    skeleton_similarity_ppm: int = Field(ge=0, le=1_000_000)
    conflict_signal_overlap: int = Field(default=0, ge=0)


class StrategicBatchPlan(StrictModel):
    """Strongly typed, replayable paper-to-batch assignment plan."""

    schema_version: Literal["1.0"] = "1.0"
    policy_name: str = Field(min_length=1)
    manifest_digest: str = Field(min_length=1)
    batch_size: int = Field(ge=1)
    seed_paper_ids: tuple[str, ...] = Field(default_factory=tuple)
    assignments: tuple[BatchAssignment, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def validate_assignments(self) -> StrategicBatchPlan:
        paper_ids = [assignment.paper_id for assignment in self.assignments]
        if len(paper_ids) != len(set(paper_ids)):
            raise ValueError("strategic batch plan assigns a paper more than once")
        if len(self.seed_paper_ids) != len(set(self.seed_paper_ids)):
            raise ValueError("seed_paper_ids must be unique")

        seed_assignments = tuple(
            assignment.paper_id
            for assignment in self.assignments
            if assignment.role == "seed_medoid"
        )
        if seed_assignments != self.seed_paper_ids:
            raise ValueError(
                "seed_paper_ids must exactly match seed_medoid assignments in order"
            )
        if self.assignments and not self.seed_paper_ids:
            raise ValueError("a non-empty strategic plan must include a seed medoid")
        first_non_seed = next(
            (
                index
                for index, assignment in enumerate(self.assignments)
                if assignment.role != "seed_medoid"
            ),
            len(self.assignments),
        )
        if any(
            assignment.role == "seed_medoid"
            for assignment in self.assignments[first_non_seed:]
        ):
            raise ValueError(
                "seed_medoid assignments must form a contiguous prefix of the plan"
            )
        if first_non_seed < len(self.assignments):
            last_seed_batch = self.assignments[first_non_seed - 1].batch_number
            first_routed_batch = self.assignments[first_non_seed].batch_number
            if first_routed_batch != last_seed_batch + 1:
                raise ValueError(
                    "skeleton/conflict routing must begin after the seed-only batches"
                )

        expected_batch = 1
        expected_position = 1
        previous_batch = 0
        for assignment in self.assignments:
            if assignment.batch_number != previous_batch:
                if assignment.batch_number != expected_batch:
                    raise ValueError("strategic batch numbers must be contiguous from one")
                previous_batch = assignment.batch_number
                expected_batch += 1
                expected_position = 1
            if assignment.position_in_batch != expected_position:
                raise ValueError(
                    "positions within each strategic batch must be contiguous from one"
                )
            if assignment.position_in_batch > self.batch_size:
                raise ValueError("strategic batch exceeds its declared batch_size")
            expected_position += 1
        return self

    @property
    def ordered_paper_ids(self) -> tuple[str, ...]:
        """Paper IDs in the exact order processors must observe."""

        return tuple(assignment.paper_id for assignment in self.assignments)

    @property
    def batches(self) -> tuple[tuple[str, ...], ...]:
        """Paper IDs grouped by their committed context boundary."""

        grouped: list[list[str]] = []
        for assignment in self.assignments:
            while len(grouped) < assignment.batch_number:
                grouped.append([])
            grouped[-1].append(assignment.paper_id)
        return tuple(tuple(batch) for batch in grouped)


class GroupingPolicy(Protocol):
    """Strategy that converts a reconstruction manifest into batch assignments."""

    policy_name: str

    def plan(
        self,
        manifest: CorpusManifest,
        *,
        batch_size: int,
    ) -> StrategicBatchPlan:
        """Return a complete, deterministic assignment for every manifest profile."""


class MedoidBatcher:
    """Seed with diverse medoids, then interleave skeleton and conflict routing.

    ``conflict_signals`` are treated only as routing cues supplied by reconstruction;
    they are never interpreted here as proof that two papers scientifically conflict.
    """

    policy_name = "medoid_skeleton_conflict_interleave_v1"

    def plan(
        self,
        manifest: CorpusManifest,
        *,
        batch_size: int,
    ) -> StrategicBatchPlan:
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        profiles = tuple(
            sorted(
                manifest.profiles,
                key=lambda profile: (
                    profile.paper_id.casefold(),
                    profile.paper_id,
                    profile.source_path,
                ),
            )
        )
        paper_ids = [profile.paper_id for profile in profiles]
        if len(paper_ids) != len(set(paper_ids)):
            raise ValueError("corpus manifest contains duplicate paper_id values")
        if not profiles:
            return StrategicBatchPlan(
                policy_name=self.policy_name,
                manifest_digest=manifest.digest(),
                batch_size=batch_size,
            )

        profile_by_id = {profile.paper_id: profile for profile in profiles}
        seeds = _select_cluster_medoids(manifest, profile_by_id=profile_by_id)
        assignments = [
            BatchAssignment(
                paper_id=profile.paper_id,
                batch_number=(index // batch_size) + 1,
                position_in_batch=(index % batch_size) + 1,
                role="seed_medoid",
                anchor_paper_id=profile.paper_id,
                skeleton_similarity_ppm=1_000_000,
            )
            for index, profile in enumerate(seeds)
        ]

        assigned_ids = {profile.paper_id for profile in seeds}
        remaining = [
            profile for profile in profiles if profile.paper_id not in assigned_ids
        ]
        seed_batch_count = (len(seeds) + batch_size - 1) // batch_size
        batch_number = seed_batch_count + 1
        selection_number = 0
        while remaining:
            anchor = seeds[(batch_number - seed_batch_count - 1) % len(seeds)]
            selected_in_batch: list[PaperProfile] = []
            for position in range(1, batch_size + 1):
                if not remaining:
                    break
                use_conflict_routing = selection_number % 2 == 1
                if use_conflict_routing:
                    chosen = _choose_conflict_interleave(
                        remaining,
                        anchor=anchor,
                        selected_in_batch=selected_in_batch,
                    )
                    role: StrategicAssignmentRole = "conflict_interleave"
                else:
                    chosen = _choose_skeleton_neighbor(
                        remaining,
                        anchor=anchor,
                        selected_in_batch=selected_in_batch,
                    )
                    role = "skeleton_neighbor"
                reference_profiles = (anchor, *selected_in_batch)
                assignments.append(
                    BatchAssignment(
                        paper_id=chosen.paper_id,
                        batch_number=batch_number,
                        position_in_batch=position,
                        role=role,
                        anchor_paper_id=anchor.paper_id,
                        skeleton_similarity_ppm=round(
                            max(
                                _skeleton_similarity(chosen, reference)
                                for reference in reference_profiles
                            )
                            * 1_000_000
                        ),
                        conflict_signal_overlap=max(
                            _conflict_signal_overlap(chosen, reference)
                            for reference in reference_profiles
                        ),
                    )
                )
                selected_in_batch.append(chosen)
                remaining.remove(chosen)
                selection_number += 1
            batch_number += 1

        return StrategicBatchPlan(
            policy_name=self.policy_name,
            manifest_digest=manifest.digest(),
            batch_size=batch_size,
            seed_paper_ids=tuple(profile.paper_id for profile in seeds),
            assignments=tuple(assignments),
        )


class PaperProcessAudit(StrictModel):
    """Success or failure record for exactly one scheduled paper."""

    paper_id: str = Field(min_length=1)
    source_path: str = Field(min_length=1)
    batch_number: int = Field(ge=1)
    position_in_batch: int = Field(ge=1)
    status: Literal["succeeded", "failed"]
    input_context_digest: str = Field(min_length=1)
    packet: PaperStudyPacketV2 | None = None
    error_type: str | None = None
    error_message: str | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> PaperProcessAudit:
        if self.status == "succeeded":
            if self.packet is None:
                raise ValueError("a succeeded paper must include its packet")
            if self.error_type is not None or self.error_message is not None:
                raise ValueError("a succeeded paper must not include error fields")
        else:
            if self.packet is not None:
                raise ValueError("a failed paper must not include a packet")
            if not self.error_type or not self.error_message:
                raise ValueError("a failed paper must include error_type and error_message")
        return self


class BatchAudit(StrictModel):
    """Complete input, outcome, and context-transition audit for one batch."""

    batch_number: int = Field(ge=1)
    input_context: GlobalContext
    papers: tuple[PaperProcessAudit, ...] = Field(min_length=1)
    output_context: GlobalContext
    extracted_finding_count: int = Field(ge=0)


class SchedulerRunResult(StrictModel):
    """Serializable result of a deterministic scheduling run."""

    ordered_entries: tuple[PaperIndexEntry, ...]
    batches: tuple[BatchAudit, ...]
    final_context: GlobalContext
    strategic_plan: StrategicBatchPlan | None = None

    @property
    def packets(self) -> tuple[PaperStudyPacketV2, ...]:
        """Successful packets in deterministic processing order."""

        return tuple(
            audit.packet
            for batch in self.batches
            for audit in batch.papers
            if audit.packet is not None
        )


def load_paper_index(
    index_path: str | Path,
    *,
    paper_folder: str | Path | None = None,
) -> list[PaperIndexEntry]:
    """Load, normalize, resolve paths, and chronologically sort a JSON index.

    Supported roots are a JSON list or an object containing ``papers`` or
    ``items``.  Entries may be path strings or objects using common identifiers,
    path fields, and publication-date fields.
    """

    source = Path(index_path).expanduser().resolve()
    payload = json.loads(source.read_text(encoding="utf-8"))
    raw_items = _index_items(payload)
    base_folder = (
        Path(paper_folder).expanduser().resolve()
        if paper_folder is not None
        else source.parent
    )
    entries = [
        _normalize_index_entry(item, item_number=number, base_folder=base_folder)
        for number, item in enumerate(raw_items, start=1)
    ]
    _validate_unique_entries(entries)
    return sort_paper_index(entries)


def load_paper_folder_index(
    paper_folder: str | Path,
    *,
    index_filename: str = "odracir_index.json",
) -> list[PaperIndexEntry]:
    """Load the conventional index located at the root of a paper folder."""

    folder = Path(paper_folder).expanduser().resolve()
    if not index_filename or Path(index_filename).name != index_filename:
        raise ValueError("index_filename must be a non-empty filename, not a path")
    return load_paper_index(folder / index_filename, paper_folder=folder)


def sort_paper_index(entries: Sequence[PaperIndexEntry]) -> list[PaperIndexEntry]:
    """Sort oldest-first, placing unknown dates last with stable tie-breakers."""

    return sorted(
        entries,
        key=lambda entry: (
            entry.published_at is None,
            entry.published_at or datetime.max.replace(tzinfo=timezone.utc),
            entry.paper_id.casefold(),
            entry.source_path,
        ),
    )


def extract_key_findings(
    packet: PaperStudyPacketV2,
    *,
    max_claims: int = 3,
) -> tuple[ContextFinding, ...]:
    """Select a paper's strongest claims using deterministic evidence signals."""

    if max_claims < 0:
        raise ValueError("max_claims must not be negative")
    if max_claims == 0:
        return ()

    claims = [
        claim
        for question in packet.research_questions
        for unit in question.study_units
        for claim in unit.claims
    ]
    ranked = sorted(
        claims,
        key=lambda claim: (
            -bool(claim.inference_basis_ids),
            -len(set(claim.inference_basis_ids)),
            claim.provenance.paraphrased,
            -len(claim.additional_provenance),
            -len(claim.statement),
            claim.claim_id,
            claim.statement,
        ),
    )

    findings: list[ContextFinding] = []
    seen_statements: set[str] = set()
    for claim in ranked:
        normalized_statement = " ".join(claim.statement.casefold().split())
        if normalized_statement in seen_statements:
            continue
        seen_statements.add(normalized_statement)
        source_chunk_ids = tuple(
            sorted(
                {
                    claim.provenance.chunk_id,
                    *(item.chunk_id for item in claim.additional_provenance),
                }
            )
        )
        findings.append(
            ContextFinding(
                paper_id=packet.paper_id,
                claim_id=claim.claim_id,
                statement=claim.statement,
                polarity=claim.polarity,
                inference_basis_ids=tuple(sorted(set(claim.inference_basis_ids))),
                source_chunk_ids=source_chunk_ids,
            )
        )
        if len(findings) == max_claims:
            break
    return tuple(findings)


def advance_global_context(
    previous: GlobalContext,
    packets: Sequence[PaperStudyPacketV2],
    *,
    completed_batch: int,
    max_claims_per_paper: int = 3,
    max_context_findings: int = 100,
) -> tuple[GlobalContext, int]:
    """Add findings from a completed batch and enforce a deterministic bound."""

    if completed_batch != previous.through_batch + 1:
        raise ValueError("completed_batch must immediately follow previous.through_batch")
    if max_claims_per_paper < 0:
        raise ValueError("max_claims_per_paper must not be negative")
    if max_context_findings < 1:
        raise ValueError("max_context_findings must be positive")

    new_findings = tuple(
        finding
        for packet in packets
        for finding in extract_key_findings(packet, max_claims=max_claims_per_paper)
    )
    combined = (*previous.findings, *new_findings)
    removed_now = max(0, len(combined) - max_context_findings)
    retained = combined[removed_now:]
    return (
        GlobalContext(
            through_batch=completed_batch,
            findings=retained,
            dropped_finding_count=previous.dropped_finding_count + removed_now,
        ),
        len(new_findings),
    )


def run_paper_study_scheduler(
    entries: Sequence[PaperIndexEntry],
    processor: PaperStudyProcessor,
    *,
    batch_size: int = 10,
    max_claims_per_paper: int = 3,
    max_context_findings: int = 100,
    initial_context: GlobalContext | None = None,
    strategic_plan: StrategicBatchPlan | None = None,
    grouping_policy: GroupingPolicy | None = None,
    corpus_manifest: CorpusManifest | None = None,
) -> SchedulerRunResult:
    """Process chronological batches and inject only completed prior context.

    Processor exceptions and invalid/mismatched packets are retained as failed
    audits.  Processing continues, and only successful packets contribute claims
    to the context used by the next batch.
    """

    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    if max_claims_per_paper < 0:
        raise ValueError("max_claims_per_paper must not be negative")
    if max_context_findings < 1:
        raise ValueError("max_context_findings must be positive")

    ordered, entry_batches, resolved_plan = _resolve_scheduler_batches(
        entries,
        batch_size=batch_size,
        strategic_plan=strategic_plan,
        grouping_policy=grouping_policy,
        corpus_manifest=corpus_manifest,
    )
    context = initial_context or GlobalContext()
    batch_audits: list[BatchAudit] = []

    for batch_entries in entry_batches:
        batch_number = context.through_batch + 1
        input_context = context.model_copy(deep=True)
        input_digest = input_context.digest()
        paper_audits: list[PaperProcessAudit] = []
        successful_packets: list[PaperStudyPacketV2] = []

        for position, entry in enumerate(batch_entries, start=1):
            try:
                raw_packet = processor(entry, input_context.model_copy(deep=True))
                packet = PaperStudyPacketV2.model_validate(raw_packet)
                if packet.paper_id != entry.paper_id:
                    raise ValueError(
                        "processor packet paper_id does not match its index entry: "
                        f"{packet.paper_id!r} != {entry.paper_id!r}"
                    )
            except Exception as exc:  # the failure is data in the scheduler audit
                paper_audits.append(
                    PaperProcessAudit(
                        paper_id=entry.paper_id,
                        source_path=entry.source_path,
                        batch_number=batch_number,
                        position_in_batch=position,
                        status="failed",
                        input_context_digest=input_digest,
                        error_type=type(exc).__name__,
                        error_message=str(exc) or repr(exc),
                    )
                )
                continue

            successful_packets.append(packet)
            paper_audits.append(
                PaperProcessAudit(
                    paper_id=entry.paper_id,
                    source_path=entry.source_path,
                    batch_number=batch_number,
                    position_in_batch=position,
                    status="succeeded",
                    input_context_digest=input_digest,
                    packet=packet,
                )
            )

        context, finding_count = advance_global_context(
            input_context,
            successful_packets,
            completed_batch=batch_number,
            max_claims_per_paper=max_claims_per_paper,
            max_context_findings=max_context_findings,
        )
        batch_audits.append(
            BatchAudit(
                batch_number=batch_number,
                input_context=input_context,
                papers=tuple(paper_audits),
                output_context=context,
                extracted_finding_count=finding_count,
            )
        )

    return SchedulerRunResult(
        ordered_entries=tuple(ordered),
        batches=tuple(batch_audits),
        final_context=context,
        strategic_plan=resolved_plan,
    )


def schedule_from_index(
    index_path: str | Path,
    processor: PaperStudyProcessor,
    *,
    paper_folder: str | Path | None = None,
    batch_size: int = 10,
    max_claims_per_paper: int = 3,
    max_context_findings: int = 100,
    initial_context: GlobalContext | None = None,
    strategic_plan: StrategicBatchPlan | None = None,
    grouping_policy: GroupingPolicy | None = None,
    corpus_manifest: CorpusManifest | None = None,
) -> SchedulerRunResult:
    """Convenience facade combining index loading and batch scheduling."""

    entries = load_paper_index(index_path, paper_folder=paper_folder)
    return run_paper_study_scheduler(
        entries,
        processor,
        batch_size=batch_size,
        max_claims_per_paper=max_claims_per_paper,
        max_context_findings=max_context_findings,
        initial_context=initial_context,
        strategic_plan=strategic_plan,
        grouping_policy=grouping_policy,
        corpus_manifest=corpus_manifest,
    )


def schedule_paper_folder(
    paper_folder: str | Path,
    processor: PaperStudyProcessor,
    *,
    index_filename: str = "odracir_index.json",
    batch_size: int = 10,
    max_claims_per_paper: int = 3,
    max_context_findings: int = 100,
    initial_context: GlobalContext | None = None,
    strategic_plan: StrategicBatchPlan | None = None,
    grouping_policy: GroupingPolicy | None = None,
    corpus_manifest: CorpusManifest | None = None,
) -> SchedulerRunResult:
    """Schedule the conventional ``odracir_index.json`` in a paper folder."""

    entries = load_paper_folder_index(paper_folder, index_filename=index_filename)
    return run_paper_study_scheduler(
        entries,
        processor,
        batch_size=batch_size,
        max_claims_per_paper=max_claims_per_paper,
        max_context_findings=max_context_findings,
        initial_context=initial_context,
        strategic_plan=strategic_plan,
        grouping_policy=grouping_policy,
        corpus_manifest=corpus_manifest,
    )


def _resolve_scheduler_batches(
    entries: Sequence[PaperIndexEntry],
    *,
    batch_size: int,
    strategic_plan: StrategicBatchPlan | None,
    grouping_policy: GroupingPolicy | None,
    corpus_manifest: CorpusManifest | None,
) -> tuple[
    list[PaperIndexEntry],
    tuple[tuple[PaperIndexEntry, ...], ...],
    StrategicBatchPlan | None,
]:
    chronological = sort_paper_index(entries)
    _validate_unique_entries(chronological)
    if strategic_plan is not None and grouping_policy is not None:
        raise ValueError("provide strategic_plan or grouping_policy, not both")
    resolved_plan = strategic_plan
    if grouping_policy is not None:
        if corpus_manifest is None:
            raise ValueError("grouping_policy requires corpus_manifest")
        resolved_plan = grouping_policy.plan(corpus_manifest, batch_size=batch_size)
    if resolved_plan is None:
        batches = tuple(
            tuple(chronological[offset : offset + batch_size])
            for offset in range(0, len(chronological), batch_size)
        )
        return chronological, batches, None

    if resolved_plan.batch_size != batch_size:
        raise ValueError(
            "strategic plan batch_size does not match scheduler batch_size: "
            f"{resolved_plan.batch_size} != {batch_size}"
        )
    entry_by_id = {entry.paper_id: entry for entry in chronological}
    planned_ids = resolved_plan.ordered_paper_ids
    if set(planned_ids) != set(entry_by_id) or len(planned_ids) != len(entry_by_id):
        missing = sorted(set(entry_by_id) - set(planned_ids))
        unknown = sorted(set(planned_ids) - set(entry_by_id))
        raise ValueError(
            "strategic plan paper IDs must exactly match scheduler entries; "
            f"missing={missing}, unknown={unknown}"
        )
    if (
        corpus_manifest is not None
        and resolved_plan.manifest_digest != corpus_manifest.digest()
    ):
        raise ValueError("strategic plan manifest_digest does not match corpus_manifest")

    ordered = [entry_by_id[paper_id] for paper_id in planned_ids]
    batches = tuple(
        tuple(entry_by_id[paper_id] for paper_id in batch)
        for batch in resolved_plan.batches
    )
    return ordered, batches, resolved_plan


def _select_cluster_medoids(
    manifest: CorpusManifest,
    *,
    profile_by_id: Mapping[str, PaperProfile],
) -> tuple[PaperProfile, ...]:
    """Choose exactly one minimum-total-distance representative per manifest class."""

    medoids: list[PaperProfile] = []
    for cluster in manifest.clusters:
        members = tuple(profile_by_id[paper_id] for paper_id in cluster.member_paper_ids)
        medoid = min(
            members,
            key=lambda profile: (
                sum(profile_distance(profile, other) for other in members),
                -profile.quality_proxy,
                profile.paper_id.casefold(),
                profile.paper_id,
                profile.source_path,
            ),
        )
        medoids.append(medoid)
    return tuple(medoids)


def _choose_skeleton_neighbor(
    profiles: Sequence[PaperProfile],
    *,
    anchor: PaperProfile,
    selected_in_batch: Sequence[PaperProfile],
) -> PaperProfile:
    references = (anchor, *selected_in_batch)
    return min(
        profiles,
        key=lambda profile: (
            -_skeleton_similarity(profile, anchor),
            -max(_skeleton_similarity(profile, item) for item in references),
            -profile.quality_proxy,
            profile.paper_id.casefold(),
            profile.paper_id,
            profile.source_path,
        ),
    )


def _choose_conflict_interleave(
    profiles: Sequence[PaperProfile],
    *,
    anchor: PaperProfile,
    selected_in_batch: Sequence[PaperProfile],
) -> PaperProfile:
    references = (anchor, *selected_in_batch)
    return min(
        profiles,
        key=lambda profile: (
            -int(bool(profile.conflict_signals)),
            -max(_conflict_signal_overlap(profile, item) for item in references),
            -profile.conflict_score,
            -max(_skeleton_similarity(profile, item) for item in references),
            -profile.quality_proxy,
            profile.paper_id.casefold(),
            profile.paper_id,
            profile.source_path,
        ),
    )


def _skeleton_similarity(left: PaperProfile, right: PaperProfile) -> float:
    return 1.0 - profile_distance(left, right)


def _conflict_signal_overlap(left: PaperProfile, right: PaperProfile) -> int:
    left_signals = _normalized_feature_set(left.conflict_signals)
    right_signals = _normalized_feature_set(right.conflict_signals)
    return len(left_signals & right_signals)


def _normalized_feature_set(values: Sequence[str]) -> frozenset[str]:
    return frozenset(
        normalized
        for value in values
        if (normalized := " ".join(value.casefold().split()))
    )


def _index_items(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        present_keys = [key for key in _INDEX_COLLECTION_KEYS if key in payload]
        if len(present_keys) != 1:
            expected = " or ".join(repr(key) for key in _INDEX_COLLECTION_KEYS)
            raise ValueError(f"index object must contain exactly one of {expected}")
        items = payload[present_keys[0]]
        if not isinstance(items, list):
            raise ValueError(f"index field {present_keys[0]!r} must be a list")
        return items
    raise ValueError("paper index must be a JSON list or an object containing papers/items")


def _normalize_index_entry(
    item: Any,
    *,
    item_number: int,
    base_folder: Path,
) -> PaperIndexEntry:
    if isinstance(item, str):
        raw_path = item
        paper_id: Any = None
        raw_date: Any = None
        metadata: dict[str, str] = {}
    elif isinstance(item, Mapping):
        raw_path = _first_present(item, _PATH_KEYS)
        paper_id = _first_present(item, _ID_KEYS)
        raw_date = _first_nonempty(item, _DATE_KEYS)
        metadata = _normalize_metadata(item.get("metadata"), item_number=item_number)
    else:
        raise ValueError(f"index item {item_number} must be a path string or object")

    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValueError(f"index item {item_number} has no non-empty source path")
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = base_folder / path
    resolved_path = path.resolve()

    if paper_id is None or (isinstance(paper_id, str) and not paper_id.strip()):
        normalized_id = resolved_path.stem
    elif isinstance(paper_id, (str, int)) and not isinstance(paper_id, bool):
        normalized_id = str(paper_id).strip()
    else:
        raise ValueError(f"index item {item_number} has an invalid paper_id")
    if not normalized_id:
        raise ValueError(f"index item {item_number} has an empty paper_id")

    return PaperIndexEntry(
        paper_id=normalized_id,
        source_path=str(resolved_path),
        published_at=_parse_publication_time(raw_date, item_number=item_number),
        metadata=metadata,
    )


def _normalize_metadata(value: Any, *, item_number: int) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f"index item {item_number} metadata must be an object")
    normalized: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise ValueError(f"index item {item_number} metadata keys must be strings")
        if item is None:
            continue
        if not isinstance(item, (str, int, float, bool)):
            raise ValueError(
                f"index item {item_number} metadata value for {key!r} must be scalar"
            )
        normalized[key] = str(item)
    return normalized


def _parse_publication_time(value: Any, *, item_number: int) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError(f"index item {item_number} has an invalid publication date")
    if isinstance(value, int):
        if not 1 <= value <= 9999:
            raise ValueError(f"index item {item_number} has an invalid publication year")
        return datetime(value, 1, 1, tzinfo=timezone.utc)
    if not isinstance(value, str):
        raise ValueError(f"index item {item_number} has an invalid publication date")

    text = value.strip()
    try:
        if _YEAR_RE.fullmatch(text):
            parsed = datetime(int(text), 1, 1)
        elif match := _YEAR_MONTH_RE.fullmatch(text):
            parsed = datetime(int(match.group(1)), int(match.group(2)), 1)
        else:
            iso_text = text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text
            try:
                parsed = datetime.fromisoformat(iso_text)
            except ValueError:
                parsed_date = date.fromisoformat(text)
                parsed = datetime.combine(parsed_date, datetime.min.time())
    except ValueError as exc:
        raise ValueError(
            f"index item {item_number} has an invalid publication date: {value!r}"
        ) from exc

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _first_present(item: Mapping[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        if key in item:
            return item[key]
    return None


def _first_nonempty(item: Mapping[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        if key in item:
            value = item[key]
            if value is not None and value != "":
                return value
    return None


def _validate_unique_entries(entries: Sequence[PaperIndexEntry]) -> None:
    paper_id_counts = Counter(entry.paper_id for entry in entries)
    duplicate_ids = sorted(
        paper_id for paper_id, count in paper_id_counts.items() if count > 1
    )
    if duplicate_ids:
        raise ValueError(f"paper index contains duplicate paper_id values: {duplicate_ids}")
