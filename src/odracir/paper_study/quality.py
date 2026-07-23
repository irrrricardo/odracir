"""Deterministic quality evaluation for canonical paper-study packets.

The quality gate deliberately uses only packet-local facts.  It performs no
network requests and contains no probabilistic or model-backed decisions, so a
packet always receives the same report regardless of where it is evaluated.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import Field, model_validator

from odracir.paper_study.models import PaperStudyPacketV2, Provenance, StrictModel


QualityComponentName = Literal[
    "structural_completeness",
    "provenance_coverage",
    "boundary_richness",
]
QualityWarningSeverity = Literal["warning"]


class QualityWarning(StrictModel):
    """One stable, machine-readable quality finding."""

    code: str = Field(min_length=1)
    severity: QualityWarningSeverity = "warning"
    message: str = Field(min_length=1)
    entity_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_entity_ids(self) -> QualityWarning:
        if self.entity_ids != sorted(set(self.entity_ids)):
            raise ValueError("entity_ids must be unique and lexically sorted")
        return self


class QualityComponent(StrictModel):
    """Auditable score for one fixed-weight quality dimension."""

    name: QualityComponentName
    weight: float = Field(ge=0.0, le=1.0)
    score: float = Field(ge=0.0, le=1.0)
    weighted_score: float = Field(ge=0.0, le=1.0)
    passed_checks: int = Field(ge=0)
    total_checks: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_check_counts(self) -> QualityComponent:
        if self.passed_checks > self.total_checks:
            raise ValueError("passed_checks must not exceed total_checks")
        expected_score = round(self.passed_checks / self.total_checks, 6)
        if self.score != expected_score:
            raise ValueError("score must equal the passed-check ratio")
        if self.weighted_score != round(self.score * self.weight, 6):
            raise ValueError("weighted_score must equal score multiplied by weight")
        return self


class PacketQualityReport(StrictModel):
    """Strongly typed result returned by :func:`evaluate_packet_quality`."""

    score: float = Field(ge=0.0, le=1.0)
    warnings: list[QualityWarning] = Field(default_factory=list)
    components: list[QualityComponent] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def validate_components(self) -> PacketQualityReport:
        expected_names = [
            "structural_completeness",
            "provenance_coverage",
            "boundary_richness",
        ]
        names = [component.name for component in self.components]
        if names != expected_names:
            raise ValueError(
                "components must use the canonical order: " + ", ".join(expected_names)
            )
        if abs(sum(component.weight for component in self.components) - 1.0) > 1e-9:
            raise ValueError("component weights must sum to 1.0")
        expected_score = round(
            sum(component.weighted_score for component in self.components), 4
        )
        if self.score != expected_score:
            raise ValueError("score must equal the sum of weighted component scores")
        return self


_STRUCTURAL_WEIGHT = 0.50
_PROVENANCE_WEIGHT = 0.35
_BOUNDARY_WEIGHT = 0.15
_SUBSTANTIVE_BOUNDARY_LENGTH = 40


@dataclass(frozen=True)
class _EvidenceEntity:
    entity_id: str
    provenances: tuple[Provenance, ...]


def evaluate_packet_quality(packet: PaperStudyPacketV2) -> PacketQualityReport:
    """Evaluate a packet using deterministic, auditable local rules.

    The function does not mutate ``packet``.  Callers that accept the quality
    result may explicitly copy ``report.score`` into ``packet.quality_score``.
    This keeps evaluation independent from persistence and scheduling policy.
    """

    structural, structural_warnings = _evaluate_structure(packet)
    provenance, provenance_warnings = _evaluate_provenance(packet)
    boundaries, boundary_warnings = _evaluate_boundaries(packet)
    components = [structural, provenance, boundaries]
    score = round(sum(component.weighted_score for component in components), 4)
    return PacketQualityReport(
        score=score,
        warnings=structural_warnings + provenance_warnings + boundary_warnings,
        components=components,
    )


def _evaluate_structure(
    packet: PaperStudyPacketV2,
) -> tuple[QualityComponent, list[QualityWarning]]:
    passed = 0
    total = 1
    warnings: list[QualityWarning] = []

    if packet.research_questions:
        passed += 1
    else:
        warnings.append(
            _warning(
                "structure.no_research_questions",
                "The packet contains no research question.",
            )
        )

    empty_questions: list[str] = []
    missing_tasks: list[str] = []
    units_without_results: list[str] = []
    units_without_claims: list[str] = []
    results_without_metrics: list[str] = []
    results_without_values: list[str] = []
    claims_without_evidence: list[str] = []
    claims_with_invalid_evidence: list[str] = []

    for question in packet.research_questions:
        total += 1
        if question.study_units:
            passed += 1
        else:
            empty_questions.append(question.question_id)

        for unit in question.study_units:
            total += 3
            if any(task.strip() for task in unit.experiments_or_tasks):
                passed += 1
            else:
                missing_tasks.append(unit.unit_id)
            if unit.results:
                passed += 1
            else:
                units_without_results.append(unit.unit_id)
            if unit.claims:
                passed += 1
            else:
                units_without_claims.append(unit.unit_id)

            local_result_ids = {result.result_id for result in unit.results}
            for result in unit.results:
                total += 2
                if result.metric_name.strip():
                    passed += 1
                else:
                    results_without_metrics.append(result.result_id)
                if result.value_raw_text.strip():
                    passed += 1
                else:
                    results_without_values.append(result.result_id)

            for claim in unit.claims:
                total += 2
                basis_ids = claim.inference_basis_ids
                if basis_ids:
                    passed += 1
                else:
                    claims_without_evidence.append(claim.claim_id)
                if (
                    basis_ids
                    and len(basis_ids) == len(set(basis_ids))
                    and set(basis_ids) <= local_result_ids
                ):
                    passed += 1
                elif basis_ids:
                    claims_with_invalid_evidence.append(claim.claim_id)

    warning_specs = (
        (
            "structure.empty_research_questions",
            "Research questions without study units were found.",
            empty_questions,
        ),
        (
            "structure.units_without_tasks",
            "Study units without a concrete experiment or task were found.",
            missing_tasks,
        ),
        (
            "structure.units_without_results",
            "Study units without result observations were found.",
            units_without_results,
        ),
        (
            "structure.units_without_claims",
            "Study units without scientific claims were found.",
            units_without_claims,
        ),
        (
            "structure.results_without_metrics",
            "Result observations with a blank metric name were found.",
            results_without_metrics,
        ),
        (
            "structure.results_without_values",
            "Result observations with a blank raw value were found.",
            results_without_values,
        ),
        (
            "structure.claims_without_evidence",
            "Claims without an inference-basis result were found.",
            claims_without_evidence,
        ),
        (
            "structure.claims_with_invalid_evidence",
            "Claims with duplicate or unresolved inference-basis IDs were found.",
            claims_with_invalid_evidence,
        ),
    )
    warnings.extend(
        _warning(code, message, ids)
        for code, message, ids in warning_specs
        if ids
    )
    component = _component(
        "structural_completeness", _STRUCTURAL_WEIGHT, passed, total
    )
    return component, warnings


def _evaluate_provenance(
    packet: PaperStudyPacketV2,
) -> tuple[QualityComponent, list[QualityWarning]]:
    entities = _evidence_entities(packet)
    extracted_chunks = {
        chunk_id
        for chunk_id, status in packet.coverage_ledger.items()
        if status == "extracted"
    }
    failed_chunks = sorted(
        chunk_id
        for chunk_id, status in packet.coverage_ledger.items()
        if status == "failed"
    )
    not_selected_chunks = sorted(
        chunk_id
        for chunk_id, status in packet.coverage_ledger.items()
        if status == "not_selected"
    )
    cited_chunks: set[str] = set()
    missing: list[str] = []
    paraphrased_only: list[str] = []
    untracked: list[str] = []

    # One ledger-health check, one successful-audit check per ledger entry, two
    # coverage checks per evidence entity, one utilization check per extracted
    # chunk, and one global exact-evidence check. ``irrelevant`` is a valid
    # audited outcome; ``failed`` and ``not_selected`` remain in the denominator
    # but do not pass. A declared paraphrase remains valid provenance, while a packet
    # with at least one exact excerpt earns the final higher-confidence check.
    passed = int(bool(extracted_chunks)) + sum(
        status in {"extracted", "irrelevant"}
        for status in packet.coverage_ledger.values()
    )
    total = (
        2
        + len(packet.coverage_ledger)
        + 2 * len(entities)
        + len(extracted_chunks)
    )
    has_exact_evidence = False

    for entity in entities:
        usable = tuple(
            provenance
            for provenance in entity.provenances
            if _is_usable_provenance(provenance)
        )
        if usable and len(usable) == len(entity.provenances):
            passed += 1
            cited_chunks.update(provenance.chunk_id for provenance in usable)
        else:
            missing.append(entity.entity_id)

        if any(not provenance.paraphrased for provenance in usable):
            has_exact_evidence = True
        elif usable:
            paraphrased_only.append(entity.entity_id)

        if usable and all(
            provenance.chunk_id in extracted_chunks for provenance in usable
        ):
            passed += 1
        elif usable:
            untracked.append(entity.entity_id)

    unused_extracted_chunks = sorted(extracted_chunks - cited_chunks)
    passed += len(extracted_chunks) - len(unused_extracted_chunks)
    passed += int(has_exact_evidence)

    warnings: list[QualityWarning] = []
    if not packet.coverage_ledger:
        warnings.append(
            _warning(
                "coverage.missing_ledger",
                "The packet has no per-chunk coverage ledger.",
            )
        )
    elif not extracted_chunks:
        warnings.append(
            _warning(
                "coverage.no_extracted_chunks",
                "The coverage ledger contains no successfully extracted chunk.",
            )
        )
    if not entities:
        warnings.append(
            _warning(
                "provenance.no_evidence_entities",
                "The packet contains no Result, Claim, or EvidenceSpan to audit.",
            )
        )

    warning_specs = (
        (
            "provenance.missing",
            "Scientific entities without a usable provenance pointer were found.",
            missing,
        ),
        (
            "provenance.paraphrased_only",
            "Scientific entities supported only by paraphrased excerpts were found.",
            paraphrased_only,
        ),
        (
            "provenance.untracked_chunks",
            (
                "Scientific entities without provenance in an extracted ledger "
                "chunk were found."
            ),
            untracked,
        ),
        (
            "coverage.failed_chunks",
            "Chunks marked failed remain in the coverage ledger.",
            failed_chunks,
        ),
        (
            "coverage.not_selected_chunks",
            "Source chunks omitted by the extraction plan were found.",
            not_selected_chunks,
        ),
        (
            "coverage.unused_extracted_chunks",
            "Extracted chunks not referenced by any scientific entity were found.",
            unused_extracted_chunks,
        ),
    )
    warnings.extend(
        _warning(code, message, ids)
        for code, message, ids in warning_specs
        if ids
    )
    component = _component(
        "provenance_coverage", _PROVENANCE_WEIGHT, passed, total
    )
    return component, warnings


def _evaluate_boundaries(
    packet: PaperStudyPacketV2,
) -> tuple[QualityComponent, list[QualityWarning]]:
    blank_count = sum(
        not boundary.strip() for boundary in packet.limitations_and_boundaries
    )
    normalized = [
        " ".join(boundary.split())
        for boundary in packet.limitations_and_boundaries
        if boundary.strip()
    ]
    normalized_keys = [boundary.casefold() for boundary in normalized]
    unique_count = len(set(normalized_keys))
    checks = (
        bool(normalized),
        unique_count >= 3,
        bool(normalized) and unique_count == len(normalized),
        bool(normalized)
        and all(
            len(boundary) >= _SUBSTANTIVE_BOUNDARY_LENGTH
            for boundary in normalized
        ),
        blank_count == 0,
    )
    passed = sum(checks)
    warnings: list[QualityWarning] = []
    if not normalized:
        warnings.append(
            _warning(
                "boundaries.none",
                "No limitation or boundary condition was recorded.",
            )
        )
    else:
        if unique_count < 3:
            warnings.append(
                _warning(
                    "boundaries.too_few",
                    (
                        "Fewer than three distinct limitation or boundary records "
                        "were found."
                    ),
                )
            )
        if unique_count != len(normalized):
            warnings.append(
                _warning(
                    "boundaries.duplicates",
                    "Duplicate limitation or boundary records were found.",
                )
            )
        if any(
            len(boundary) < _SUBSTANTIVE_BOUNDARY_LENGTH for boundary in normalized
        ):
            warnings.append(
                _warning(
                    "boundaries.shallow",
                    (
                        "Boundary records shorter than 40 normalized characters "
                        "were found."
                    ),
                )
            )
    if blank_count:
        warnings.append(
            _warning(
                "boundaries.blank",
                "Blank limitation or boundary records were found.",
            )
        )
    return _component("boundary_richness", _BOUNDARY_WEIGHT, passed, 5), warnings


def _evidence_entities(packet: PaperStudyPacketV2) -> list[_EvidenceEntity]:
    entities: list[_EvidenceEntity] = []
    for question in packet.research_questions:
        for unit in question.study_units:
            entities.extend(
                _EvidenceEntity(
                    entity_id=result.result_id,
                    provenances=(result.provenance, *result.additional_provenance),
                )
                for result in unit.results
            )
            entities.extend(
                _EvidenceEntity(
                    entity_id=claim.claim_id,
                    provenances=(claim.provenance, *claim.additional_provenance),
                )
                for claim in unit.claims
            )
            entities.extend(
                _EvidenceEntity(
                    entity_id=evidence.span_id,
                    provenances=(evidence.provenance,),
                )
                for evidence in unit.evidence_spans
            )
    return sorted(entities, key=lambda entity: entity.entity_id)


def _is_usable_provenance(provenance: Provenance) -> bool:
    return bool(
        provenance.chunk_id.strip()
        and provenance.text_excerpt.strip()
        and provenance.page_start >= 1
        and provenance.page_end >= provenance.page_start
    )


def _component(
    name: QualityComponentName,
    weight: float,
    passed: int,
    total: int,
) -> QualityComponent:
    score = round(passed / total, 6)
    return QualityComponent(
        name=name,
        weight=weight,
        score=score,
        weighted_score=round(score * weight, 6),
        passed_checks=passed,
        total_checks=total,
    )


def _warning(
    code: str,
    message: str,
    entity_ids: list[str] | None = None,
) -> QualityWarning:
    return QualityWarning(
        code=code,
        message=message,
        entity_ids=sorted(set(entity_ids or [])),
    )
