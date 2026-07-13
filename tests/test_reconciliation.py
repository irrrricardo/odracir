from __future__ import annotations

import json
from pathlib import Path

import pytest

from odracir.paper_study.assembly import assemble_scheduler_result
from odracir.paper_study.models import (
    Claim,
    PacketStatus,
    PaperStudyPacketV2,
    Provenance,
    ResearchQuestion,
    ResultObservation,
    StudyUnit,
)
from odracir.paper_study.reconciliation import (
    FinalReconciliationPolicy,
    load_reconciliation,
    reconcile_corpus,
    write_reconciliation,
)
from odracir.paper_study.scheduler import (
    PaperIndexEntry,
    run_paper_study_scheduler,
)


def _packet(
    paper_id: str,
    statement: str,
    *,
    status: PacketStatus,
    with_basis: bool = True,
    quality_score: float = 0.9,
) -> PaperStudyPacketV2:
    chunk_id = f"{paper_id}-chunk"
    result_id = f"{paper_id}-result"
    provenance = Provenance(
        chunk_id=chunk_id,
        page_start=1,
        page_end=1,
        text_excerpt=statement,
        paraphrased=True,
    )
    return PaperStudyPacketV2(
        paper_id=paper_id,
        status=status,
        requires_reconciliation=status == "provisional",
        quality_score=quality_score,
        coverage_ledger={chunk_id: "extracted"},
        research_questions=[
            ResearchQuestion(
                question_id=f"{paper_id}-question",
                statement="What changed?",
                study_units=[
                    StudyUnit(
                        unit_id=f"{paper_id}-unit",
                        name="Experiment",
                        experiments_or_tasks=["Measure response"],
                        results=[
                            ResultObservation(
                                result_id=result_id,
                                metric_name="response",
                                value_raw_text="changed",
                                provenance=provenance,
                            )
                        ],
                        claims=[
                            Claim(
                                claim_id=f"{paper_id}-claim",
                                statement=statement,
                                polarity="positive",
                                inference_basis_ids=[result_id] if with_basis else [],
                                provenance=provenance,
                            )
                        ],
                    )
                ],
            )
        ],
    )


def _assembly(*packets: PaperStudyPacketV2):
    packet_by_id = {packet.paper_id: packet for packet in packets}
    scheduler = run_paper_study_scheduler(
        [
            PaperIndexEntry(
                paper_id=packet.paper_id,
                source_path=f"{packet.paper_id}.json",
            )
            for packet in packets
        ],
        lambda entry, _context: packet_by_id[entry.paper_id],
        batch_size=1,
    )
    return assemble_scheduler_result(scheduler, corpus_id="reconciliation-corpus")


def test_accepted_complete_claim_enters_core_and_provisional_is_deferred() -> None:
    assembly = _assembly(
        _packet(
            "paper-accepted",
            "Treatment increases response.",
            status="accepted",
        ),
        _packet(
            "paper-provisional",
            "Another treatment increases response.",
            status="provisional",
        ),
    )
    before = assembly.model_dump_json()

    result = reconcile_corpus(assembly)
    repeated = reconcile_corpus(assembly)

    assert result == repeated
    assert result.core_snapshot.digest() == repeated.core_snapshot.digest()
    assert assembly.model_dump_json() == before
    assert len(result.core_snapshot.assertions) == 1
    core = result.core_snapshot.assertions[0]
    assert core.evidence[0].paper_id == "paper-accepted"
    assert core.evidence[0].admission_status == "accepted"
    assert core.evidence[0].quality_ppm == 900_000
    assert core.evidence[0].effective_weight_ppm == 900_000

    decisions = {
        decision.paper_id: decision
        for decision in result.decision_log.evidence_decisions
    }
    assert decisions["paper-accepted"].disposition == "core_accepted"
    assert decisions["paper-accepted"].reason_codes == (
        "accepted_complete_scientific_chain",
    )
    assert decisions["paper-provisional"].disposition == "deferred"
    assert decisions["paper-provisional"].base_weight_ppm == 350_000
    assert decisions["paper-provisional"].effective_weight_ppm == 315_000
    assert result.conflict_report.conflicts == ()
    assert result.policy.provisional_quality_threshold_ppm == 900_000
    assert result.policy.cross_support_min_independent_papers == 2


def test_incomplete_accepted_claim_is_excluded_instead_of_entering_core() -> None:
    assembly = _assembly(
        _packet(
            "paper-invalid",
            "Treatment changes response.",
            status="accepted",
            with_basis=False,
        )
    )

    result = reconcile_corpus(assembly)

    assert result.core_snapshot.assertions == ()
    evidence = result.decision_log.evidence_decisions[0]
    assertion = result.decision_log.assertion_decisions[0]
    assert evidence.disposition == "excluded_invalid"
    assert "claim_missing_inference_basis" in evidence.reason_codes
    assert evidence.effective_weight_ppm == 0
    assert assertion.disposition == "excluded_invalid"


def test_write_load_round_trip_and_content_tamper_detection(tmp_path: Path) -> None:
    assembly = _assembly(
        _packet(
            "paper-accepted",
            "Treatment increases response.",
            status="accepted",
            quality_score=0.87,
        )
    )
    result = reconcile_corpus(
        assembly,
        policy=FinalReconciliationPolicy(
            provisional_quality_threshold_ppm=910_000,
        ),
    )

    paths = write_reconciliation(result, tmp_path / "reconciliation")

    assert Path(paths["manifest"]).is_file()
    assert Path(paths["core_snapshot_compat"]).name == (
        "core_knowledge_snapshot.json"
    )
    assert result.core_snapshot.digest().removeprefix("sha256:") in Path(
        paths["core_snapshot"]
    ).name
    loaded = load_reconciliation(paths["manifest"], assembly=assembly)
    assert loaded == result

    snapshot_path = Path(paths["core_snapshot"])
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    payload["assertions"][0]["preferred_statement"] = "Tampered statement."
    snapshot_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="core snapshot digest"):
        load_reconciliation(paths["manifest"])
