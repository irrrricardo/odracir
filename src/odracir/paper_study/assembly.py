"""Deterministic corpus ledger reduction and final delivery reconciliation."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from pydantic import Field

from odracir.paper_study.canonicalization import (
    extract_protected_conditions,
    normalize_scientific_text,
)
from odracir.paper_study.models import (
    AlignmentReceipt,
    AssertionEvidenceRef,
    AssertionRelation,
    GenerationContextReceipt,
    GlobalAssertion,
    GlobalStateLedger,
    LedgerEntityRef,
    LedgerEvent,
    PaperStudyDeliveryV2,
    PaperStudyPacketV2,
    StrictModel,
    packet_content_digest,
)
from odracir.paper_study.scheduler import BatchAudit, SchedulerRunResult


REDUCER_POLICY_VERSION = "corpus-assertion-reducer/v1"
ALIGNMENT_POLICY_VERSION = "deterministic-claim-alignment/v1"
PROJECTION_POLICY_VERSION = "global-context-projection/v1"
_RELATION_THRESHOLD = 0.65


class CorpusAssemblyResult(StrictModel):
    """In-memory result of append-only ledger reduction and reconciliation."""

    corpus_id: str = Field(min_length=1)
    ledger_snapshots: tuple[GlobalStateLedger, ...] = Field(min_length=1)
    deliveries: tuple[PaperStudyDeliveryV2, ...]

    @property
    def final_ledger(self) -> GlobalStateLedger:
        return self.ledger_snapshots[-1]


def _validate_corpus_assembly_result(
    result: CorpusAssemblyResult,
) -> CorpusAssemblyResult:
    """Validate a complete persisted/in-memory assembly and all receipt bindings."""

    snapshots = result.ledger_snapshots
    revisions = tuple(snapshot.revision for snapshot in snapshots)
    if revisions != tuple(range(len(snapshots))):
        raise ValueError(
            "assembly ledger snapshots must form a complete revision chain from zero"
        )
    if any(snapshot.corpus_id != result.corpus_id for snapshot in snapshots):
        raise ValueError("every ledger snapshot must match the assembly corpus_id")
    for previous, current in zip(snapshots, snapshots[1:]):
        current.validate_successor_of(previous)

    snapshot_by_revision = {snapshot.revision: snapshot for snapshot in snapshots}
    deliveries_by_paper: dict[str, PaperStudyDeliveryV2] = {}
    claim_targets = _claim_targets_from_ledger(result.final_ledger)
    delivered_claim_refs: set[tuple[str, str]] = set()
    for delivery in result.deliveries:
        paper_id = delivery.packet.paper_id
        if paper_id in deliveries_by_paper:
            raise ValueError("assembly deliveries contain a duplicate paper_id")
        deliveries_by_paper[paper_id] = delivery
        try:
            generation_snapshot = snapshot_by_revision[
                delivery.generation_context.ledger_revision
            ]
        except KeyError as exc:
            raise ValueError(
                "delivery generation_context identifies a missing ledger revision: "
                f"{paper_id!r}"
            ) from exc
        delivery.validate_against_ledgers(generation_snapshot, result.final_ledger)
        for alignment in delivery.alignments:
            claim_ref = (paper_id, alignment.source.canonical_id)
            expected_target = claim_targets.get(claim_ref)
            if expected_target is None:
                raise ValueError(
                    "delivery claim has no evidence target in the final ledger: "
                    f"{claim_ref!r}"
                )
            if alignment.target_assertion_id != expected_target:
                raise ValueError(
                    "delivery alignment target does not own its source claim evidence"
                )
            delivered_claim_refs.add(claim_ref)
    if delivered_claim_refs != set(claim_targets):
        missing = tuple(sorted(set(claim_targets) - delivered_claim_refs))
        raise ValueError(
            "final ledger claim evidence is missing from assembly deliveries: "
            f"{missing!r}"
        )
    return result


def _validate_scheduler_result(scheduler_result: SchedulerRunResult) -> None:
    """Reject structurally valid but internally inconsistent scheduler audits."""

    ordered_entries = scheduler_result.ordered_entries
    entry_ids = tuple(entry.paper_id for entry in ordered_entries)
    if len(entry_ids) != len(set(entry_ids)):
        raise ValueError("scheduler ordered_entries contains duplicate paper_id values")
    entry_by_id = {entry.paper_id: entry for entry in ordered_entries}

    batches = scheduler_result.batches
    if ordered_entries and not batches:
        raise ValueError("scheduler result has entries but no batch audits")
    if not batches:
        return

    first_batch = batches[0].batch_number
    expected_numbers = tuple(range(first_batch, first_batch + len(batches)))
    actual_numbers = tuple(batch.batch_number for batch in batches)
    if actual_numbers != expected_numbers:
        raise ValueError("scheduler batch numbers must be contiguous")

    audited_ids: list[str] = []
    previous_output = None
    for batch in batches:
        expected_input_batch = batch.batch_number - 1
        if batch.input_context.through_batch != expected_input_batch:
            raise ValueError(
                "batch input_context.through_batch must immediately precede its batch"
            )
        if batch.output_context.through_batch != batch.batch_number:
            raise ValueError("batch output_context.through_batch must equal batch_number")
        if previous_output is not None and batch.input_context != previous_output:
            raise ValueError("a batch input_context must equal the prior output_context")

        input_digest = batch.input_context.digest()
        positions = tuple(audit.position_in_batch for audit in batch.papers)
        if positions != tuple(range(1, len(batch.papers) + 1)):
            raise ValueError("paper positions must be contiguous within each batch")
        for audit in batch.papers:
            if audit.batch_number != batch.batch_number:
                raise ValueError("paper audit batch_number does not match its batch")
            if audit.input_context_digest != input_digest:
                raise ValueError(
                    "paper audit input_context_digest does not match batch input_context"
                )
            entry = entry_by_id.get(audit.paper_id)
            if entry is None:
                raise ValueError("paper audit does not correspond to an ordered entry")
            if audit.source_path != entry.source_path:
                raise ValueError("paper audit source_path does not match its ordered entry")
            if audit.packet is not None and audit.packet.paper_id != audit.paper_id:
                raise ValueError("paper audit packet paper_id does not match its audit")
            audited_ids.append(audit.paper_id)
        previous_output = batch.output_context

    if tuple(audited_ids) != entry_ids:
        raise ValueError(
            "paper audits must exactly follow scheduler ordered_entries without gaps"
        )
    if scheduler_result.final_context != batches[-1].output_context:
        raise ValueError("scheduler final_context must equal the last output_context")
    if scheduler_result.strategic_plan is not None and (
        scheduler_result.strategic_plan.ordered_paper_ids != entry_ids
    ):
        raise ValueError("strategic plan order does not match scheduler ordered_entries")


def _resolve_starting_ledger(
    *,
    corpus_id: str,
    expected_revision: int,
    initial_ledger: GlobalStateLedger | None,
) -> GlobalStateLedger:
    if initial_ledger is None:
        if expected_revision != 0:
            raise ValueError(
                "A scheduler run beginning after batch 1 requires initial_ledger"
            )
        return GlobalStateLedger(
            corpus_id=corpus_id,
            reducer_policy_version=REDUCER_POLICY_VERSION,
            alignment_policy_version=ALIGNMENT_POLICY_VERSION,
        )

    if initial_ledger.corpus_id != corpus_id:
        raise ValueError("initial_ledger corpus_id does not match corpus_id")
    if initial_ledger.revision != expected_revision:
        raise ValueError(
            "initial_ledger revision must immediately precede the first scheduler batch"
        )
    if initial_ledger.reducer_policy_version != REDUCER_POLICY_VERSION:
        raise ValueError("initial_ledger reducer policy is incompatible")
    if initial_ledger.alignment_policy_version != ALIGNMENT_POLICY_VERSION:
        raise ValueError("initial_ledger alignment policy is incompatible")
    return initial_ledger


def _claim_targets_from_ledger(
    ledger: GlobalStateLedger,
) -> dict[tuple[str, str], str]:
    targets: dict[tuple[str, str], str] = {}
    for assertion in ledger.assertions:
        for evidence in assertion.evidence:
            key = (evidence.claim.paper_id, evidence.claim.canonical_id)
            existing = targets.get(key)
            if existing is not None and existing != assertion.assertion_id:
                raise ValueError(
                    "initial_ledger maps one claim reference to multiple assertions"
                )
            targets[key] = assertion.assertion_id
    return targets


def assemble_scheduler_result(
    scheduler_result: SchedulerRunResult,
    *,
    corpus_id: str,
    initial_ledger: GlobalStateLedger | None = None,
) -> CorpusAssemblyResult:
    """Reduce scheduler audits and reconcile their packets to the final state.

    A resumed scheduler run must supply the exact ledger snapshot immediately before
    its first batch.  This prevents a batch numbered after one from being silently
    attached to a fresh, unrelated ledger chain.
    """

    _validate_scheduler_result(scheduler_result)
    first_batch_number = (
        scheduler_result.batches[0].batch_number if scheduler_result.batches else None
    )
    expected_revision = (
        first_batch_number - 1
        if first_batch_number is not None
        else scheduler_result.final_context.through_batch
    )
    starting_ledger = _resolve_starting_ledger(
        corpus_id=corpus_id,
        expected_revision=expected_revision,
        initial_ledger=initial_ledger,
    )
    snapshots = [starting_ledger]
    snapshots_by_revision = {starting_ledger.revision: starting_ledger}
    claim_targets = _claim_targets_from_ledger(starting_ledger)
    packet_batches: dict[str, BatchAudit] = {}

    for batch in scheduler_result.batches:
        previous = snapshots[-1]
        current, new_targets = _reduce_batch(previous, batch)
        current.validate_successor_of(previous)
        snapshots.append(current)
        snapshots_by_revision[current.revision] = current
        claim_targets.update(new_targets)
        for audit in batch.papers:
            if audit.packet is not None:
                packet_batches[audit.paper_id] = batch

    final_ledger = snapshots[-1]
    deliveries: list[PaperStudyDeliveryV2] = []
    for packet in scheduler_result.packets:
        batch = packet_batches[packet.paper_id]
        input_revision = batch.batch_number - 1
        try:
            input_snapshot = snapshots_by_revision[input_revision]
        except KeyError as exc:
            raise ValueError(
                "Missing generation ledger snapshot for revision "
                f"{input_revision} (paper {packet.paper_id!r})"
            ) from exc
        missing_findings = tuple(
            (finding.paper_id, finding.claim_id)
            for finding in batch.input_context.findings
            if (finding.paper_id, finding.claim_id) not in claim_targets
        )
        if missing_findings:
            raise ValueError(
                "Generation context references findings absent from its ledger: "
                f"{missing_findings}"
            )
        included_assertion_ids = tuple(
            sorted(
                {
                    claim_targets[(finding.paper_id, finding.claim_id)]
                    for finding in batch.input_context.findings
                }
            )
        )
        generation_context = GenerationContextReceipt(
            ledger_digest=input_snapshot.digest(),
            ledger_revision=input_snapshot.revision,
            through_batch=input_snapshot.through_batch,
            projection_policy_version=PROJECTION_POLICY_VERSION,
            prompt_projection_digest=batch.input_context.prompt_projection_digest(),
            included_assertion_ids=included_assertion_ids,
        )
        delivery = _reconcile_delivery(
            packet=packet,
            packet_digest=packet_content_digest(packet),
            generation_context=generation_context,
            final_ledger=final_ledger,
            claim_targets=claim_targets,
        )
        delivery.validate_against_ledgers(input_snapshot, final_ledger)
        deliveries.append(delivery)
    result = CorpusAssemblyResult(
        corpus_id=corpus_id,
        ledger_snapshots=tuple(snapshots),
        deliveries=tuple(sorted(deliveries, key=lambda item: item.packet.paper_id)),
    )
    if starting_ledger.revision == 0:
        return _validate_corpus_assembly_result(result)
    return result


def load_corpus_assembly(
    assembly_manifest_path: str | Path,
) -> CorpusAssemblyResult:
    """Load and fully audit an assembly from its persisted manifest.

    The manifest is not treated as sufficient proof: every content-addressed
    snapshot and delivery is parsed, the complete successor chain is replayed,
    and both receipt planes are checked against the ledgers they identify.
    """

    manifest_path = Path(assembly_manifest_path).expanduser().resolve()
    manifest = _read_json_object(manifest_path, description="assembly manifest")
    if manifest.get("schema_version") != "1.0":
        raise ValueError("unsupported assembly manifest schema_version")
    corpus_id = manifest.get("corpus_id")
    if not isinstance(corpus_id, str) or not corpus_id:
        raise ValueError("assembly manifest corpus_id must be a non-empty string")

    raw_snapshot_paths = manifest.get("snapshot_paths")
    if not isinstance(raw_snapshot_paths, list) or not raw_snapshot_paths:
        raise ValueError("assembly manifest snapshot_paths must be a non-empty list")
    snapshot_paths = tuple(
        _resolve_manifest_member(manifest_path, value, description="snapshot path")
        for value in raw_snapshot_paths
    )
    if len(snapshot_paths) != len(set(snapshot_paths)):
        raise ValueError("assembly manifest contains duplicate snapshot paths")
    snapshots = tuple(
        GlobalStateLedger.model_validate_json(path.read_text(encoding="utf-8"))
        for path in snapshot_paths
    )

    raw_delivery_paths = manifest.get("delivery_paths")
    if not isinstance(raw_delivery_paths, Mapping):
        raise ValueError("assembly manifest delivery_paths must be an object")
    resolved_delivery_paths: dict[str, Path] = {}
    for paper_id, value in raw_delivery_paths.items():
        if not isinstance(paper_id, str) or not paper_id:
            raise ValueError("delivery_paths keys must be non-empty paper IDs")
        resolved_delivery_paths[paper_id] = _resolve_manifest_member(
            manifest_path,
            value,
            description=f"delivery path for {paper_id!r}",
        )
    if len(set(resolved_delivery_paths.values())) != len(resolved_delivery_paths):
        raise ValueError("assembly manifest contains duplicate delivery paths")
    deliveries: list[PaperStudyDeliveryV2] = []
    for paper_id in sorted(resolved_delivery_paths):
        delivery = PaperStudyDeliveryV2.model_validate_json(
            resolved_delivery_paths[paper_id].read_text(encoding="utf-8")
        )
        if delivery.packet.paper_id != paper_id:
            raise ValueError("delivery_paths key does not match delivery packet.paper_id")
        deliveries.append(delivery)

    result = CorpusAssemblyResult(
        corpus_id=corpus_id,
        ledger_snapshots=snapshots,
        deliveries=tuple(deliveries),
    )
    _validate_corpus_assembly_result(result)

    final_ledger = result.final_ledger
    if manifest.get("final_revision") != final_ledger.revision:
        raise ValueError("assembly manifest final_revision does not match snapshots")
    if manifest.get("final_ledger_digest") != final_ledger.digest():
        raise ValueError("assembly manifest final_ledger_digest does not match snapshots")
    ledger_path = _resolve_manifest_member(
        manifest_path,
        manifest.get("ledger_path"),
        description="final ledger path",
    )
    persisted_final = GlobalStateLedger.model_validate_json(
        ledger_path.read_text(encoding="utf-8")
    )
    if persisted_final != final_ledger:
        raise ValueError("assembly manifest ledger_path does not match final snapshot")
    return result


def extend_corpus_assembly(
    prior: CorpusAssemblyResult,
    appended_scheduler: SchedulerRunResult,
) -> CorpusAssemblyResult:
    """Append scheduler batches and reconcile every delivery to the new final ledger.

    Existing scientific packets and generation receipts are carried forward
    byte-for-byte at the model-content level.  Only AlignmentReceipt values are
    regenerated because they intentionally bind to the new final-ledger digest.
    """

    _validate_corpus_assembly_result(prior)
    if not appended_scheduler.batches:
        raise ValueError("an assembly extension requires at least one appended batch")

    prior_paper_ids = _committed_paper_ids(prior.final_ledger)
    appended_paper_ids = {
        entry.paper_id for entry in appended_scheduler.ordered_entries
    }
    duplicates = tuple(sorted(prior_paper_ids & appended_paper_ids))
    if duplicates:
        raise ValueError(
            "assembly extension cannot process a paper already committed: "
            f"{duplicates!r}"
        )

    appended = assemble_scheduler_result(
        appended_scheduler,
        corpus_id=prior.corpus_id,
        initial_ledger=prior.final_ledger,
    )
    if appended.ledger_snapshots[0] != prior.final_ledger:
        raise ValueError("appended assembly does not begin at the prior final ledger")
    combined_snapshots = (
        *prior.ledger_snapshots,
        *appended.ledger_snapshots[1:],
    )
    new_final = combined_snapshots[-1]
    if new_final.parent_digest != combined_snapshots[-2].digest():
        raise ValueError("appended ledger parent_digest is not continuous")

    claim_targets = _claim_targets_from_ledger(new_final)
    snapshot_by_revision = {
        snapshot.revision: snapshot for snapshot in combined_snapshots
    }
    source_deliveries = (*prior.deliveries, *appended.deliveries)
    reconciled_deliveries: list[PaperStudyDeliveryV2] = []
    for source_delivery in source_deliveries:
        reconciled = _reconcile_delivery(
            packet=source_delivery.packet,
            packet_digest=source_delivery.packet_digest,
            generation_context=source_delivery.generation_context,
            final_ledger=new_final,
            claim_targets=claim_targets,
        )
        if (
            reconciled.packet != source_delivery.packet
            or reconciled.packet_digest != source_delivery.packet_digest
            or reconciled.generation_context != source_delivery.generation_context
        ):
            raise ValueError(
                "assembly extension changed an immutable delivery generation component"
            )
        try:
            generation_snapshot = snapshot_by_revision[
                reconciled.generation_context.ledger_revision
            ]
        except KeyError as exc:
            raise ValueError(
                "extended delivery identifies a missing generation snapshot"
            ) from exc
        reconciled.validate_against_ledgers(generation_snapshot, new_final)
        reconciled_deliveries.append(reconciled)

    result = CorpusAssemblyResult(
        corpus_id=prior.corpus_id,
        ledger_snapshots=combined_snapshots,
        deliveries=tuple(
            sorted(reconciled_deliveries, key=lambda item: item.packet.paper_id)
        ),
    )
    return _validate_corpus_assembly_result(result)


def _reconcile_delivery(
    *,
    packet: PaperStudyPacketV2,
    packet_digest: str,
    generation_context: GenerationContextReceipt,
    final_ledger: GlobalStateLedger,
    claim_targets: Mapping[tuple[str, str], str],
) -> PaperStudyDeliveryV2:
    """Create only the deterministic final-ledger alignment plane for a packet."""

    assertions_by_id = {
        assertion.assertion_id: assertion for assertion in final_ledger.assertions
    }
    final_digest = final_ledger.digest()
    alignments: list[AlignmentReceipt] = []
    for question in packet.research_questions:
        for unit in question.study_units:
            for claim in unit.claims:
                claim_ref = (packet.paper_id, claim.claim_id)
                try:
                    target_id = claim_targets[claim_ref]
                except KeyError as exc:
                    raise ValueError(
                        f"Missing final assertion target for claim: {claim_ref!r}"
                    ) from exc
                if target_id not in assertions_by_id:
                    raise ValueError(f"Missing final assertion target: {target_id}")
                source = LedgerEntityRef(
                    paper_id=packet.paper_id,
                    entity_type="claim",
                    canonical_id=claim.claim_id,
                    packet_digest=packet_digest,
                )
                alignments.append(
                    AlignmentReceipt(
                        alignment_id=_stable_id(
                            "align",
                            {
                                "source": source.model_dump(mode="json"),
                                "target": target_id,
                                "ledger": final_digest,
                            },
                        ),
                        source=source,
                        target_assertion_id=target_id,
                        relation_type=(
                            "exact" if packet.status == "accepted" else "new_assertion"
                        ),
                        score_ppm=(
                            1_000_000 if packet.status == "accepted" else 350_000
                        ),
                        alignment_policy_version=final_ledger.alignment_policy_version,
                        output_ledger_digest=final_digest,
                    )
                )
    return PaperStudyDeliveryV2(
        packet=packet,
        packet_digest=packet_digest,
        generation_context=generation_context,
        alignments=tuple(sorted(alignments, key=lambda item: item.stable_key())),
    )


def _committed_paper_ids(ledger: GlobalStateLedger) -> set[str]:
    """Read successfully committed paper identities from immutable events.

    Failed attempts are intentionally excluded: recovery may append a later,
    successful attempt without creating duplicate scientific evidence.
    """

    paper_ids: set[str] = set()
    for event in ledger.events:
        if event.event_type != "batch_committed":
            continue
        outcomes = event.payload.get("paper_outcomes")
        if not isinstance(outcomes, Sequence) or isinstance(outcomes, (str, bytes)):
            raise ValueError("batch_committed paper_outcomes must be a sequence")
        for outcome in outcomes:
            if not isinstance(outcome, Mapping):
                raise ValueError("batch_committed paper outcome must be an object")
            paper_id = outcome.get("paper_id")
            if not isinstance(paper_id, str) or not paper_id:
                raise ValueError("batch_committed paper outcome requires paper_id")
            status = outcome.get("status")
            if status not in {"succeeded", "failed"}:
                raise ValueError("batch_committed paper outcome has invalid status")
            if status == "failed":
                continue
            if paper_id in paper_ids:
                raise ValueError(
                    "ledger successfully commits the same paper_id more than once"
                )
            paper_ids.add(paper_id)
    return paper_ids


def _read_json_object(path: Path, *, description: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"unable to read {description}: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{description} must contain a JSON object")
    return payload


def _resolve_manifest_member(
    manifest_path: Path,
    value: object,
    *,
    description: str,
) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{description} must be a non-empty path string")
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = manifest_path.parent / path
    return path.resolve()


def write_corpus_assembly(
    result: CorpusAssemblyResult,
    output_root: str | Path,
) -> dict[str, str]:
    """Persist immutable snapshots, final ledger, deliveries, and an assembly manifest."""

    root = Path(output_root)
    ledger_root = root / "ledger"
    delivery_root = root / "deliveries"
    paths: dict[str, str] = {}
    snapshot_paths = []
    for snapshot in result.ledger_snapshots:
        digest_suffix = snapshot.digest().removeprefix("sha256:")[:16]
        path = ledger_root / "snapshots" / (
            f"revision-{snapshot.revision:04d}-{digest_suffix}.json"
        )
        _write_json(snapshot.model_dump(mode="json"), path)
        snapshot_paths.append(str(path.resolve()))
    final_digest_hex = result.final_ledger.digest().removeprefix("sha256:")
    final_path = ledger_root / f"global_state_ledger-{final_digest_hex}.json"
    final_payload = result.final_ledger.model_dump(mode="json")
    _write_json(final_payload, final_path)
    compatibility_ledger_path = ledger_root / "global_state_ledger.json"
    _write_json(final_payload, compatibility_ledger_path)
    paths["ledger"] = str(final_path.resolve())
    paths["ledger_compat"] = str(compatibility_ledger_path.resolve())

    delivery_paths = {}
    compatibility_delivery_paths = {}
    for delivery in result.deliveries:
        delivery_digest = _sha256_json(delivery.model_dump(mode="json"))
        path = delivery_root / f"{delivery.packet.paper_id}-{delivery_digest}.json"
        delivery_payload = delivery.model_dump(mode="json")
        _write_json(delivery_payload, path)
        delivery_paths[delivery.packet.paper_id] = str(path.resolve())
        compatibility_path = delivery_root / f"{delivery.packet.paper_id}.json"
        _write_json(delivery_payload, compatibility_path)
        compatibility_delivery_paths[delivery.packet.paper_id] = str(
            compatibility_path.resolve()
        )
    manifest_path = root / "assembly_manifest.json"
    _write_json(
        {
            "schema_version": "1.0",
            "corpus_id": result.corpus_id,
            "final_ledger_digest": result.final_ledger.digest(),
            "final_revision": result.final_ledger.revision,
            "ledger_path": str(final_path.resolve()),
            "compatibility_ledger_path": str(compatibility_ledger_path.resolve()),
            "snapshot_paths": snapshot_paths,
            "delivery_paths": dict(sorted(delivery_paths.items())),
            "compatibility_delivery_paths": dict(
                sorted(compatibility_delivery_paths.items())
            ),
        },
        manifest_path,
    )
    paths["assembly_manifest"] = str(manifest_path.resolve())
    paths.update({f"delivery:{key}": value for key, value in delivery_paths.items()})
    return paths


def _reduce_batch(
    previous: GlobalStateLedger,
    batch: BatchAudit,
) -> tuple[GlobalStateLedger, dict[tuple[str, str], str]]:
    if batch.batch_number != previous.revision + 1:
        raise ValueError("Batch number must immediately follow the ledger revision")
    assertions = {item.assertion_id: item for item in previous.assertions}
    relations = {item.relation_id: item for item in previous.relations}
    events = list(previous.events)
    targets: dict[tuple[str, str], str] = {}

    for audit in batch.papers:
        packet = audit.packet
        if packet is None:
            continue
        packet_digest = packet_content_digest(packet)
        for question in packet.research_questions:
            for unit in question.study_units:
                for claim in sorted(unit.claims, key=lambda item: item.claim_id):
                    assertion_id, proposition_key, conditions = _assertion_identity(claim)
                    evidence = AssertionEvidenceRef(
                        claim=LedgerEntityRef(
                            paper_id=packet.paper_id,
                            entity_type="claim",
                            canonical_id=claim.claim_id,
                            packet_digest=packet_digest,
                        ),
                        result_ids=tuple(sorted(set(claim.inference_basis_ids))),
                        source_chunk_ids=tuple(
                            sorted(
                                {
                                    claim.provenance.chunk_id,
                                    *(
                                        provenance.chunk_id
                                        for provenance in claim.additional_provenance
                                    ),
                                }
                            )
                        ),
                        admission_status=packet.status,
                        weight_ppm=(
                            1_000_000
                            if packet.status == "accepted"
                            else 350_000
                        ),
                    )
                    existing = assertions.get(assertion_id)
                    if existing is None:
                        assertion = GlobalAssertion(
                            assertion_id=assertion_id,
                            proposition_key=proposition_key,
                            preferred_statement=normalize_scientific_text(claim.statement),
                            polarity=claim.polarity,
                            status=(
                                "supported"
                                if packet.status == "accepted"
                                else "unresolved"
                            ),
                            conditions=conditions,
                            evidence=(evidence,),
                        )
                        assertions[assertion_id] = assertion
                        events.append(
                            _event(
                                len(events) + 1,
                                batch.batch_number,
                                "assertion_added",
                                assertion_id,
                                assertion.model_dump(mode="json"),
                            )
                        )
                    else:
                        evidence_by_key = {
                            item.stable_key(): item for item in existing.evidence
                        }
                        if evidence.stable_key() not in evidence_by_key:
                            evidence_by_key[evidence.stable_key()] = evidence
                            revised_status = (
                                "supported"
                                if existing.status == "unresolved"
                                and evidence.admission_status == "accepted"
                                else existing.status
                            )
                            assertions[assertion_id] = existing.model_copy(
                                update={
                                    "evidence": tuple(
                                        evidence_by_key[key]
                                        for key in sorted(evidence_by_key)
                                    ),
                                    "status": revised_status,
                                }
                            )
                            events.append(
                                _event(
                                    len(events) + 1,
                                    batch.batch_number,
                                    "assertion_evidence_added",
                                    assertion_id,
                                    evidence.model_dump(mode="json"),
                                )
                            )
                            if revised_status != existing.status:
                                events.append(
                                    _event(
                                        len(events) + 1,
                                        batch.batch_number,
                                        "assertion_revised",
                                        assertion_id,
                                        {
                                            "previous_status": existing.status,
                                            "status": revised_status,
                                            "reason": "accepted_evidence_admitted",
                                            "evidence_claim": (
                                                evidence.claim.model_dump(mode="json")
                                            ),
                                        },
                                    )
                                )
                    targets[(packet.paper_id, claim.claim_id)] = assertion_id

    assertion_ids = tuple(sorted(assertions))
    for index, left_id in enumerate(assertion_ids):
        for right_id in assertion_ids[index + 1 :]:
            # Status is read live because a contradiction earlier in this same
            # revision can move an assertion from supported to contested.
            left = assertions[left_id]
            right = assertions[right_id]
            if left.status != "supported" or right.status != "supported":
                continue
            relation = _candidate_relation(left, right)
            if relation is None or relation.relation_id in relations:
                continue
            relations[relation.relation_id] = relation
            events.append(
                _event(
                    len(events) + 1,
                    batch.batch_number,
                    "relation_added",
                    relation.relation_id,
                    relation.model_dump(mode="json"),
                )
            )
            if relation.relation_type == "contradicts":
                for assertion_id in (
                    relation.source_assertion_id,
                    relation.target_assertion_id,
                ):
                    assertion = assertions[assertion_id]
                    if assertion.status == "contested":
                        continue
                    revised = assertion.model_copy(update={"status": "contested"})
                    assertions[assertion_id] = revised
                    events.append(
                        _event(
                            len(events) + 1,
                            batch.batch_number,
                            "assertion_revised",
                            assertion_id,
                            {
                                "previous_status": assertion.status,
                                "status": "contested",
                                "reason_relation_id": relation.relation_id,
                            },
                        )
                    )

    commit_payload = {
        "batch_number": batch.batch_number,
        "input_context_digest": batch.input_context.digest(),
        "input_prompt_projection_digest": (
            batch.input_context.prompt_projection_digest()
        ),
        "output_context_digest": batch.output_context.digest(),
        "output_prompt_projection_digest": (
            batch.output_context.prompt_projection_digest()
        ),
        "extracted_finding_count": batch.extracted_finding_count,
        "paper_outcomes": [_paper_commit_payload(audit) for audit in batch.papers],
    }
    events.append(
        _event(
            len(events) + 1,
            batch.batch_number,
            "batch_committed",
            f"batch:{batch.batch_number}",
            commit_payload,
        )
    )
    ledger = GlobalStateLedger(
        corpus_id=previous.corpus_id,
        revision=batch.batch_number,
        through_batch=batch.batch_number,
        parent_digest=previous.digest(),
        reducer_policy_version=previous.reducer_policy_version,
        alignment_policy_version=previous.alignment_policy_version,
        assertions=tuple(assertions[key] for key in sorted(assertions)),
        relations=tuple(
            sorted(relations.values(), key=lambda item: item.stable_key())
        ),
        events=tuple(events),
    )
    return ledger, targets


def _paper_commit_payload(audit: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "paper_id": getattr(audit, "paper_id"),
        "source_path": getattr(audit, "source_path"),
        "batch_number": getattr(audit, "batch_number"),
        "position_in_batch": getattr(audit, "position_in_batch"),
        "status": getattr(audit, "status"),
        "input_context_digest": getattr(audit, "input_context_digest"),
    }
    packet = getattr(audit, "packet")
    if packet is not None:
        payload["packet_digest"] = packet_content_digest(packet)
        payload["packet_status"] = packet.status
    else:
        payload["error_type"] = getattr(audit, "error_type")
        payload["error_message"] = getattr(audit, "error_message")
    return payload


def _assertion_identity(claim: object) -> tuple[str, str, tuple[str, ...]]:
    statement = normalize_scientific_text(getattr(claim, "statement"))
    polarity = getattr(claim, "polarity")
    conditions = tuple(
        sorted(
            f"{condition.kind}:{condition.value}"
            for condition in extract_protected_conditions(statement)
        )
    )
    proposition_payload = {
        "statement": statement,
        "polarity": polarity,
        "conditions": conditions,
    }
    proposition_key = "sha256:" + _sha256_json(proposition_payload)
    return f"ga_{_sha256_json(proposition_payload)[:24]}", proposition_key, conditions


def _candidate_relation(
    left: GlobalAssertion,
    right: GlobalAssertion,
) -> AssertionRelation | None:
    left_tokens = set(re.findall(r"[a-z0-9]+", left.preferred_statement))
    right_tokens = set(re.findall(r"[a-z0-9]+", right.preferred_statement))
    union = left_tokens | right_tokens
    score = 0.0 if not union else len(left_tokens & right_tokens) / len(union)
    if score < _RELATION_THRESHOLD:
        return None
    opposite = {left.polarity, right.polarity} == {"positive", "negative"}
    if left.conditions != right.conditions:
        relation_type = "conditioned_on"
    elif opposite:
        relation_type = "contradicts"
    else:
        relation_type = "supports"
    source_id, target_id = sorted((left.assertion_id, right.assertion_id))
    payload = {
        "source": source_id,
        "target": target_id,
        "type": relation_type,
        "policy": ALIGNMENT_POLICY_VERSION,
    }
    return AssertionRelation(
        relation_id=_stable_id("rel", payload),
        source_assertion_id=source_id,
        target_assertion_id=target_id,
        relation_type=relation_type,
        score_ppm=round(score * 1_000_000),
        policy_version=ALIGNMENT_POLICY_VERSION,
    )


def _event(
    sequence: int,
    revision: int,
    event_type: str,
    subject_id: str,
    payload: object,
) -> LedgerEvent:
    payload_digest = "sha256:" + _sha256_json(payload)
    return LedgerEvent.model_validate(
        {
            "event_id": _stable_id(
                "evt",
                {
                    "sequence": sequence,
                    "revision": revision,
                    "event_type": event_type,
                    "subject_id": subject_id,
                    "payload_digest": payload_digest,
                },
            ),
            "sequence": sequence,
            "revision": revision,
            "event_type": event_type,
            "subject_id": subject_id,
            "payload": payload,
            "payload_digest": payload_digest,
        }
    )


def _stable_id(prefix: str, payload: object) -> str:
    return f"{prefix}_{_sha256_json(payload)[:24]}"


def _sha256_json(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _write_json(payload: object, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
