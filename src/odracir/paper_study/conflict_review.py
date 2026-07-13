"""Strongly typed, specification-driven review of critical scientific conflicts.

This module deliberately performs no semantic conflict discovery.  A caller must
provide explicit :class:`ConflictSpec` values identifying the two paper-local
claims to compare.  Resolution then follows the audited delivery alignment into
the final ledger and materializes every claim, basis result, and provenance span
needed for human review.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from odracir.paper_study.assembly import (
    CorpusAssemblyResult,
    load_corpus_assembly,
)
from odracir.paper_study.models import (
    AlignmentRelationType,
    AssertionStatus,
    Claim,
    GlobalAssertion,
    PacketStatus,
    PacketValidationWarning,
    ResultObservation,
    StrictModel,
)


ConflictClassification = Literal[
    "explicit_contradiction",
    "performance_ranking",
    "conditional_tension",
]
ConflictSideName = Literal["a", "b"]
_SHA256_PATTERN = r"^sha256:[0-9a-f]{64}$"


class ClaimSelector(StrictModel):
    """A paper-scoped claim identity supplied by a human or policy layer."""

    model_config = {**StrictModel.model_config, "frozen": True}

    paper_id: str = Field(min_length=1)
    claim_id: str = Field(min_length=1)

    def stable_key(self) -> tuple[str, str]:
        return (self.paper_id, self.claim_id)


class ConflictSpec(StrictModel):
    """Explicit request to resolve one claim pair for critical review.

    Specs contain review semantics, but never infer them.  Corpus-specific specs
    belong in the calling workflow or its configuration, not in this module.
    """

    model_config = {**StrictModel.model_config, "frozen": True}

    conflict_id: str = Field(min_length=1)
    priority: Literal["critical"] = "critical"
    classification: ConflictClassification
    title: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    review_question: str = Field(min_length=1)
    side_a: ClaimSelector
    side_b: ClaimSelector

    @model_validator(mode="after")
    def validate_distinct_sides(self) -> ConflictSpec:
        if self.side_a == self.side_b:
            raise ValueError("a conflict spec must identify two distinct claims")
        return self

    def pair_key(self) -> tuple[tuple[str, str], tuple[str, str]]:
        return tuple(sorted((self.side_a.stable_key(), self.side_b.stable_key())))  # type: ignore[return-value]


class ResolvedConflictSide(StrictModel):
    """One fully resolved paper-local side of a conflict review."""

    model_config = {**StrictModel.model_config, "frozen": True}

    side: ConflictSideName
    selector: ClaimSelector
    research_question_id: str = Field(min_length=1)
    study_unit_id: str = Field(min_length=1)
    packet_digest: str = Field(pattern=_SHA256_PATTERN)
    packet_quality_score: float = Field(ge=0.0, le=1.0)
    packet_status: PacketStatus
    requires_reconciliation: bool
    packet_validation_warnings: tuple[PacketValidationWarning, ...] = ()
    assertion_status: AssertionStatus
    evidence_admission_status: PacketStatus
    evidence_weight_ppm: int = Field(ge=1, le=1_000_000)
    alignment_relation_type: AlignmentRelationType
    alignment_score_ppm: int = Field(ge=0, le=1_000_000)
    assertion: GlobalAssertion
    claim: Claim
    basis_results: tuple[ResultObservation, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_resolved_chain(self) -> ResolvedConflictSide:
        if self.selector.claim_id != self.claim.claim_id:
            raise ValueError("resolved claim does not match its selector")
        if self.assertion_status != self.assertion.status:
            raise ValueError("assertion_status does not match the resolved assertion")
        basis_ids = tuple(result.result_id for result in self.basis_results)
        if basis_ids != tuple(sorted(set(basis_ids))):
            raise ValueError("basis_results must be sorted by unique result_id")
        if set(basis_ids) != set(self.claim.inference_basis_ids):
            raise ValueError("basis_results do not exactly resolve inference_basis_ids")
        if self.requires_reconciliation != (self.packet_status == "provisional"):
            raise ValueError(
                "requires_reconciliation must reflect provisional packet status"
            )
        if self.evidence_admission_status != self.packet_status:
            raise ValueError(
                "ledger evidence admission status must match packet status"
            )
        return self


class CriticalConflict(StrictModel):
    """One materialized, human-reviewable scientific conflict."""

    model_config = {**StrictModel.model_config, "frozen": True}

    conflict_id: str = Field(min_length=1)
    priority: Literal["critical"] = "critical"
    classification: ConflictClassification
    title: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    review_question: str = Field(min_length=1)
    side_a: ResolvedConflictSide
    side_b: ResolvedConflictSide

    @model_validator(mode="after")
    def validate_distinct_assertions(self) -> CriticalConflict:
        if self.side_a.side != "a" or self.side_b.side != "b":
            raise ValueError("conflict sides must retain canonical a/b roles")
        if self.side_a.assertion.assertion_id == self.side_b.assertion.assertion_id:
            raise ValueError("a conflict cannot compare two claims in one assertion")
        return self


class CriticalConflictReport(StrictModel):
    """Content-addressed report suitable for JSON, CSV, and Markdown rendering."""

    model_config = {**StrictModel.model_config, "frozen": True}

    schema_version: Literal["1.0"] = "1.0"
    corpus_id: str = Field(min_length=1)
    ledger_revision: int = Field(ge=0)
    ledger_digest: str = Field(pattern=_SHA256_PATTERN)
    conflicts: tuple[CriticalConflict, ...] = ()
    report_digest: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_stable_report(self) -> CriticalConflictReport:
        conflict_ids = tuple(conflict.conflict_id for conflict in self.conflicts)
        if conflict_ids != tuple(sorted(set(conflict_ids))):
            raise ValueError("conflicts must be sorted by unique conflict_id")
        pair_keys = tuple(
            tuple(
                sorted(
                    (
                        conflict.side_a.selector.stable_key(),
                        conflict.side_b.selector.stable_key(),
                    )
                )
            )
            for conflict in self.conflicts
        )
        if len(pair_keys) != len(set(pair_keys)):
            raise ValueError("the same claim pair cannot appear in multiple conflicts")
        if self.report_digest != _report_digest(
            schema_version=self.schema_version,
            corpus_id=self.corpus_id,
            ledger_revision=self.ledger_revision,
            ledger_digest=self.ledger_digest,
            conflicts=self.conflicts,
        ):
            raise ValueError("report_digest does not match report content")
        return self


class ConflictReviewArtifactPaths(StrictModel):
    """Absolute locations and semantic digest of persisted report artifacts."""

    model_config = {**StrictModel.model_config, "frozen": True}

    report_digest: str = Field(pattern=_SHA256_PATTERN)
    json_path: str = Field(min_length=1)
    csv_path: str = Field(min_length=1)
    markdown_path: str = Field(min_length=1)
    checksum_path: str = Field(min_length=1)


def resolve_critical_conflicts(
    assembly: CorpusAssemblyResult | str | Path,
    specs: Sequence[ConflictSpec],
) -> CriticalConflictReport:
    """Resolve explicit claim pairs through deliveries into the final ledger.

    Missing papers, claims, alignments, assertions, evidence references, and
    inference-basis results are hard failures.  No fuzzy lookup or semantic
    fallback is performed.
    """

    resolved_assembly = (
        assembly
        if isinstance(assembly, CorpusAssemblyResult)
        else load_corpus_assembly(assembly)
    )
    if isinstance(specs, (str, bytes)):
        raise TypeError("specs must be a sequence of ConflictSpec values")
    typed_specs = tuple(specs)
    if any(not isinstance(spec, ConflictSpec) for spec in typed_specs):
        raise TypeError("every conflict specification must be a ConflictSpec")
    _validate_specs(typed_specs)

    deliveries = {
        delivery.packet.paper_id: delivery
        for delivery in resolved_assembly.deliveries
    }
    if len(deliveries) != len(resolved_assembly.deliveries):
        raise ValueError("assembly contains duplicate delivery paper_id values")
    assertions = {
        assertion.assertion_id: assertion
        for assertion in resolved_assembly.final_ledger.assertions
    }
    if len(assertions) != len(resolved_assembly.final_ledger.assertions):
        raise ValueError("final ledger contains duplicate assertion_id values")

    conflicts: list[CriticalConflict] = []
    for spec in sorted(typed_specs, key=lambda item: item.conflict_id):
        side_a = _resolve_side(
            "a", spec.side_a, deliveries=deliveries, assertions=assertions
        )
        side_b = _resolve_side(
            "b", spec.side_b, deliveries=deliveries, assertions=assertions
        )
        conflicts.append(
            CriticalConflict(
                conflict_id=spec.conflict_id,
                priority=spec.priority,
                classification=spec.classification,
                title=spec.title,
                rationale=spec.rationale,
                review_question=spec.review_question,
                side_a=side_a,
                side_b=side_b,
            )
        )

    final_ledger = resolved_assembly.final_ledger
    digest = _report_digest(
        schema_version="1.0",
        corpus_id=resolved_assembly.corpus_id,
        ledger_revision=final_ledger.revision,
        ledger_digest=final_ledger.digest(),
        conflicts=tuple(conflicts),
    )
    return CriticalConflictReport(
        corpus_id=resolved_assembly.corpus_id,
        ledger_revision=final_ledger.revision,
        ledger_digest=final_ledger.digest(),
        conflicts=tuple(conflicts),
        report_digest=digest,
    )


def write_critical_conflicts(
    report: CriticalConflictReport,
    output_root: str | Path,
) -> ConflictReviewArtifactPaths:
    """Write canonical JSON, flattened CSV, Markdown, and SHA-256 checksums."""

    root = Path(output_root).expanduser().resolve()
    json_path = root / "critical_conflicts.json"
    csv_path = root / "critical_conflicts.csv"
    markdown_path = root / "critical_conflicts.md"
    checksum_path = root / "critical_conflicts.sha256"

    payloads = {
        json_path: json.dumps(
            report.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n",
        csv_path: _render_csv(report),
        markdown_path: _render_markdown(report),
    }
    for path, content in payloads.items():
        _write_text(content, path)

    checksum_content = "".join(
        f"{hashlib.sha256(payloads[path].encode('utf-8')).hexdigest()}  {path.name}\n"
        for path in (json_path, csv_path, markdown_path)
    )
    _write_text(checksum_content, checksum_path)
    return ConflictReviewArtifactPaths(
        report_digest=report.report_digest,
        json_path=str(json_path),
        csv_path=str(csv_path),
        markdown_path=str(markdown_path),
        checksum_path=str(checksum_path),
    )


def generate_critical_conflicts(
    assembly: CorpusAssemblyResult | str | Path,
    specs: Sequence[ConflictSpec],
    output_root: str | Path,
) -> tuple[CriticalConflictReport, ConflictReviewArtifactPaths]:
    """Resolve and persist an explicit critical-conflict review in one call."""

    report = resolve_critical_conflicts(assembly, specs)
    return report, write_critical_conflicts(report, output_root)


def _validate_specs(specs: tuple[ConflictSpec, ...]) -> None:
    ids = [spec.conflict_id for spec in specs]
    if len(ids) != len(set(ids)):
        raise ValueError("conflict specs must use unique conflict_id values")
    pair_keys = [spec.pair_key() for spec in specs]
    if len(pair_keys) != len(set(pair_keys)):
        raise ValueError("the same claim pair cannot appear in multiple specs")


def _resolve_side(
    side: ConflictSideName,
    selector: ClaimSelector,
    *,
    deliveries: dict[str, object],
    assertions: dict[str, GlobalAssertion],
) -> ResolvedConflictSide:
    try:
        delivery = deliveries[selector.paper_id]
    except KeyError as exc:
        raise ValueError(
            f"conflict selector references missing paper {selector.paper_id!r}"
        ) from exc

    packet = getattr(delivery, "packet")
    matches: list[tuple[str, str, Claim, tuple[ResultObservation, ...]]] = []
    for question in packet.research_questions:
        for unit in question.study_units:
            matching_claims = [
                claim for claim in unit.claims if claim.claim_id == selector.claim_id
            ]
            for claim in matching_claims:
                matches.append(
                    (
                        question.question_id,
                        unit.unit_id,
                        claim,
                        tuple(unit.results),
                    )
                )
    if not matches:
        raise ValueError(
            "conflict selector references missing claim "
            f"{selector.paper_id!r}/{selector.claim_id!r}"
        )
    if len(matches) != 1:
        raise ValueError(
            "conflict selector resolves ambiguously to multiple packet claims: "
            f"{selector.paper_id!r}/{selector.claim_id!r}"
        )
    question_id, unit_id, claim, unit_results = matches[0]
    if not claim.inference_basis_ids:
        raise ValueError(
            "conflict claim has no inference basis: "
            f"{selector.paper_id!r}/{selector.claim_id!r}"
        )
    if len(claim.inference_basis_ids) != len(set(claim.inference_basis_ids)):
        raise ValueError(
            "conflict claim contains duplicate inference_basis_ids: "
            f"{selector.paper_id!r}/{selector.claim_id!r}"
        )

    result_by_id = {result.result_id: result for result in unit_results}
    if len(result_by_id) != len(unit_results):
        raise ValueError(f"study unit {unit_id!r} contains duplicate result_id values")
    missing_result_ids = tuple(
        sorted(set(claim.inference_basis_ids) - result_by_id.keys())
    )
    if missing_result_ids:
        raise ValueError(
            "conflict claim references missing basis results: "
            f"{selector.paper_id!r}/{selector.claim_id!r}: {missing_result_ids!r}"
        )
    basis_results = tuple(
        result_by_id[result_id] for result_id in sorted(claim.inference_basis_ids)
    )

    alignments = [
        alignment
        for alignment in getattr(delivery, "alignments")
        if alignment.source.entity_type == "claim"
        and alignment.source.paper_id == selector.paper_id
        and alignment.source.canonical_id == selector.claim_id
    ]
    if len(alignments) != 1:
        raise ValueError(
            "conflict claim must resolve through exactly one delivery alignment: "
            f"{selector.paper_id!r}/{selector.claim_id!r}"
        )
    alignment = alignments[0]
    try:
        assertion = assertions[alignment.target_assertion_id]
    except KeyError as exc:
        raise ValueError(
            "conflict alignment references missing final-ledger assertion "
            f"{alignment.target_assertion_id!r}"
        ) from exc

    packet_digest = getattr(delivery, "packet_digest")
    evidence_matches = [
        evidence
        for evidence in assertion.evidence
        if evidence.claim.paper_id == selector.paper_id
        and evidence.claim.canonical_id == selector.claim_id
        and evidence.claim.packet_digest == packet_digest
    ]
    if len(evidence_matches) != 1:
        raise ValueError(
            "resolved assertion must contain exactly one matching claim evidence ref: "
            f"{selector.paper_id!r}/{selector.claim_id!r}"
        )
    evidence = evidence_matches[0]
    expected_result_ids = tuple(sorted(claim.inference_basis_ids))
    if evidence.result_ids != expected_result_ids:
        raise ValueError(
            "ledger evidence result_ids do not match claim inference_basis_ids: "
            f"{selector.paper_id!r}/{selector.claim_id!r}"
        )

    return ResolvedConflictSide(
        side=side,
        selector=selector,
        research_question_id=question_id,
        study_unit_id=unit_id,
        packet_digest=packet_digest,
        packet_quality_score=packet.quality_score,
        packet_status=packet.status,
        requires_reconciliation=packet.requires_reconciliation,
        packet_validation_warnings=tuple(packet.validation_warnings),
        assertion_status=assertion.status,
        evidence_admission_status=evidence.admission_status,
        evidence_weight_ppm=evidence.weight_ppm,
        alignment_relation_type=alignment.relation_type,
        alignment_score_ppm=alignment.score_ppm,
        assertion=assertion,
        claim=claim,
        basis_results=basis_results,
    )


def _report_digest(
    *,
    schema_version: str,
    corpus_id: str,
    ledger_revision: int,
    ledger_digest: str,
    conflicts: tuple[CriticalConflict, ...],
) -> str:
    payload = {
        "schema_version": schema_version,
        "corpus_id": corpus_id,
        "ledger_revision": ledger_revision,
        "ledger_digest": ledger_digest,
        "conflicts": [conflict.model_dump(mode="json") for conflict in conflicts],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _render_csv(report: CriticalConflictReport) -> str:
    fieldnames = [
        "report_digest",
        "conflict_id",
        "priority",
        "classification",
        "title",
        "rationale",
        "review_question",
        "side",
        "paper_id",
        "claim_id",
        "research_question_id",
        "study_unit_id",
        "packet_digest",
        "packet_quality_score",
        "packet_status",
        "requires_reconciliation",
        "assertion_id",
        "assertion_status",
        "evidence_admission_status",
        "evidence_weight_ppm",
        "alignment_relation_type",
        "alignment_score_ppm",
        "result_id",
        "assertion_json",
        "claim_json",
        "result_json",
        "claim_provenance_json",
        "result_provenance_json",
    ]
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    for conflict in report.conflicts:
        for side in (conflict.side_a, conflict.side_b):
            for result in side.basis_results:
                writer.writerow(
                    {
                        "report_digest": report.report_digest,
                        "conflict_id": conflict.conflict_id,
                        "priority": conflict.priority,
                        "classification": conflict.classification,
                        "title": conflict.title,
                        "rationale": conflict.rationale,
                        "review_question": conflict.review_question,
                        "side": side.side,
                        "paper_id": side.selector.paper_id,
                        "claim_id": side.selector.claim_id,
                        "research_question_id": side.research_question_id,
                        "study_unit_id": side.study_unit_id,
                        "packet_digest": side.packet_digest,
                        "packet_quality_score": side.packet_quality_score,
                        "packet_status": side.packet_status,
                        "requires_reconciliation": str(
                            side.requires_reconciliation
                        ).lower(),
                        "assertion_id": side.assertion.assertion_id,
                        "assertion_status": side.assertion_status,
                        "evidence_admission_status": side.evidence_admission_status,
                        "evidence_weight_ppm": side.evidence_weight_ppm,
                        "alignment_relation_type": side.alignment_relation_type,
                        "alignment_score_ppm": side.alignment_score_ppm,
                        "result_id": result.result_id,
                        "assertion_json": _compact_json(side.assertion),
                        "claim_json": _compact_json(side.claim),
                        "result_json": _compact_json(result),
                        "claim_provenance_json": _compact_json(
                            side.claim.provenance
                        ),
                        "result_provenance_json": _compact_json(result.provenance),
                    }
                )
    return stream.getvalue()


def _render_markdown(report: CriticalConflictReport) -> str:
    lines = [
        "# Critical Scientific Conflicts",
        "",
        f"- Corpus: `{_md_cell(report.corpus_id)}`",
        f"- Ledger revision: `{report.ledger_revision}`",
        f"- Ledger digest: `{report.ledger_digest}`",
        f"- Report digest: `{report.report_digest}`",
        f"- Conflict count: `{len(report.conflicts)}`",
        "",
        "The JSON artifact is the authoritative full-fidelity representation.",
        "",
    ]
    for conflict in report.conflicts:
        lines.extend(
            [
                f"## {_md_cell(conflict.conflict_id)} — {_md_cell(conflict.title)}",
                "",
                f"- Classification: `{conflict.classification}`",
                f"- Rationale: {_md_cell(conflict.rationale)}",
                f"- Review question: {_md_cell(conflict.review_question)}",
                "",
            ]
        )
        for side in (conflict.side_a, conflict.side_b):
            lines.extend(
                [
                    f"### Side {side.side.upper()}: `{_md_cell(side.selector.paper_id)}` / `{_md_cell(side.selector.claim_id)}`",
                    "",
                    f"- Packet: `{side.packet_status}`, quality `{side.packet_quality_score:.4f}`, reconciliation `{str(side.requires_reconciliation).lower()}`",
                    f"- Assertion: `{side.assertion.assertion_id}`, status `{side.assertion_status}`, evidence weight `{side.evidence_weight_ppm}` ppm",
                    f"- Assertion statement: {_md_cell(side.assertion.preferred_statement)}",
                    f"- Claim: {_md_cell(side.claim.statement)}",
                    f"- Claim provenance: chunk `{_md_cell(side.claim.provenance.chunk_id)}`, pages `{side.claim.provenance.page_start}–{side.claim.provenance.page_end}`, paraphrased `{str(side.claim.provenance.paraphrased).lower()}` — {_md_cell(side.claim.provenance.text_excerpt)}",
                    "",
                    "| Result | Metric | Value | Provenance |",
                    "|---|---|---|---|",
                ]
            )
            for result in side.basis_results:
                provenance = result.provenance
                lines.append(
                    "| "
                    + " | ".join(
                        (
                            f"`{_md_cell(result.result_id)}`",
                            _md_cell(result.metric_name),
                            _md_cell(result.value_raw_text),
                            _md_cell(
                                f"{provenance.chunk_id} p{provenance.page_start}–{provenance.page_end}; "
                                f"paraphrased={str(provenance.paraphrased).lower()}; "
                                f"{provenance.text_excerpt}"
                            ),
                        )
                    )
                    + " |"
                )
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _compact_json(value: object) -> str:
    model_dump = getattr(value, "model_dump")
    return json.dumps(
        model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _md_cell(value: object) -> str:
    return " ".join(str(value).split()).replace("|", "\\|")


def _write_text(content: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)
