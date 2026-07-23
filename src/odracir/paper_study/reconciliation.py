"""Deterministic, non-mutating final reconciliation for a corpus assembly.

The assembly ledger is an immutable history of extraction-time admission.  This
module derives a content-addressed core view from that history; it never changes a
Packet, Delivery, receipt, or ledger snapshot.  Policy v1 is intentionally
conservative: only complete evidence from an accepted Packet enters the core.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from odracir.paper_study.assembly import CorpusAssemblyResult
from odracir.paper_study.models import (
    AssertionRelation,
    ClaimPolarity,
    GlobalAssertion,
    PaperStudyDeliveryV2,
    StrictModel,
)


_SHA256_PATTERN = r"^sha256:[0-9a-f]{64}$"
ReconciliationDisposition = Literal[
    "core_accepted",
    "deferred",
    "excluded_invalid",
]


class FinalReconciliationPolicy(StrictModel):
    """Versioned v1 policy, with reserved thresholds for later promotion modes."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: Literal["1.0"] = "1.0"
    policy_version: Literal["final-reconciliation/accepted-only-v1"] = (
        "final-reconciliation/accepted-only-v1"
    )
    admission_mode: Literal["accepted_only"] = "accepted_only"
    accepted_base_weight_ppm: int = Field(default=1_000_000, ge=1, le=1_000_000)
    provisional_base_weight_ppm: int = Field(default=350_000, ge=1, le=500_000)
    provisional_quality_threshold_ppm: int = Field(
        default=900_000, ge=0, le=1_000_000
    )
    cross_support_quality_threshold_ppm: int = Field(
        default=850_000, ge=0, le=1_000_000
    )
    cross_support_min_independent_papers: int = Field(default=2, ge=2)
    cross_support_min_effective_weight_ppm: int = Field(
        default=595_000, ge=1, le=1_000_000
    )
    equivalence_threshold_ppm: int = Field(default=900_000, ge=0, le=1_000_000)
    contradiction_threshold_ppm: int = Field(
        default=850_000, ge=0, le=1_000_000
    )

    def digest(self) -> str:
        return _model_digest(self)


class SourceDeliveryBinding(StrictModel):
    """Content binding for one immutable input Delivery."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    paper_id: str = Field(min_length=1)
    delivery_digest: str = Field(pattern=_SHA256_PATTERN)
    packet_digest: str = Field(pattern=_SHA256_PATTERN)


class CoreEvidence(StrictModel):
    """Accepted Claim evidence admitted to the derived core."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    evidence_id: str = Field(min_length=1)
    paper_id: str = Field(min_length=1)
    claim_id: str = Field(min_length=1)
    result_ids: tuple[str, ...]
    source_chunk_ids: tuple[str, ...] = Field(min_length=1)
    packet_digest: str = Field(pattern=_SHA256_PATTERN)
    admission_status: Literal["accepted"] = "accepted"
    quality_ppm: int = Field(ge=0, le=1_000_000)
    effective_weight_ppm: int = Field(ge=0, le=1_000_000)


class CoreAssertion(StrictModel):
    """One corpus assertion with only reconciled core evidence attached."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    assertion_id: str = Field(min_length=1)
    preferred_statement: str = Field(min_length=1)
    polarity: ClaimPolarity
    conditions: tuple[str, ...]
    confidence_weight_ppm: int = Field(ge=0, le=1_000_000)
    evidence: tuple[CoreEvidence, ...] = Field(min_length=1)


class CoreKnowledgeSnapshot(StrictModel):
    """Content-addressed conservative knowledge view consumed downstream."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: Literal["1.0"] = "1.0"
    corpus_id: str = Field(min_length=1)
    source_ledger_digest: str = Field(pattern=_SHA256_PATTERN)
    source_ledger_revision: int = Field(ge=0)
    source_deliveries: tuple[SourceDeliveryBinding, ...]
    policy_version: str = Field(min_length=1)
    policy_digest: str = Field(pattern=_SHA256_PATTERN)
    assertions: tuple[CoreAssertion, ...]
    relations: tuple[AssertionRelation, ...]

    def digest(self) -> str:
        return _model_digest(self)


