from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from odracir.paper_study.models import (
    Claim,
    PaperStudyPacketV2,
    Provenance,
    ResearchQuestion,
    ResultObservation,
    StudyUnit,
)
from odracir.paper_study.quality import (
    PacketQualityReport,
    evaluate_packet_quality,
)


FIXTURE = Path(__file__).parent / "fixtures" / "paper_study" / "5-3.packet.json"


def _load_packet() -> PaperStudyPacketV2:
    return PaperStudyPacketV2.model_validate_json(FIXTURE.read_text(encoding="utf-8"))


def _warning_codes(report: PacketQualityReport) -> list[str]:
    return [warning.code for warning in report.warnings]


def _complete_minimal_packet() -> PaperStudyPacketV2:
    provenance = Provenance(
        chunk_id="chunk-1",
        page_start=1,
        page_end=1,
        text_excerpt="The intervention increased the measured response.",
        paraphrased=False,
    )
    result = ResultObservation(
        result_id="R1",
        metric_name="Response",
        value_raw_text="The response increased by 20%.",
        provenance=provenance,
    )
    claim = Claim(
        claim_id="C1",
        statement="The intervention increases the measured response.",
        polarity="positive",
        inference_basis_ids=["R1"],
        provenance=provenance,
    )
    unit = StudyUnit(
        unit_id="SU1",
        name="Intervention experiment",
        experiments_or_tasks=["Compare treated and untreated samples."],
        results=[result],
        claims=[claim],
    )
    return PaperStudyPacketV2(
        paper_id="paper-1",
        research_questions=[
            ResearchQuestion(
                question_id="RQ1",
                statement="Does the intervention alter the response?",
                study_units=[unit],
            )
        ],
        limitations_and_boundaries=[
            "The experiment was restricted to one model system and may not generalize.",
            (
                "The molecular mechanism linking intervention and response remains "
                "unresolved."
            ),
            (
                "Long-term outcomes beyond the reported observation period were not "
                "tested."
            ),
        ],
        coverage_ledger={"chunk-1": "extracted"},
    )


def test_complete_packet_receives_full_score_without_warnings() -> None:
    packet = _complete_minimal_packet()

    report = evaluate_packet_quality(packet)

    assert report.score == 1.0
    assert report.warnings == []
    assert [component.name for component in report.components] == [
        "structural_completeness",
        "provenance_coverage",
        "boundary_richness",
    ]
    assert all(component.score == 1.0 for component in report.components)
    assert sum(component.weight for component in report.components) == 1.0


def test_5_3_fixture_is_high_quality_and_reports_unused_extracted_chunk() -> None:
    packet = _load_packet()

    report = evaluate_packet_quality(packet)

    assert report.score == 0.9879
    assert report.components[0].score == 1.0
    assert report.components[1].passed_checks == 56
    assert report.components[1].total_checks == 58
    assert report.components[2].score == 1.0
    assert _warning_codes(report) == [
        "provenance.paraphrased_only",
        "coverage.unused_extracted_chunks",
    ]
    assert len(report.warnings[0].entity_ids) == 24
    assert report.warnings[1].entity_ids == ["84cbbf8cd9a0f5c7a717"]


def test_quality_warnings_cover_structure_provenance_ledger_and_boundaries() -> None:
    packet = _complete_minimal_packet()
    unit = packet.research_questions[0].study_units[0]
    unit.results[0].metric_name = " "
    unit.results[0].provenance = unit.results[0].provenance.model_copy(
        update={"chunk_id": "unknown", "paraphrased": True}
    )
    unit.claims[0].inference_basis_ids = []
    packet.coverage_ledger = {"chunk-1": "failed"}
    packet.limitations_and_boundaries = ["Limited cohort."]

    report = evaluate_packet_quality(packet)

    assert report.score < 0.7
    assert _warning_codes(report) == [
        "structure.results_without_metrics",
        "structure.claims_without_evidence",
        "coverage.no_extracted_chunks",
        "provenance.paraphrased_only",
        "provenance.untracked_chunks",
        "coverage.failed_chunks",
        "boundaries.too_few",
        "boundaries.shallow",
    ]
    assert report.warnings[0].entity_ids == ["R1"]
    assert report.warnings[1].entity_ids == ["C1"]


def test_evaluation_is_deterministic_and_does_not_mutate_packet() -> None:
    packet = _load_packet()
    before = packet.model_dump_json()

    first = evaluate_packet_quality(packet)
    second = evaluate_packet_quality(packet)

    assert first == second
    assert packet.model_dump_json() == before
    assert packet.quality_score == 1.0


def test_every_additional_provenance_must_be_covered_by_the_ledger() -> None:
    packet = _complete_minimal_packet()
    result = packet.research_questions[0].study_units[0].results[0]
    result.additional_provenance.append(
        result.provenance.model_copy(update={"chunk_id": "unknown-chunk"})
    )

    report = evaluate_packet_quality(packet)

    assert report.score < 1.0
    assert "provenance.untracked_chunks" in _warning_codes(report)
    warning = next(
        warning
        for warning in report.warnings
        if warning.code == "provenance.untracked_chunks"
    )
    assert warning.entity_ids == ["R1"]


def test_blank_boundary_record_is_not_silently_ignored() -> None:
    packet = _complete_minimal_packet()
    packet.limitations_and_boundaries.append("   ")

    report = evaluate_packet_quality(packet)

    assert report.components[2].score == 0.8
    assert "boundaries.blank" in _warning_codes(report)


def test_unselected_source_chunks_remain_in_the_quality_denominator() -> None:
    packet = _complete_minimal_packet()
    packet.coverage_ledger["chunk-2"] = "not_selected"

    report = evaluate_packet_quality(packet)

    assert report.score < 1.0
    assert "coverage.not_selected_chunks" in _warning_codes(report)
    warning = next(
        warning
        for warning in report.warnings
        if warning.code == "coverage.not_selected_chunks"
    )
    assert warning.entity_ids == ["chunk-2"]


def test_quality_report_rejects_undeclared_fields() -> None:
    report = evaluate_packet_quality(_complete_minimal_packet())
    payload = report.model_dump(mode="python")
    payload["unexpected"] = True

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        PacketQualityReport.model_validate(payload)
