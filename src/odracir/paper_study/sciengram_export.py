"""Deterministic PaperStudyDeliveryV2 to SciEngramPacket 0.1 export.

The exporter is deliberately a pure adapter.  It does not invoke SciEngram,
perform a second semantic alignment, or mutate an Odracir delivery.  Only
accepted claims admitted to the final reconciliation core receive registered
``result -> claim`` report edges.  All other inference bases remain visible as
non-authoritative relation candidates.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import unicodedata
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from odracir.paper_study.assembly import CorpusAssemblyResult
from odracir.paper_study.models import (
    AlignmentReceipt,
    GlobalStateLedger,
    PaperStudyDeliveryV2,
    Provenance,
    StrictModel,
)


SCIENTGRAM_PACKET_SCHEMA_VERSION = "0.1"
EXPORT_SCHEMA_VERSION = "1.0"
EXPORT_POLICY_VERSION = "odracir-v2-to-sciengram-packet/v1"

ReconciliationDisposition = Literal[
    "core_accepted",
    "deferred",
    "excluded_invalid",
]


class SciEngramExportResult(StrictModel):
    """Paths returned after an atomic deterministic package export."""

    output_root: str = Field(min_length=1)
    manifest_path: str = Field(min_length=1)
    quality_report_path: str = Field(min_length=1)
    packet_paths: dict[str, str]
    crosswalk_paths: dict[str, str]


@dataclass(frozen=True)
class _ClaimDecision:
    paper_id: str
    claim_id: str
    assertion_id: str
    disposition: ReconciliationDisposition
    reason: str
    quality_ppm: int | None = None
    base_weight_ppm: int | None = None
    effective_weight_ppm: int | None = None


@dataclass(frozen=True)
class _ExplicitClaimDecision:
    disposition: ReconciliationDisposition
    reason: str
    assertion_id: str | None
    quality_ppm: int | None
    base_weight_ppm: int | None
    effective_weight_ppm: int | None


@dataclass
class _PacketBuild:
    paper_id: str
    packet: dict[str, Any]
    crosswalk: dict[str, Any]
    counts: dict[str, int]
    quality_row: dict[str, object]


def export_sciengram_packets(
    assembly: CorpusAssemblyResult,
    output_root: str | Path,
    *,
    reconciliation: object | None = None,
) -> SciEngramExportResult:
    """Write one SciEngramPacket 0.1 per delivery and an audited package.

    ``reconciliation`` may be a ``FinalReconciliationResult``.  The adapter is
    intentionally tolerant of that module's serialization boundary: it reads
    ``core_snapshot.assertions`` and claim-level decisions by field name, while
    validating every selected claim against the immutable assembly.  When no
    reconciliation result is supplied, supported final-ledger assertions form
    the conservative core and all other claims are deferred.
    """

    _validate_assembly_receipts(assembly)
    decisions = _resolve_claim_decisions(assembly, reconciliation)
    builds = [
        _build_packet(
            delivery,
            assembly.final_ledger,
            decisions,
            reconciliation=reconciliation,
        )
        for delivery in sorted(
            assembly.deliveries,
            key=lambda item: item.packet.paper_id,
        )
    ]
    if not builds:
        raise ValueError("a SciEngram export requires at least one delivery")

    _validate_corpus_closure(assembly, builds, decisions)
    root = Path(output_root).expanduser().resolve()
    packet_root = root / "packets"
    crosswalk_root = root / "crosswalks"
    packet_records: dict[str, dict[str, object]] = {}
    packet_paths: dict[str, str] = {}
    crosswalk_paths: dict[str, str] = {}

    # Build and validate every artifact before publishing any of them.
    staged: list[tuple[Path, bytes]] = []
    for build in builds:
        packet_path = packet_root / f"{build.paper_id}.json"
        crosswalk_path = crosswalk_root / f"{build.paper_id}.json"
        packet_bytes = _json_bytes(build.packet)
        crosswalk_bytes = _json_bytes(build.crosswalk)
        packet_sha256 = _sha256_bytes(packet_bytes)
        crosswalk_sha256 = _sha256_bytes(crosswalk_bytes)
        staged.extend(
            (
                (packet_path, packet_bytes),
                (crosswalk_path, crosswalk_bytes),
            )
        )
        packet_records[build.paper_id] = {
            "packet_path": packet_path.relative_to(root).as_posix(),
            "packet_sha256": packet_sha256,
            "crosswalk_path": crosswalk_path.relative_to(root).as_posix(),
            "crosswalk_sha256": crosswalk_sha256,
            "counts": dict(sorted(build.counts.items())),
        }
        build.quality_row["packet_sha256"] = packet_sha256
        packet_paths[build.paper_id] = str(packet_path)
        crosswalk_paths[build.paper_id] = str(crosswalk_path)

    quality_path = root / "quality_report.csv"
    quality_bytes = _quality_csv_bytes(builds)
    staged.append((quality_path, quality_bytes))
    aggregate_counts = _sum_counts(builds)
    manifest = {
        "schema_version": EXPORT_SCHEMA_VERSION,
        "export_policy_version": EXPORT_POLICY_VERSION,
        "corpus_id": assembly.corpus_id,
        "source_ledger_digest": assembly.final_ledger.digest(),
        "source_ledger_revision": assembly.final_ledger.revision,
        "reconciliation_policy_digest": _reconciliation_policy_digest(
            reconciliation
        ),
        "sciengram_packet_schema_version": SCIENTGRAM_PACKET_SCHEMA_VERSION,
        "packet_count": len(builds),
        "paper_ids": [build.paper_id for build in builds],
        "quality_report_path": quality_path.relative_to(root).as_posix(),
        "quality_report_sha256": _sha256_bytes(quality_bytes),
        "aggregate_counts": dict(sorted(aggregate_counts.items())),
        "id_count_closure": _corpus_closure_payload(
            assembly,
            builds,
            decisions,
        ),
        "packets": dict(sorted(packet_records.items())),
    }
    manifest_path = root / "export_manifest.json"
    staged.append((manifest_path, _json_bytes(manifest)))
    for path, content in staged:
        _write_bytes_atomic(path, content)

    return SciEngramExportResult(
        output_root=str(root),
        manifest_path=str(manifest_path),
        quality_report_path=str(quality_path),
        packet_paths=dict(sorted(packet_paths.items())),
        crosswalk_paths=dict(sorted(crosswalk_paths.items())),
    )


def export_sciengram_package(
    assembly: CorpusAssemblyResult,
    output_root: str | Path,
    *,
    reconciliation: object | None = None,
) -> SciEngramExportResult:
    """Compatibility alias for :func:`export_sciengram_packets`."""

    return export_sciengram_packets(
        assembly,
        output_root,
        reconciliation=reconciliation,
    )


def _validate_assembly_receipts(assembly: CorpusAssemblyResult) -> None:
    snapshots = {item.revision: item for item in assembly.ledger_snapshots}
    if tuple(sorted(snapshots)) != tuple(range(len(snapshots))):
        raise ValueError("assembly snapshots must form a complete revision chain")
    if assembly.final_ledger.corpus_id != assembly.corpus_id:
        raise ValueError("assembly corpus_id does not match its final ledger")
    seen: set[str] = set()
    for delivery in assembly.deliveries:
        paper_id = delivery.packet.paper_id
        if paper_id in seen:
            raise ValueError(f"duplicate delivery paper_id: {paper_id}")
        seen.add(paper_id)
        revision = delivery.generation_context.ledger_revision
        try:
            generation_ledger = snapshots[revision]
        except KeyError as exc:
            raise ValueError(
                f"delivery {paper_id!r} references missing ledger revision {revision}"
            ) from exc
        delivery.validate_against_ledgers(
            generation_ledger,
            assembly.final_ledger,
        )


def _resolve_claim_decisions(
    assembly: CorpusAssemblyResult,
    reconciliation: object | None,
) -> dict[tuple[str, str], _ClaimDecision]:
    assertion_status = {
        item.assertion_id: item.status for item in assembly.final_ledger.assertions
    }
    explicit_core_ids = _core_assertion_ids(reconciliation)
    if explicit_core_ids is None:
        core_ids = {
            assertion_id
            for assertion_id, status in assertion_status.items()
            if status == "supported"
        }
    else:
        unknown = explicit_core_ids - set(assertion_status)
        if unknown:
            raise ValueError(
                "reconciliation core contains assertions absent from the ledger: "
                f"{tuple(sorted(unknown))!r}"
            )
        core_ids = explicit_core_ids

    explicit = _explicit_decisions(reconciliation)
    result: dict[tuple[str, str], _ClaimDecision] = {}
    for delivery in assembly.deliveries:
        packet = delivery.packet
        alignment_by_claim = {
            item.source.canonical_id: item for item in delivery.alignments
        }
        for _question, _unit, claim, _path in _iter_claims(packet):
            alignment = alignment_by_claim.get(claim.claim_id)
            if alignment is None:
                raise ValueError(
                    f"claim {packet.paper_id}/{claim.claim_id} lacks an alignment receipt"
                )
            key = (packet.paper_id, claim.claim_id)
            provided = explicit.get(key)
            if provided is None:
                if packet.status == "accepted" and alignment.target_assertion_id in core_ids:
                    disposition: ReconciliationDisposition = "core_accepted"
                    reason = "accepted_complete_chain_in_reconciliation_core"
                else:
                    disposition = "deferred"
                    reason = (
                        "source_packet_provisional"
                        if packet.status == "provisional"
                        else "assertion_not_admitted_to_reconciliation_core"
                    )
            else:
                disposition = provided.disposition
                reason = provided.reason
                decision_assertion = provided.assertion_id
                if decision_assertion and decision_assertion != alignment.target_assertion_id:
                    raise ValueError(
                        "reconciliation decision assertion does not match delivery alignment: "
                        f"{key!r}"
                    )
            if disposition == "core_accepted":
                if packet.status != "accepted":
                    raise ValueError("a provisional packet claim cannot enter the core")
                if alignment.target_assertion_id not in core_ids:
                    raise ValueError(
                        "a core_accepted claim must target a reconciliation core assertion"
                    )
            result[key] = _ClaimDecision(
                paper_id=packet.paper_id,
                claim_id=claim.claim_id,
                assertion_id=alignment.target_assertion_id,
                disposition=disposition,
                reason=reason,
                quality_ppm=(provided.quality_ppm if provided is not None else None),
                base_weight_ppm=(
                    provided.base_weight_ppm if provided is not None else None
                ),
                effective_weight_ppm=(
                    provided.effective_weight_ppm if provided is not None else None
                ),
            )
    unknown_explicit = set(explicit) - set(result)
    if unknown_explicit:
        raise ValueError(
            "reconciliation decisions reference unknown claims: "
            f"{tuple(sorted(unknown_explicit))!r}"
        )
    return result


def _core_assertion_ids(reconciliation: object | None) -> set[str] | None:
    if reconciliation is None:
        return None
    core = _field(reconciliation, "core_snapshot")
    if core is None:
        core = _field(reconciliation, "core_knowledge_snapshot")
    if core is None:
        return None
    assertions = _field(core, "assertions")
    if assertions is None:
        raise ValueError("reconciliation core snapshot has no assertions")
    identifiers = {
        str(_field(item, "assertion_id") or "") for item in assertions
    }
    if "" in identifiers:
        raise ValueError("reconciliation core assertion requires assertion_id")
    return identifiers


def _explicit_decisions(
    reconciliation: object | None,
) -> dict[
    tuple[str, str],
    _ExplicitClaimDecision,
]:
    if reconciliation is None:
        return {}
    decision_log = _field(reconciliation, "decision_log")
    raw = _field(decision_log, "evidence_decisions") if decision_log is not None else None
    if raw is None:
        raw = _field(reconciliation, "decisions")
    if raw is None:
        raw = _field(reconciliation, "reconciliation_decisions")
    if raw is None:
        return {}
    result: dict[tuple[str, str], _ExplicitClaimDecision] = {}
    for item in raw:
        paper_id = str(_field(item, "paper_id") or "")
        claim_id = str(
            _field(item, "claim_id")
            or _field(item, "source_claim_id")
            or ""
        )
        disposition = str(_field(item, "disposition") or "")
        if disposition not in {
            "core_accepted",
            "deferred",
            "excluded_invalid",
        }:
            raise ValueError(
                f"unsupported reconciliation disposition: {disposition!r}"
            )
        if not paper_id or not claim_id:
            raise ValueError("a reconciliation decision requires paper_id and claim_id")
        key = (paper_id, claim_id)
        if key in result:
            raise ValueError(f"duplicate reconciliation claim decision: {key!r}")
        reason_value = _field(item, "reason") or _field(item, "reason_code")
        if not reason_value:
            reason_codes = _field(item, "reason_codes")
            if isinstance(reason_codes, Sequence) and not isinstance(
                reason_codes, (str, bytes)
            ):
                reason_value = ",".join(str(value) for value in reason_codes)
        reason = str(reason_value or disposition)
        assertion_id = _field(item, "assertion_id")
        result[key] = _ExplicitClaimDecision(
            disposition=disposition,  # type: ignore[arg-type]
            reason=reason,
            assertion_id=str(assertion_id) if assertion_id else None,
            quality_ppm=_optional_ppm(item, "quality_ppm"),
            base_weight_ppm=_optional_ppm(item, "base_weight_ppm"),
            effective_weight_ppm=_optional_ppm(item, "effective_weight_ppm"),
        )
    return result


def _build_packet(
    delivery: PaperStudyDeliveryV2,
    final_ledger: GlobalStateLedger,
    decisions: Mapping[tuple[str, str], _ClaimDecision],
    *,
    reconciliation: object | None,
) -> _PacketBuild:
    packet = delivery.packet
    paper_id = packet.paper_id
    alignment_by_claim = {
        item.source.canonical_id: item for item in delivery.alignments
    }
    collections: dict[str, list[dict[str, Any]]] = {
        "evidence_spans": [],
        "claims": [],
        "experiments": [],
        "methods": [],
        "datasets": [],
        "metrics": [],
        "results": [],
        "figure_tables": [],
        "limitations": [],
        "negative_results": [],
        "validation_needs": [],
        "relation_candidates": [],
        "edges": [],
    }
    object_crosswalk: list[dict[str, str]] = []
    provenance_crosswalk: list[dict[str, str]] = []
    alignment_crosswalk: list[dict[str, Any]] = []
    result_paths: dict[str, str] = {}
    result_unit_ids: dict[str, str] = {}
    result_evidence: dict[str, list[str]] = {}
    result_citations: dict[str, list[str]] = {}
    claim_paths: dict[str, str] = {}
    claim_evidence: dict[str, list[str]] = {}
    claim_citations: dict[str, list[str]] = {}
    metric_by_key: dict[tuple[str, str], str] = {}
    input_counts: Counter[str] = Counter()

    for question_index, question in enumerate(packet.research_questions):
        question_path = f"$.packet.research_questions[{question_index}]"
        input_counts["research_questions"] += 1
        for unit_index, unit in enumerate(question.study_units):
            unit_path = f"{question_path}.study_units[{unit_index}]"
            input_counts["study_units"] += 1
            method_ids = [item.method_id for item in unit.methods]
            dataset_ids = [item.dataset_id for item in unit.datasets]
            experiment = {
                "experiment_id": unit.unit_id,
                "name": unit.name,
                "purpose": " | ".join(unit.experiments_or_tasks) or unit.name,
                "research_question_id": question.question_id,
                "research_question": question.statement,
                "method_ids": method_ids,
                "dataset_ids": dataset_ids,
                "conditions": list(unit.experiments_or_tasks),
                "artifact_sources": ["odracir_paper_study_v2"],
                "inference": False,
            }
            collections["experiments"].append(experiment)
            object_crosswalk.append(
                _crosswalk(unit_path, "study_unit", "experiments", unit.unit_id)
            )

            for dataset_index, dataset in enumerate(unit.datasets):
                source_path = f"{unit_path}.datasets[{dataset_index}]"
                input_counts["datasets"] += 1
                collections["datasets"].append(
                    {
                        "dataset_id": dataset.dataset_id,
                        "name": dataset.name,
                        "version": dataset.version_or_split or "",
                        "split_or_holdout": dataset.version_or_split or "",
                        "description": dataset.description or "",
                        "artifact_sources": ["odracir_paper_study_v2"],
                        "inference": False,
                    }
                )
                object_crosswalk.append(
                    _crosswalk(
                        source_path,
                        "dataset",
                        "datasets",
                        dataset.dataset_id,
                    )
                )

            for method_index, method in enumerate(unit.methods):
                source_path = f"{unit_path}.methods[{method_index}]"
                input_counts["methods"] += 1
                collections["methods"].append(
                    {
                        "method_id": method.method_id,
                        "name": method.name,
                        "description": method.protocol_description,
                        "protocol": method.protocol_description,
                        "artifact_sources": ["odracir_paper_study_v2"],
                        "inference": False,
                    }
                )
                object_crosswalk.append(
                    _crosswalk(source_path, "method", "methods", method.method_id)
                )

            for span_index, span in enumerate(unit.evidence_spans):
                source_path = f"{unit_path}.evidence_spans[{span_index}]"
                input_counts["evidence_spans"] += 1
                evidence_id = span.span_id
                collections["evidence_spans"].append(
                    _evidence_record(
                        evidence_id=evidence_id,
                        text=span.content,
                        provenance=span.provenance,
                        evidence_type="other",
                    )
                )
                object_crosswalk.append(
                    _crosswalk(
                        source_path,
                        "evidence_span",
                        "evidence_spans",
                        evidence_id,
                    )
                )
                provenance_crosswalk.append(
                    {
                        "source_path": f"{source_path}.provenance",
                        "evidence_id": evidence_id,
                    }
                )

            for result_index, result in enumerate(unit.results):
                source_path = f"{unit_path}.results[{result_index}]"
                input_counts["results"] += 1
                result_paths[result.result_id] = source_path
                result_unit_ids[result.result_id] = unit.unit_id
                evidences, citations = _append_entity_provenance(
                    collections["evidence_spans"],
                    provenance_crosswalk,
                    source_path,
                    result.result_id,
                    "result",
                    (result.provenance, *result.additional_provenance),
                    grounds_experiment_ids=[unit.unit_id],
                    grounds_result_ids=[result.result_id],
                )
                input_counts["provenance_occurrences"] += len(evidences)
                result_evidence[result.result_id] = evidences
                result_citations[result.result_id] = citations
                metric_key = (unit.unit_id, _normalize_key(result.metric_name))
                metric_id = metric_by_key.get(metric_key)
                if metric_id is None:
                    metric_id = _stable_id(
                        "metric",
                        {"unit_id": unit.unit_id, "name": metric_key[1]},
                    )
                    metric_by_key[metric_key] = metric_id
                    collections["metrics"].append(
                        {
                            "metric_id": metric_id,
                            "name": result.metric_name,
                            "artifact_sources": ["odracir_paper_study_v2"],
                            "inference": False,
                        }
                    )
                collections["results"].append(
                    {
                        "result_id": result.result_id,
                        "statement": result.value_raw_text,
                        "description": result.value_raw_text,
                        "value": result.value_raw_text,
                        "quantitative_value": result.quantitative_value,
                        "unit": result.unit,
                        "p_value": result.p_value,
                        "n_sample_size": result.n_sample_size,
                        "experiment_id": unit.unit_id,
                        "dataset_ids": dataset_ids,
                        "method_ids": method_ids,
                        "metric_id": metric_id,
                        "metric": result.metric_name,
                        "conditions": list(unit.experiments_or_tasks),
                        "citations": citations,
                        "evidence_span_ids": evidences,
                        "source_locator": _source_locator(result.provenance),
                        "paraphrased": result.provenance.paraphrased,
                        "quality": {
                            "extraction": _evidence_extraction_quality(packet)
                        },
                        "admission_status": packet.status,
                        "requires_reconciliation": packet.requires_reconciliation,
                        "weight_ppm": _packet_weight_ppm(packet.status),
                        "artifact_sources": ["odracir_paper_study_v2"],
                        "inference": False,
                    }
                )
                object_crosswalk.append(
                    _crosswalk(
                        source_path,
                        "result",
                        "results",
                        result.result_id,
                    )
                )

            for claim_index, claim in enumerate(unit.claims):
                source_path = f"{unit_path}.claims[{claim_index}]"
                input_counts["claims"] += 1
                input_counts["inference_basis_references"] += len(
                    claim.inference_basis_ids
                )
                if len(claim.inference_basis_ids) != len(
                    set(claim.inference_basis_ids)
                ):
                    raise ValueError(
                        f"claim inference_basis_ids contain duplicates: {paper_id}/{claim.claim_id}"
                    )
                missing_basis = set(claim.inference_basis_ids) - set(result_paths)
                if missing_basis:
                    raise ValueError(
                        f"claim has missing result basis: {paper_id}/{claim.claim_id}: "
                        f"{tuple(sorted(missing_basis))!r}"
                    )
                wrong_unit = {
                    result_id
                    for result_id in claim.inference_basis_ids
                    if result_unit_ids[result_id] != unit.unit_id
                }
                if wrong_unit:
                    raise ValueError(
                        f"claim basis crosses StudyUnit boundary: {paper_id}/{claim.claim_id}"
                    )
                decision = decisions[(paper_id, claim.claim_id)]
                alignment = alignment_by_claim[claim.claim_id]
                evidences, citations = _append_entity_provenance(
                    collections["evidence_spans"],
                    provenance_crosswalk,
                    source_path,
                    claim.claim_id,
                    "claim",
                    (claim.provenance, *claim.additional_provenance),
                    supports_claim_ids=(
                        [claim.claim_id]
                        if decision.disposition == "core_accepted"
                        else []
                    ),
                )
                input_counts["provenance_occurrences"] += len(evidences)
                claim_paths[claim.claim_id] = source_path
                claim_evidence[claim.claim_id] = evidences
                claim_citations[claim.claim_id] = citations
                claim_record = {
                    "claim_id": claim.claim_id,
                    "statement": claim.statement,
                    "polarity": claim.polarity,
                    "conditions": list(unit.experiments_or_tasks),
                    "dataset_ids": dataset_ids,
                    "method_ids": method_ids,
                    "inference_basis_ids": list(claim.inference_basis_ids),
                    "citations": citations,
                    "evidence_span_ids": evidences,
                    "paraphrased": claim.provenance.paraphrased,
                    "admission_status": packet.status,
                    "requires_reconciliation": packet.requires_reconciliation,
                    "weight_ppm": _packet_weight_ppm(packet.status),
                    "reconciliation_quality_ppm": decision.quality_ppm,
                    "reconciliation_base_weight_ppm": decision.base_weight_ppm,
                    "reconciliation_effective_weight_ppm": (
                        decision.effective_weight_ppm
                    ),
                    "reconciliation_disposition": decision.disposition,
                    "reconciliation_reason": decision.reason,
                    "target_assertion_id": decision.assertion_id,
                    "alignment_receipt": alignment.model_dump(mode="json"),
                    "quality": {
                        "extraction": _evidence_extraction_quality(packet)
                    },
                    "artifact_sources": ["odracir_paper_study_v2"],
                    "inference": False,
                }
                collections["claims"].append(claim_record)
                object_crosswalk.append(
                    _crosswalk(source_path, "claim", "claims", claim.claim_id)
                )
                alignment_crosswalk.append(
                    {
                        "claim_id": claim.claim_id,
                        "target_assertion_id": decision.assertion_id,
                        "disposition": decision.disposition,
                        "alignment_id": alignment.alignment_id,
                        "alignment_score_ppm": alignment.score_ppm,
                        "evidence_weight_ppm": _packet_weight_ppm(packet.status),
                        "quality_ppm": decision.quality_ppm,
                        "base_weight_ppm": decision.base_weight_ppm,
                        "effective_weight_ppm": decision.effective_weight_ppm,
                    }
                )

    # Results are emitted before claims are traversed, so attach the complete raw
    # reverse crosswalk after every claim basis has been classified.
    related_claims_by_result: dict[str, list[str]] = {
        result_id: [] for result_id in result_paths
    }
    for claim in collections["claims"]:
        for result_id in claim["inference_basis_ids"]:
            related_claims_by_result[result_id].append(claim["claim_id"])
    for result in collections["results"]:
        result["related_claim_ids"] = sorted(
            related_claims_by_result[result["result_id"]]
        )

    _append_structural_edges(collections, paper_id)
    for claim in collections["claims"]:
        claim_id = claim["claim_id"]
        decision = decisions[(paper_id, claim_id)]
        for result_id in claim["inference_basis_ids"]:
            common = {
                "source_id": result_id,
                "source_type": "result",
                "target_id": claim_id,
                "target_type": "claim",
                "relation_type": "supports",
                "citations": sorted(
                    set(result_citations[result_id] + claim_citations[claim_id])
                ),
                "evidence_span_ids": sorted(
                    set(result_evidence[result_id] + claim_evidence[claim_id])
                ),
                "artifact_sources": ["odracir_paper_study_v2"],
                "inference": False,
                "admission_status": packet.status,
                "weight_ppm": _packet_weight_ppm(packet.status),
                "reconciliation_quality_ppm": decision.quality_ppm,
                "reconciliation_base_weight_ppm": decision.base_weight_ppm,
                "reconciliation_effective_weight_ppm": (
                    decision.effective_weight_ppm
                ),
                "reconciliation_disposition": decision.disposition,
                "target_assertion_id": decision.assertion_id,
                "raw_inference_basis_id": result_id,
            }
            if decision.disposition == "core_accepted":
                collections["edges"].append(
                    {
                        "relation_id": _stable_id("rel", common),
                        **common,
                        "confidence_hint": "high",
                    }
                )
            else:
                candidate = {
                    "relation_id": _stable_id("candidate", common),
                    **common,
                    "reason": decision.reason,
                    "target_claim_hint": claim_id,
                }
                collections["relation_candidates"].append(candidate)

    for index, text in enumerate(packet.limitations_and_boundaries, start=1):
        limitation_id = _stable_id(
            "limitation",
            {"paper_id": paper_id, "ordinal": index, "statement": text},
        )
        collections["limitations"].append(
            {
                "limitation_id": limitation_id,
                "statement": text,
                "artifact_sources": ["odracir_paper_study_v2"],
                "inference": False,
            }
        )
    for warning in packet.validation_warnings:
        collections["validation_needs"].append(
            {
                "validation_id": _stable_id(
                    "validation",
                    {"paper_id": paper_id, **warning.model_dump(mode="json")},
                ),
                "message": warning.message,
                "validation_type": warning.code,
                "target_object_id": warning.json_path,
                "severity_hint": "warning",
                "repair": warning.repair,
                "artifact_sources": ["odracir_paper_study_v2"],
            }
        )
    if packet.requires_reconciliation:
        collections["validation_needs"].append(
            {
                "validation_id": _stable_id(
                    "validation",
                    {"paper_id": paper_id, "type": "requires_reconciliation"},
                ),
                "message": "PaperStudyPacketV2 requires final reconciliation.",
                "validation_type": "requires_reconciliation",
                "target_object_id": paper_id,
                "severity_hint": "warning",
                "artifact_sources": ["odracir_paper_study_v2"],
            }
        )

    _sort_collections(collections)
    counts = _validate_packet_closure(
        paper_id,
        collections,
        input_counts,
        object_crosswalk,
        provenance_crosswalk,
    )
    crosswalk = {
        "schema_version": "1.0",
        "paper_id": paper_id,
        "packet_digest": delivery.packet_digest,
        "source_ledger_digest": final_ledger.digest(),
        "objects": sorted(object_crosswalk, key=lambda item: item["source_path"]),
        "provenance": sorted(
            provenance_crosswalk,
            key=lambda item: item["source_path"],
        ),
        "alignments": sorted(
            alignment_crosswalk,
            key=lambda item: item["claim_id"],
        ),
    }
    receipts = {
        "delivery_schema_version": delivery.schema_version,
        "packet_schema_version": packet.schema_version,
        "packet_digest": delivery.packet_digest,
        "generation_context": delivery.generation_context.model_dump(mode="json"),
        "alignments": [item.model_dump(mode="json") for item in delivery.alignments],
        "source_ledger_digest": final_ledger.digest(),
        "source_ledger_revision": final_ledger.revision,
        "reconciliation_policy_digest": _reconciliation_policy_digest(
            reconciliation
        ),
        "crosswalk": crosswalk,
        "coverage_ledger": dict(sorted(packet.coverage_ledger.items())),
        "merge_decisions": [
            item.model_dump(mode="json") for item in packet.merge_decisions
        ],
        "validation_warnings": [
            item.model_dump(mode="json") for item in packet.validation_warnings
        ],
    }
    sciengram_packet: dict[str, Any] = {
        "schema_version": SCIENTGRAM_PACKET_SCHEMA_VERSION,
        "paper_id": paper_id,
        "source_file": packet.metadata.get("source_file", ""),
        "source_sha256": packet.metadata.get("source_sha256", ""),
        "source_artifacts": {"odracir_v2": receipts},
        "paper_profile": {
            "title": packet.metadata.get("title", paper_id),
            "admission_status": packet.status,
            "requires_reconciliation": packet.requires_reconciliation,
            "quality_score": packet.quality_score,
            "metadata": dict(sorted(packet.metadata.items())),
            "research_questions": [
                {
                    "question_id": item.question_id,
                    "statement": item.statement,
                }
                for item in packet.research_questions
            ],
            "reconciliation_disposition_counts": dict(
                sorted(
                    Counter(
                        decisions[(paper_id, claim["claim_id"])].disposition
                        for claim in collections["claims"]
                    ).items()
                )
            ),
        },
        "admission_status": packet.status,
        "requires_reconciliation": packet.requires_reconciliation,
        "quality_score": packet.quality_score,
        "raw_v2_metadata": dict(sorted(packet.metadata.items())),
        "v2_crosswalk": crosswalk,
        **collections,
    }
    dispositions = Counter(
        decisions[(paper_id, claim["claim_id"])].disposition
        for claim in collections["claims"]
    )
    quality_row: dict[str, object] = {
        "paper_id": paper_id,
        "packet_status": packet.status,
        "requires_reconciliation": str(packet.requires_reconciliation).lower(),
        "quality_score": f"{packet.quality_score:.4f}",
        "study_units": counts["experiments"],
        "results": counts["results"],
        "claims": counts["claims"],
        "core_accepted_claims": dispositions["core_accepted"],
        "deferred_claims": dispositions["deferred"],
        "excluded_invalid_claims": dispositions["excluded_invalid"],
        "supports_edges": counts["core_support_edges"],
        "relation_candidates": counts["relation_candidates"],
        "evidence_spans": counts["evidence_spans"],
        "validation_warnings": len(packet.validation_warnings),
        "packet_sha256": "",
    }
    return _PacketBuild(
        paper_id=paper_id,
        packet=sciengram_packet,
        crosswalk=crosswalk,
        counts=counts,
        quality_row=quality_row,
    )


def _append_entity_provenance(
    evidence_records: list[dict[str, Any]],
    crosswalk: list[dict[str, str]],
    entity_path: str,
    entity_id: str,
    entity_type: str,
    provenances: Sequence[Provenance],
    *,
    grounds_experiment_ids: Sequence[str] = (),
    grounds_result_ids: Sequence[str] = (),
    supports_claim_ids: Sequence[str] = (),
) -> tuple[list[str], list[str]]:
    evidence_ids: list[str] = []
    citations: list[str] = []
    for index, provenance in enumerate(provenances):
        field = "provenance" if index == 0 else f"additional_provenance[{index - 1}]"
        source_path = f"{entity_path}.{field}"
        evidence_id = _stable_id(
            "evidence",
            {
                "source_path": source_path,
                "entity_id": entity_id,
                "entity_type": entity_type,
            },
        )
        citation = _citation(provenance)
        evidence_records.append(
            _evidence_record(
                evidence_id=evidence_id,
                text=provenance.text_excerpt,
                provenance=provenance,
                evidence_type=entity_type,
                grounds_experiment_ids=grounds_experiment_ids,
                grounds_result_ids=grounds_result_ids,
                supports_claim_ids=supports_claim_ids,
            )
        )
        crosswalk.append(
            {"source_path": source_path, "evidence_id": evidence_id}
        )
        evidence_ids.append(evidence_id)
        citations.append(citation)
    return evidence_ids, sorted(set(citations))


def _evidence_record(
    *,
    evidence_id: str,
    text: str,
    provenance: Provenance,
    evidence_type: str,
    grounds_experiment_ids: Sequence[str] = (),
    grounds_result_ids: Sequence[str] = (),
    supports_claim_ids: Sequence[str] = (),
) -> dict[str, Any]:
    return {
        "evidence_id": evidence_id,
        "text": text,
        "citation": _citation(provenance),
        "citations": [_citation(provenance)],
        "chunk_id": provenance.chunk_id,
        "page_start": provenance.page_start,
        "page_end": provenance.page_end,
        "source_locator": _source_locator(provenance),
        "paraphrased": provenance.paraphrased,
        "evidence_type": evidence_type,
        "grounds_experiment_ids": sorted(set(grounds_experiment_ids)),
        "grounds_result_ids": sorted(set(grounds_result_ids)),
        "supports_claim_ids": sorted(set(supports_claim_ids)),
        "weakens_claim_ids": [],
        "artifact_sources": ["odracir_paper_study_v2"],
        "inference": False,
    }


def _append_structural_edges(
    collections: dict[str, list[dict[str, Any]]],
    paper_id: str,
) -> None:
    edge_payloads: list[dict[str, Any]] = []
    experiment_by_id = {
        item["experiment_id"]: item for item in collections["experiments"]
    }
    for result in collections["results"]:
        experiment_id = result["experiment_id"]
        edge_payloads.append(
            _edge(
                paper_id,
                experiment_id,
                "experiment",
                result["result_id"],
                "result",
                "produces",
            )
        )
        edge_payloads.append(
            _edge(
                paper_id,
                result["result_id"],
                "result",
                result["metric_id"],
                "metric",
                "measured_by",
            )
        )
    for experiment_id, experiment in experiment_by_id.items():
        for method_id in experiment["method_ids"]:
            edge_payloads.append(
                _edge(
                    paper_id,
                    experiment_id,
                    "experiment",
                    method_id,
                    "method",
                    "uses_method",
                )
            )
        for dataset_id in experiment["dataset_ids"]:
            edge_payloads.append(
                _edge(
                    paper_id,
                    experiment_id,
                    "experiment",
                    dataset_id,
                    "dataset",
                    "uses_data",
                )
            )
    collections["edges"].extend(edge_payloads)


def _edge(
    paper_id: str,
    source_id: str,
    source_type: str,
    target_id: str,
    target_type: str,
    relation_type: str,
) -> dict[str, Any]:
    payload = {
        "source_id": source_id,
        "source_type": source_type,
        "target_id": target_id,
        "target_type": target_type,
        "relation_type": relation_type,
    }
    return {
        "relation_id": _stable_id(
            "rel",
            {"paper_id": paper_id, **payload},
        ),
        **payload,
        "citations": [],
        "evidence_span_ids": [],
        "artifact_sources": ["odracir_paper_study_v2"],
        "inference": False,
    }


def _validate_packet_closure(
    paper_id: str,
    collections: Mapping[str, list[dict[str, Any]]],
    input_counts: Counter[str],
    object_crosswalk: Sequence[dict[str, str]],
    provenance_crosswalk: Sequence[dict[str, str]],
) -> dict[str, int]:
    id_fields = {
        "evidence_spans": "evidence_id",
        "claims": "claim_id",
        "experiments": "experiment_id",
        "methods": "method_id",
        "datasets": "dataset_id",
        "metrics": "metric_id",
        "results": "result_id",
        "figure_tables": "figure_table_id",
        "limitations": "limitation_id",
        "negative_results": "failure_id",
        "validation_needs": "validation_id",
        "relation_candidates": "relation_id",
        "edges": "relation_id",
    }
    ids: dict[str, set[str]] = {}
    for collection, id_field in id_fields.items():
        values = [str(item.get(id_field) or "") for item in collections[collection]]
        if any(not item for item in values):
            raise ValueError(f"{paper_id} {collection} contains an empty identifier")
        if len(values) != len(set(values)):
            raise ValueError(f"{paper_id} {collection} contains duplicate identifiers")
        ids[collection] = set(values)

    endpoint_collections = {
        "claim": "claims",
        "experiment": "experiments",
        "method": "methods",
        "dataset": "datasets",
        "metric": "metrics",
        "result": "results",
    }
    for edge in collections["edges"]:
        source_collection = endpoint_collections.get(str(edge["source_type"]))
        target_collection = endpoint_collections.get(str(edge["target_type"]))
        if source_collection is None or target_collection is None:
            raise ValueError(f"{paper_id} edge has an unsupported endpoint type")
        if str(edge["source_id"]) not in ids[source_collection]:
            raise ValueError(f"{paper_id} edge source endpoint is missing")
        if str(edge["target_id"]) not in ids[target_collection]:
            raise ValueError(f"{paper_id} edge target endpoint is missing")

    result_ids = ids["results"]
    basis_count = 0
    for claim in collections["claims"]:
        bases = [str(item) for item in claim["inference_basis_ids"]]
        if set(bases) - result_ids:
            raise ValueError(f"{paper_id} claim retains an invalid raw inference basis")
        basis_count += len(bases)
    support_edges = [
        item
        for item in collections["edges"]
        if item["relation_type"] == "supports"
        and item["source_type"] == "result"
        and item["target_type"] == "claim"
    ]
    candidate_count = len(collections["relation_candidates"])
    if len(support_edges) + candidate_count != basis_count:
        raise ValueError(
            f"{paper_id} inference basis classification is not one-to-one"
        )
    expected_pairs = {
        (str(claim["claim_id"]), str(result_id))
        for claim in collections["claims"]
        for result_id in claim["inference_basis_ids"]
    }
    classified_pairs = {
        (str(item["target_id"]), str(item["source_id"]))
        for item in (*support_edges, *collections["relation_candidates"])
    }
    if classified_pairs != expected_pairs:
        raise ValueError(f"{paper_id} inference basis pair closure failed")

    expected = {
        "study_units": len(collections["experiments"]),
        "datasets": len(collections["datasets"]),
        "methods": len(collections["methods"]),
        "results": len(collections["results"]),
        "claims": len(collections["claims"]),
    }
    for key, output_count in expected.items():
        if input_counts[key] != output_count:
            raise ValueError(
                f"{paper_id} {key} count closure failed: "
                f"{input_counts[key]} != {output_count}"
            )
    if len(provenance_crosswalk) != input_counts["provenance_occurrences"] + input_counts[
        "evidence_spans"
    ]:
        raise ValueError(f"{paper_id} provenance crosswalk count closure failed")
    if len(collections["evidence_spans"]) != len(provenance_crosswalk):
        raise ValueError(f"{paper_id} evidence span count closure failed")
    if len(object_crosswalk) != sum(
        input_counts[key]
        for key in ("study_units", "datasets", "methods", "results", "claims", "evidence_spans")
    ):
        raise ValueError(f"{paper_id} object crosswalk count closure failed")

    counts = {
        collection: len(records)
        for collection, records in collections.items()
    }
    counts.update(
        {
            "input_inference_basis_references": input_counts[
                "inference_basis_references"
            ],
            "classified_inference_basis_references": len(support_edges)
            + candidate_count,
            "core_support_edges": len(support_edges),
            "crosswalk_objects": len(object_crosswalk),
            "crosswalk_provenance": len(provenance_crosswalk),
        }
    )
    return counts


def _validate_corpus_closure(
    assembly: CorpusAssemblyResult,
    builds: Sequence[_PacketBuild],
    decisions: Mapping[tuple[str, str], _ClaimDecision],
) -> None:
    input_papers = {item.packet.paper_id for item in assembly.deliveries}
    output_papers = {item.paper_id for item in builds}
    if input_papers != output_papers or len(builds) != len(input_papers):
        raise ValueError("delivery-to-packet paper identity closure failed")
    claim_keys = {
        (delivery.packet.paper_id, claim.claim_id)
        for delivery in assembly.deliveries
        for _question, _unit, claim, _path in _iter_claims(delivery.packet)
    }
    if set(decisions) != claim_keys:
        raise ValueError("reconciliation decision-to-claim closure failed")
    expected_claims = len(claim_keys)
    output_claims = sum(item.counts["claims"] for item in builds)
    if output_claims != expected_claims:
        raise ValueError("corpus claim count closure failed")


def _corpus_closure_payload(
    assembly: CorpusAssemblyResult,
    builds: Sequence[_PacketBuild],
    decisions: Mapping[tuple[str, str], _ClaimDecision],
) -> dict[str, object]:
    aggregate = _sum_counts(builds)
    dispositions = Counter(item.disposition for item in decisions.values())
    return {
        "valid": True,
        "input_delivery_count": len(assembly.deliveries),
        "output_packet_count": len(builds),
        "input_claim_count": len(decisions),
        "output_claim_count": aggregate.get("claims", 0),
        "input_inference_basis_reference_count": aggregate.get(
            "input_inference_basis_references", 0
        ),
        "classified_inference_basis_reference_count": aggregate.get(
            "classified_inference_basis_references", 0
        ),
        "core_support_edge_count": aggregate.get("core_support_edges", 0),
        "relation_candidate_count": aggregate.get("relation_candidates", 0),
        "disposition_counts": dict(sorted(dispositions.items())),
    }


def _sum_counts(builds: Sequence[_PacketBuild]) -> dict[str, int]:
    total: Counter[str] = Counter()
    for build in builds:
        total.update(build.counts)
    return dict(total)


def _quality_csv_bytes(builds: Sequence[_PacketBuild]) -> bytes:
    fields = [
        "paper_id",
        "packet_status",
        "requires_reconciliation",
        "quality_score",
        "study_units",
        "results",
        "claims",
        "core_accepted_claims",
        "deferred_claims",
        "excluded_invalid_claims",
        "supports_edges",
        "relation_candidates",
        "evidence_spans",
        "validation_warnings",
        "packet_sha256",
    ]
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for build in builds:
        writer.writerow(build.quality_row)
    return buffer.getvalue().encode("utf-8")


def _sort_collections(collections: dict[str, list[dict[str, Any]]]) -> None:
    id_fields = {
        "evidence_spans": "evidence_id",
        "claims": "claim_id",
        "experiments": "experiment_id",
        "methods": "method_id",
        "datasets": "dataset_id",
        "metrics": "metric_id",
        "results": "result_id",
        "figure_tables": "figure_table_id",
        "limitations": "limitation_id",
        "negative_results": "failure_id",
        "validation_needs": "validation_id",
        "relation_candidates": "relation_id",
        "edges": "relation_id",
    }
    for collection, id_field in id_fields.items():
        collections[collection].sort(key=lambda item: str(item.get(id_field) or ""))


def _iter_claims(packet: object) -> Iterable[tuple[object, object, object, str]]:
    for question_index, question in enumerate(getattr(packet, "research_questions")):
        for unit_index, unit in enumerate(question.study_units):
            for claim_index, claim in enumerate(unit.claims):
                yield (
                    question,
                    unit,
                    claim,
                    f"$.packet.research_questions[{question_index}]"
                    f".study_units[{unit_index}].claims[{claim_index}]",
                )


def _crosswalk(
    source_path: str,
    source_type: str,
    target_collection: str,
    target_id: str,
) -> dict[str, str]:
    return {
        "source_path": source_path,
        "source_type": source_type,
        "target_collection": target_collection,
        "target_id": target_id,
    }


def _source_locator(provenance: Provenance) -> dict[str, object]:
    return {
        "chunk_id": provenance.chunk_id,
        "page_start": provenance.page_start,
        "page_end": provenance.page_end,
    }


def _citation(provenance: Provenance) -> str:
    pages = (
        str(provenance.page_start)
        if provenance.page_start == provenance.page_end
        else f"{provenance.page_start}-{provenance.page_end}"
    )
    return f"[pp.{pages} chunk:{provenance.chunk_id}]"


def _packet_weight_ppm(status: str) -> int:
    return 1_000_000 if status == "accepted" else 350_000


def _evidence_extraction_quality(packet: object) -> float:
    quality = float(getattr(packet, "quality_score"))
    weight = _packet_weight_ppm(str(getattr(packet, "status"))) / 1_000_000
    return round(max(0.0, min(1.0, quality * weight)), 6)


def _normalize_key(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _field(value: object, name: str) -> object | None:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def _optional_ppm(value: object, name: str) -> int | None:
    raw = _field(value, name)
    if raw is None:
        return None
    parsed = int(raw)
    if not 0 <= parsed <= 1_000_000:
        raise ValueError(f"{name} must be between 0 and 1000000")
    return parsed


def _reconciliation_policy_digest(reconciliation: object | None) -> str | None:
    if reconciliation is None:
        return None
    value = _field(reconciliation, "policy_digest")
    if value is None:
        decision_log = _field(reconciliation, "decision_log")
        value = (
            _field(decision_log, "policy_digest")
            if decision_log is not None
            else None
        )
    if value is None:
        core = _field(reconciliation, "core_snapshot")
        value = _field(core, "policy_digest") if core is not None else None
    return str(value) if value else None


def _stable_id(prefix: str, payload: object) -> str:
    digest = hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()
    return f"{prefix}_{digest[:24]}"


def _canonical_json_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _json_bytes(payload: object) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _sha256_bytes(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _write_bytes_atomic(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(content)
    temporary.replace(path)