class EvidenceReconciliationDecision(StrictModel):
    """Claim-level admission audit for one ledger evidence reference."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    decision_id: str = Field(min_length=1)
    evidence_id: str = Field(min_length=1)
    assertion_id: str = Field(min_length=1)
    paper_id: str = Field(min_length=1)
    claim_id: str = Field(min_length=1)
    result_ids: tuple[str, ...]
    disposition: ReconciliationDisposition
    quality_ppm: int = Field(ge=0, le=1_000_000)
    base_weight_ppm: int = Field(ge=1, le=1_000_000)
    effective_weight_ppm: int = Field(ge=0, le=1_000_000)
    reason_codes: tuple[str, ...] = Field(min_length=1)


class AssertionReconciliationDecision(StrictModel):
    """Stable assertion-level summary of its evidence decisions."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    decision_id: str = Field(min_length=1)
    assertion_id: str = Field(min_length=1)
    disposition: ReconciliationDisposition
    evidence_decision_ids: tuple[str, ...] = Field(min_length=1)
    reason_codes: tuple[str, ...] = Field(min_length=1)
    confidence_weight_ppm: int = Field(ge=0, le=1_000_000)


class ReconciliationDecisionLog(StrictModel):
    """Complete deterministic decision audit for one source ledger."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: Literal["1.0"] = "1.0"
    corpus_id: str = Field(min_length=1)
    source_ledger_digest: str = Field(pattern=_SHA256_PATTERN)
    policy_digest: str = Field(pattern=_SHA256_PATTERN)
    evidence_decisions: tuple[EvidenceReconciliationDecision, ...]
    assertion_decisions: tuple[AssertionReconciliationDecision, ...]

    def digest(self) -> str:
        return _model_digest(self)


class CriticalConflict(StrictModel):
    """A ledger-declared contradiction whose endpoints both entered the core."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    conflict_id: str = Field(min_length=1)
    relation_id: str = Field(min_length=1)
    source_assertion_id: str = Field(min_length=1)
    target_assertion_id: str = Field(min_length=1)
    score_ppm: int = Field(ge=0, le=1_000_000)
    source_statement: str = Field(min_length=1)
    target_statement: str = Field(min_length=1)


class CriticalConflictReport(StrictModel):
    """High-precision conflict list; an empty report is a valid result."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: Literal["1.0"] = "1.0"
    corpus_id: str = Field(min_length=1)
    source_ledger_digest: str = Field(pattern=_SHA256_PATTERN)
    policy_digest: str = Field(pattern=_SHA256_PATTERN)
    conflicts: tuple[CriticalConflict, ...]

    def digest(self) -> str:
        return _model_digest(self)


class FinalReconciliationResult(StrictModel):
    """In-memory result of the three reconciliation output planes."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    policy: FinalReconciliationPolicy
    core_snapshot: CoreKnowledgeSnapshot
    decision_log: ReconciliationDecisionLog
    conflict_report: CriticalConflictReport

    @model_validator(mode="after")
    def validate_bindings(self) -> FinalReconciliationResult:
        policy_digest = self.policy.digest()
        artifacts = (self.core_snapshot, self.decision_log, self.conflict_report)
        if any(item.policy_digest != policy_digest for item in artifacts):
            raise ValueError("reconciliation artifacts do not bind to the policy")
        if len({item.source_ledger_digest for item in artifacts}) != 1:
            raise ValueError("reconciliation artifacts use different source ledgers")
        if len({item.corpus_id for item in artifacts}) != 1:
            raise ValueError("reconciliation artifacts use different corpus IDs")
        return self


class ReconciliationManifest(StrictModel):
    """Typed file manifest with digest verification for every persisted artifact."""

    schema_version: Literal["1.0"] = "1.0"
    corpus_id: str = Field(min_length=1)
    source_ledger_digest: str = Field(pattern=_SHA256_PATTERN)
    policy_digest: str = Field(pattern=_SHA256_PATTERN)
    policy: FinalReconciliationPolicy
    core_snapshot_path: str = Field(min_length=1)
    core_snapshot_digest: str = Field(pattern=_SHA256_PATTERN)
    decision_log_path: str = Field(min_length=1)
    decision_log_digest: str = Field(pattern=_SHA256_PATTERN)
    conflict_report_path: str = Field(min_length=1)
    conflict_report_digest: str = Field(pattern=_SHA256_PATTERN)


def reconcile_corpus(
    assembly: CorpusAssemblyResult,
    *,
    policy: FinalReconciliationPolicy | None = None,
) -> FinalReconciliationResult:
    """Derive an accepted-only core without mutating any assembly component."""

    settings = policy or FinalReconciliationPolicy()
    _validate_assembly(assembly)
    ledger = assembly.final_ledger
    delivery_by_paper = {item.packet.paper_id: item for item in assembly.deliveries}
    bindings = tuple(
        SourceDeliveryBinding(
            paper_id=paper_id,
            delivery_digest=_model_digest(delivery),
            packet_digest=delivery.packet_digest,
        )
        for paper_id, delivery in sorted(delivery_by_paper.items())
    )

    evidence_decisions: list[EvidenceReconciliationDecision] = []
    assertion_decisions: list[AssertionReconciliationDecision] = []
    core_assertions: list[CoreAssertion] = []

    for assertion in ledger.assertions:
        local_decisions: list[EvidenceReconciliationDecision] = []
        admitted: list[CoreEvidence] = []
        for evidence in assertion.evidence:
            delivery = delivery_by_paper.get(evidence.claim.paper_id)
            invalid_reasons = _scientific_chain_errors(evidence, delivery)
            quality_ppm = (
                0 if delivery is None else _quality_ppm(delivery.packet.quality_score)
            )
            base_weight = evidence.weight_ppm
            evidence_id = _stable_id(
                "evidence",
                {
                    "assertion_id": assertion.assertion_id,
                    "evidence": evidence.model_dump(mode="json"),
                },
            )
            if invalid_reasons:
                disposition: ReconciliationDisposition = "excluded_invalid"
                reasons = tuple(sorted(set(invalid_reasons)))
                effective_weight = 0
            elif evidence.admission_status == "provisional":
                disposition = "deferred"
                reasons = ("provisional_deferred_by_accepted_only_policy",)
                effective_weight = _effective_weight(base_weight, quality_ppm)
            else:
                disposition = "core_accepted"
                reasons = ("accepted_complete_scientific_chain",)
                effective_weight = _effective_weight(base_weight, quality_ppm)
                admitted.append(
                    CoreEvidence(
                        evidence_id=evidence_id,
                        paper_id=evidence.claim.paper_id,
                        claim_id=evidence.claim.canonical_id,
                        result_ids=evidence.result_ids,
                        source_chunk_ids=evidence.source_chunk_ids,
                        packet_digest=evidence.claim.packet_digest,
                        quality_ppm=quality_ppm,
                        effective_weight_ppm=effective_weight,
                    )
                )
            decision_payload = {
                "evidence_id": evidence_id,
                "assertion_id": assertion.assertion_id,
                "disposition": disposition,
                "reason_codes": reasons,
                "policy_digest": settings.digest(),
            }
            decision = EvidenceReconciliationDecision(
                decision_id=_stable_id("decision", decision_payload),
                evidence_id=evidence_id,
                assertion_id=assertion.assertion_id,
                paper_id=evidence.claim.paper_id,
                claim_id=evidence.claim.canonical_id,
                result_ids=evidence.result_ids,
                disposition=disposition,
                quality_ppm=quality_ppm,
                base_weight_ppm=base_weight,
                effective_weight_ppm=effective_weight,
                reason_codes=reasons,
            )
            local_decisions.append(decision)
            evidence_decisions.append(decision)

        confidence = min(
            1_000_000,
            sum(item.effective_weight_ppm for item in admitted),
        )
        if admitted:
            assertion_disposition: ReconciliationDisposition = "core_accepted"
            assertion_reasons = ("has_accepted_complete_evidence",)
            core_assertions.append(
                CoreAssertion(
                    assertion_id=assertion.assertion_id,
                    preferred_statement=assertion.preferred_statement,
                    polarity=assertion.polarity,
                    conditions=assertion.conditions,
                    confidence_weight_ppm=confidence,
                    evidence=tuple(sorted(admitted, key=lambda item: item.evidence_id)),
                )
            )
        elif any(item.disposition == "deferred" for item in local_decisions):
            assertion_disposition = "deferred"
            assertion_reasons = ("only_provisional_complete_evidence",)
        else:
            assertion_disposition = "excluded_invalid"
            assertion_reasons = ("no_complete_accepted_or_provisional_evidence",)
        summary_payload = {
            "assertion_id": assertion.assertion_id,
            "disposition": assertion_disposition,
            "evidence_decision_ids": sorted(item.decision_id for item in local_decisions),
            "policy_digest": settings.digest(),
        }
        assertion_decisions.append(
            AssertionReconciliationDecision(
                decision_id=_stable_id("assertion-decision", summary_payload),
                assertion_id=assertion.assertion_id,
                disposition=assertion_disposition,
                evidence_decision_ids=tuple(summary_payload["evidence_decision_ids"]),
                reason_codes=assertion_reasons,
                confidence_weight_ppm=confidence,
            )
        )

    core_ids = {item.assertion_id for item in core_assertions}
    core_relations = tuple(
        relation
        for relation in ledger.relations
        if relation.source_assertion_id in core_ids
        and relation.target_assertion_id in core_ids
    )
    policy_digest = settings.digest()
    snapshot = CoreKnowledgeSnapshot(
        corpus_id=assembly.corpus_id,
        source_ledger_digest=ledger.digest(),
        source_ledger_revision=ledger.revision,
        source_deliveries=bindings,
        policy_version=settings.policy_version,
        policy_digest=policy_digest,
        assertions=tuple(sorted(core_assertions, key=lambda item: item.assertion_id)),
        relations=core_relations,
    )
    decision_log = ReconciliationDecisionLog(
        corpus_id=assembly.corpus_id,
        source_ledger_digest=ledger.digest(),
        policy_digest=policy_digest,
        evidence_decisions=tuple(
            sorted(evidence_decisions, key=lambda item: item.decision_id)
        ),
        assertion_decisions=tuple(
            sorted(assertion_decisions, key=lambda item: item.assertion_id)
        ),
    )
    assertions_by_id = {item.assertion_id: item for item in ledger.assertions}
    conflicts = tuple(
        _critical_conflict(relation, assertions_by_id)
        for relation in core_relations
        if relation.relation_type == "contradicts"
        and relation.score_ppm >= settings.contradiction_threshold_ppm
    )
    conflict_report = CriticalConflictReport(
        corpus_id=assembly.corpus_id,
        source_ledger_digest=ledger.digest(),
        policy_digest=policy_digest,
        conflicts=tuple(sorted(conflicts, key=lambda item: item.conflict_id)),
    )
    return FinalReconciliationResult(
        policy=settings,
        core_snapshot=snapshot,
        decision_log=decision_log,
        conflict_report=conflict_report,
    )


def write_reconciliation(
    result: FinalReconciliationResult,
    output_root: str | Path,
) -> dict[str, str]:
    """Atomically persist content-addressed artifacts plus stable aliases."""

    root = Path(output_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    artifacts = (
        (
            "core_snapshot",
            "core_knowledge_snapshot",
            result.core_snapshot,
            result.core_snapshot.digest(),
        ),
        (
            "decision_log",
            "reconciliation_decisions",
            result.decision_log,
            result.decision_log.digest(),
        ),
        (
            "conflict_report",
            "critical_conflicts",
            result.conflict_report,
            result.conflict_report.digest(),
        ),
    )
    paths: dict[str, str] = {}
    persisted: dict[str, tuple[Path, str]] = {}
    for key, stem, model, digest in artifacts:
        content_path = root / f"{stem}-{digest.removeprefix('sha256:')}.json"
        alias_path = root / f"{stem}.json"
        payload = model.model_dump(mode="json")
        _write_json(payload, content_path)
        _write_json(payload, alias_path)
        paths[key] = str(content_path)
        paths[f"{key}_compat"] = str(alias_path)
        persisted[key] = (content_path, digest)

    manifest = ReconciliationManifest(
        corpus_id=result.core_snapshot.corpus_id,
        source_ledger_digest=result.core_snapshot.source_ledger_digest,
        policy_digest=result.policy.digest(),
        policy=result.policy,
        core_snapshot_path=str(persisted["core_snapshot"][0]),
        core_snapshot_digest=persisted["core_snapshot"][1],
        decision_log_path=str(persisted["decision_log"][0]),
        decision_log_digest=persisted["decision_log"][1],
        conflict_report_path=str(persisted["conflict_report"][0]),
        conflict_report_digest=persisted["conflict_report"][1],
    )
    manifest_path = root / "reconciliation_manifest.json"
    _write_json(manifest.model_dump(mode="json"), manifest_path)
    paths["manifest"] = str(manifest_path)
    return paths


def load_reconciliation(
    manifest_path: str | Path,
    *,
    assembly: CorpusAssemblyResult | None = None,
) -> FinalReconciliationResult:
    """Load artifacts, verify all content digests, and optionally bind assembly."""

    path = Path(manifest_path).expanduser().resolve()
    manifest = ReconciliationManifest.model_validate_json(path.read_text(encoding="utf-8"))
    snapshot = _read_model(
        _resolve_member(path, manifest.core_snapshot_path), CoreKnowledgeSnapshot
    )
    decisions = _read_model(
        _resolve_member(path, manifest.decision_log_path), ReconciliationDecisionLog
    )
    conflicts = _read_model(
        _resolve_member(path, manifest.conflict_report_path), CriticalConflictReport
    )
    expected = (
        (snapshot.digest(), manifest.core_snapshot_digest, "core snapshot"),
        (decisions.digest(), manifest.decision_log_digest, "decision log"),
        (conflicts.digest(), manifest.conflict_report_digest, "conflict report"),
    )
    for actual, declared, label in expected:
        if actual != declared:
            raise ValueError(f"{label} digest does not match reconciliation manifest")
    result = FinalReconciliationResult(
        policy=manifest.policy,
        core_snapshot=snapshot,
        decision_log=decisions,
        conflict_report=conflicts,
    )
    if manifest.policy_digest != result.policy.digest():
        raise ValueError("policy digest does not match reconciliation manifest")
    if manifest.source_ledger_digest != snapshot.source_ledger_digest:
        raise ValueError("source ledger digest does not match reconciliation manifest")
    if manifest.corpus_id != snapshot.corpus_id:
        raise ValueError("corpus ID does not match reconciliation manifest")
    if assembly is not None:
        _validate_assembly_binding(result, assembly)
    return result


def _scientific_chain_errors(evidence: object, delivery: PaperStudyDeliveryV2 | None) -> tuple[str, ...]:
    if delivery is None:
        return ("delivery_missing",)
    claim_ref = getattr(evidence, "claim")
    if claim_ref.packet_digest != delivery.packet_digest:
        return ("packet_digest_mismatch",)
    if getattr(evidence, "admission_status") != delivery.packet.status:
        return ("packet_admission_status_mismatch",)
    matches = []
    for question in delivery.packet.research_questions:
        for unit in question.study_units:
            for claim in unit.claims:
                if claim.claim_id == claim_ref.canonical_id:
                    matches.append((claim, unit))
    if len(matches) != 1:
        return ("claim_missing_or_ambiguous",)
    claim, unit = matches[0]
    errors: list[str] = []
    basis = tuple(claim.inference_basis_ids)
    if not basis:
        errors.append("claim_missing_inference_basis")
    if len(basis) != len(set(basis)):
        errors.append("claim_duplicate_inference_basis")
    if tuple(sorted(set(basis))) != getattr(evidence, "result_ids"):
        errors.append("ledger_result_ids_mismatch")
    results = {item.result_id: item for item in unit.results}
    if set(basis) - set(results):
        errors.append("claim_result_missing")
    provenances = [claim.provenance, *claim.additional_provenance]
    for result_id in basis:
        result = results.get(result_id)
        if result is not None:
            provenances.extend((result.provenance, *result.additional_provenance))
    if any(
        delivery.packet.coverage_ledger.get(provenance.chunk_id) != "extracted"
        for provenance in provenances
    ):
        errors.append("provenance_chunk_not_extracted")
    expected_claim_chunks = tuple(
        sorted({item.chunk_id for item in (claim.provenance, *claim.additional_provenance)})
    )
    if expected_claim_chunks != getattr(evidence, "source_chunk_ids"):
        errors.append("ledger_source_chunks_mismatch")
    return tuple(sorted(set(errors)))


def _validate_assembly(assembly: CorpusAssemblyResult) -> None:
    revisions = tuple(item.revision for item in assembly.ledger_snapshots)
    if revisions != tuple(range(len(revisions))):
        raise ValueError("assembly ledger snapshots must form a complete revision chain")
    for previous, current in zip(assembly.ledger_snapshots, assembly.ledger_snapshots[1:]):
        current.validate_successor_of(previous)
    snapshots = {item.revision: item for item in assembly.ledger_snapshots}
    paper_ids = [item.packet.paper_id for item in assembly.deliveries]
    if len(paper_ids) != len(set(paper_ids)):
        raise ValueError("assembly deliveries contain duplicate paper IDs")
    for delivery in assembly.deliveries:
        revision = delivery.generation_context.ledger_revision
        if revision not in snapshots:
            raise ValueError("delivery references a missing generation ledger")
        delivery.validate_against_ledgers(snapshots[revision], assembly.final_ledger)


def _validate_assembly_binding(
    result: FinalReconciliationResult,
    assembly: CorpusAssemblyResult,
) -> None:
    _validate_assembly(assembly)
    snapshot = result.core_snapshot
    if snapshot.corpus_id != assembly.corpus_id:
        raise ValueError("reconciliation corpus does not match assembly")
    if snapshot.source_ledger_digest != assembly.final_ledger.digest():
        raise ValueError("reconciliation source ledger does not match assembly")
    if snapshot.source_ledger_revision != assembly.final_ledger.revision:
        raise ValueError("reconciliation source revision does not match assembly")
    expected = tuple(
        SourceDeliveryBinding(
            paper_id=item.packet.paper_id,
            delivery_digest=_model_digest(item),
            packet_digest=item.packet_digest,
        )
        for item in sorted(assembly.deliveries, key=lambda value: value.packet.paper_id)
    )
    if snapshot.source_deliveries != expected:
        raise ValueError("reconciliation source deliveries do not match assembly")


def _critical_conflict(
    relation: AssertionRelation,
    assertions: Mapping[str, GlobalAssertion],
) -> CriticalConflict:
    left = assertions[relation.source_assertion_id]
    right = assertions[relation.target_assertion_id]
    return CriticalConflict(
        conflict_id=_stable_id(
            "conflict",
            {"relation_id": relation.relation_id, "score_ppm": relation.score_ppm},
        ),
        relation_id=relation.relation_id,
        source_assertion_id=left.assertion_id,
        target_assertion_id=right.assertion_id,
        score_ppm=relation.score_ppm,
        source_statement=left.preferred_statement,
        target_statement=right.preferred_statement,
    )


def _quality_ppm(value: float) -> int:
    return min(1_000_000, max(0, int(round(value * 1_000_000))))


def _effective_weight(base_ppm: int, quality_ppm: int) -> int:
    return (base_ppm * quality_ppm + 500_000) // 1_000_000


def _model_digest(model: StrictModel) -> str:
    return "sha256:" + _sha256_json(model.model_dump(mode="json"))


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


def _resolve_member(manifest_path: Path, raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = manifest_path.parent / path
    return path.resolve()


def _read_model(path: Path, model_type: type[StrictModel]):
    return model_type.model_validate_json(path.read_text(encoding="utf-8"))
