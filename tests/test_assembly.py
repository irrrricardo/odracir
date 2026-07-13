from __future__ import annotations

import json
from pathlib import Path

import pytest

from odracir.paper_study.assembly import (
    assemble_scheduler_result,
    write_corpus_assembly,
)
from odracir.paper_study.models import (
    Claim,
    PacketStatus,
    PaperStudyDeliveryV2,
    PaperStudyPacketV2,
    Provenance,
    ResearchQuestion,
    ResultObservation,
    StudyUnit,
)
from odracir.paper_study.scheduler import PaperIndexEntry, run_paper_study_scheduler


def _packet(
    paper_id: str,
    statement: str,
    polarity: str,
    *,
    status: PacketStatus = "accepted",
) -> PaperStudyPacketV2:
    provenance = Provenance(
        chunk_id=f"{paper_id}-chunk",
        page_start=1,
        page_end=1,
        text_excerpt=statement,
        paraphrased=True,
    )
    result_id = f"{paper_id}-result"
    return PaperStudyPacketV2(
        paper_id=paper_id,
        status=status,
        requires_reconciliation=status == "provisional",
        research_questions=[
            ResearchQuestion(
                question_id=f"{paper_id}-question",
                statement="What changed?",
                study_units=[
                    StudyUnit(
                        unit_id=f"{paper_id}-unit",
                        name="Experiment",
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
                                polarity=polarity,
                                inference_basis_ids=[result_id],
                                provenance=provenance,
                            )
                        ],
                    )
                ],
            )
        ],
    )


def test_provisional_only_assertions_remain_unresolved_and_relation_free() -> None:
    packets = {
        "paper-positive": _packet(
            "paper-positive",
            "Treatment increases response at 3 h.",
            "positive",
            status="provisional",
        ),
        "paper-negative": _packet(
            "paper-negative",
            "Treatment decreases response at 3 h.",
            "negative",
            status="provisional",
        ),
    }
    entries = [
        PaperIndexEntry(paper_id=paper_id, source_path=f"{paper_id}.json")
        for paper_id in packets
    ]
    scheduled = run_paper_study_scheduler(
        entries,
        lambda entry, _context: packets[entry.paper_id],
        batch_size=2,
    )

    result = assemble_scheduler_result(scheduled, corpus_id="provisional-corpus")

    assert len(result.final_ledger.assertions) == 2
    assert {
        assertion.status for assertion in result.final_ledger.assertions
    } == {"unresolved"}
    assert result.final_ledger.relations == ()
    assert all(
        evidence.admission_status == "provisional"
        and evidence.weight_ppm == 350_000
        for assertion in result.final_ledger.assertions
        for evidence in assertion.evidence
    )
    commit = next(
        event
        for event in result.final_ledger.events
        if event.event_type == "batch_committed"
    )
    assert {
        outcome["packet_status"] for outcome in commit.payload["paper_outcomes"]
    } == {"provisional"}
    assert all(
        str(outcome["packet_digest"]).startswith("sha256:")
        for outcome in commit.payload["paper_outcomes"]
    )


def test_accepted_evidence_upgrades_unresolved_assertion_with_revision_event() -> None:
    statement = "Treatment increases response at 3 h."
    packets = {
        "paper-1-provisional": _packet(
            "paper-1-provisional",
            statement,
            "positive",
            status="provisional",
        ),
        "paper-2-accepted": _packet(
            "paper-2-accepted",
            statement,
            "positive",
        ),
    }
    entries = [
        PaperIndexEntry(paper_id=paper_id, source_path=f"{paper_id}.json")
        for paper_id in packets
    ]
    scheduled = run_paper_study_scheduler(
        entries,
        lambda entry, _context: packets[entry.paper_id],
        batch_size=1,
    )

    result = assemble_scheduler_result(scheduled, corpus_id="upgrade-corpus")

    assert result.ledger_snapshots[1].assertions[0].status == "unresolved"
    assertion = result.final_ledger.assertions[0]
    assert assertion.status == "supported"
    assert {
        (evidence.admission_status, evidence.weight_ppm)
        for evidence in assertion.evidence
    } == {("provisional", 350_000), ("accepted", 1_000_000)}
    revision_events = [
        event
        for event in result.final_ledger.events
        if event.event_type == "assertion_revised"
    ]
    assert len(revision_events) == 1
    assert revision_events[0].revision == 2
    assert revision_events[0].subject_id == assertion.assertion_id
    assert revision_events[0].payload["previous_status"] == "unresolved"
    assert revision_events[0].payload["status"] == "supported"
    assert revision_events[0].payload["reason"] == "accepted_evidence_admitted"
    assert result.final_ledger.validate_successor_of(result.ledger_snapshots[-2])


def test_provisional_delivery_uses_low_weight_new_assertion_alignment() -> None:
    provisional = _packet(
        "paper-provisional",
        "Treatment increases response.",
        "positive",
        status="provisional",
    )
    accepted = _packet(
        "paper-accepted",
        "A distinct intervention decreases viability.",
        "negative",
    )
    packets = {packet.paper_id: packet for packet in (provisional, accepted)}
    scheduled = run_paper_study_scheduler(
        [
            PaperIndexEntry(paper_id=paper_id, source_path=f"{paper_id}.json")
            for paper_id in packets
        ],
        lambda entry, _context: packets[entry.paper_id],
        batch_size=2,
    )

    result = assemble_scheduler_result(scheduled, corpus_id="alignment-corpus")
    alignments = {
        delivery.packet.paper_id: delivery.alignments[0]
        for delivery in result.deliveries
    }

    assert alignments["paper-provisional"].relation_type == "new_assertion"
    assert alignments["paper-provisional"].score_ppm == 350_000
    assert alignments["paper-accepted"].relation_type == "exact"
    assert alignments["paper-accepted"].score_ppm == 1_000_000


def test_assembly_builds_append_only_ledger_and_separate_receipts(tmp_path: Path) -> None:
    packets = {
        "paper-1": _packet(
            "paper-1", "Treatment increases response at 3 h.", "positive"
        ),
        "paper-2": _packet(
            "paper-2", "Treatment increases response at 6 h.", "positive"
        ),
        "paper-3": _packet(
            "paper-3", "Treatment decreases response at 3 h.", "negative"
        ),
    }
    entries = [
        PaperIndexEntry(paper_id=paper_id, source_path=f"{paper_id}.json")
        for paper_id in packets
    ]
    scheduled = run_paper_study_scheduler(
        entries,
        lambda entry, _context: packets[entry.paper_id],
        batch_size=1,
    )

    result = assemble_scheduler_result(scheduled, corpus_id="corpus-1")

    assert [snapshot.revision for snapshot in result.ledger_snapshots] == [0, 1, 2, 3]
    assert result.final_ledger.validate_successor_of(result.ledger_snapshots[-2])
    assert len(result.final_ledger.assertions) == 3
    assert {relation.relation_type for relation in result.final_ledger.relations} >= {
        "conditioned_on",
        "contradicts",
    }
    assertions = {
        assertion.assertion_id: assertion for assertion in result.final_ledger.assertions
    }
    contradiction = next(
        relation
        for relation in result.final_ledger.relations
        if relation.relation_type == "contradicts"
    )
    assert (
        assertions[contradiction.source_assertion_id].conditions
        == assertions[contradiction.target_assertion_id].conditions
    )
    assert assertions[contradiction.source_assertion_id].status == "contested"
    assert assertions[contradiction.target_assertion_id].status == "contested"
    assert {
        event.subject_id
        for event in result.final_ledger.events
        if event.event_type == "assertion_revised"
    } >= {
        contradiction.source_assertion_id,
        contradiction.target_assertion_id,
    }
    assert all(
        assertions[relation.source_assertion_id].conditions
        != assertions[relation.target_assertion_id].conditions
        for relation in result.final_ledger.relations
        if relation.relation_type == "conditioned_on"
    )
    assert [delivery.generation_context.ledger_revision for delivery in result.deliveries] == [
        0,
        1,
        2,
    ]
    assert all(delivery.alignments for delivery in result.deliveries)
    assert all(
        alignment.output_ledger_digest == result.final_ledger.digest()
        for delivery in result.deliveries
        for alignment in delivery.alignments
    )
    first_delivery = next(
        delivery for delivery in result.deliveries if delivery.packet.paper_id == "paper-1"
    )
    assert (
        first_delivery.generation_context.prompt_projection_digest
        == scheduled.batches[0].input_context.prompt_projection_digest()
    )
    assert (
        first_delivery.generation_context.prompt_projection_digest
        != scheduled.batches[0].input_context.digest()
    )

    paths = write_corpus_assembly(result, tmp_path / "assembly")
    assert Path(paths["ledger"]).is_file()
    assert result.final_ledger.digest().removeprefix("sha256:") in Path(
        paths["ledger"]
    ).name
    assert Path(paths["ledger_compat"]).name == "global_state_ledger.json"
    assert Path(paths["assembly_manifest"]).is_file()
    manifest = json.loads(Path(paths["assembly_manifest"]).read_text(encoding="utf-8"))
    assert manifest["ledger_path"] == paths["ledger"]
    assert manifest["compatibility_ledger_path"] == paths["ledger_compat"]
    content_delivery_path = Path(manifest["delivery_paths"]["paper-1"])
    assert content_delivery_path.is_file()
    assert content_delivery_path.name.startswith("paper-1-")
    assert len(content_delivery_path.stem.removeprefix("paper-1-")) == 64
    assert Path(manifest["compatibility_delivery_paths"]["paper-1"]).name == (
        "paper-1.json"
    )
    delivery_path = Path(paths["delivery:paper-1"])
    assert PaperStudyDeliveryV2.model_validate_json(
        delivery_path.read_text(encoding="utf-8")
    ).packet.paper_id == "paper-1"


def test_batch_commit_binds_failure_and_claimless_packet_content() -> None:
    entry = PaperIndexEntry(paper_id="paper-x", source_path="paper-x.json")

    def failed(message: str):
        def processor(_entry: PaperIndexEntry, _context: object) -> PaperStudyPacketV2:
            raise RuntimeError(message)

        return processor

    failed_a = run_paper_study_scheduler([entry], failed("first failure"), batch_size=1)
    failed_b = run_paper_study_scheduler([entry], failed("different failure"), batch_size=1)
    failed_digest_a = assemble_scheduler_result(
        failed_a, corpus_id="failure-corpus"
    ).final_ledger.digest()
    failed_digest_b = assemble_scheduler_result(
        failed_b, corpus_id="failure-corpus"
    ).final_ledger.digest()
    assert failed_digest_a != failed_digest_b
    failed_commit = next(
        event
        for event in assemble_scheduler_result(
            failed_a, corpus_id="failure-corpus"
        ).final_ledger.events
        if event.event_type == "batch_committed"
    )
    failed_outcome = failed_commit.payload["paper_outcomes"][0]
    assert failed_outcome == {
        "paper_id": "paper-x",
        "source_path": "paper-x.json",
        "batch_number": 1,
        "position_in_batch": 1,
        "status": "failed",
        "input_context_digest": failed_a.batches[0].input_context.digest(),
        "error_type": "RuntimeError",
        "error_message": "first failure",
    }
    assert failed_commit.payload["input_context_digest"] == (
        failed_a.batches[0].input_context.digest()
    )
    assert failed_commit.payload["output_context_digest"] == (
        failed_a.batches[0].output_context.digest()
    )

    claimless_a = PaperStudyPacketV2(paper_id="paper-x", metadata={"version": "a"})
    claimless_b = PaperStudyPacketV2(paper_id="paper-x", metadata={"version": "b"})
    scheduled_a = run_paper_study_scheduler(
        [entry], lambda _entry, _context: claimless_a, batch_size=1
    )
    scheduled_b = run_paper_study_scheduler(
        [entry], lambda _entry, _context: claimless_b, batch_size=1
    )
    claimless_digest_a = assemble_scheduler_result(
        scheduled_a, corpus_id="claimless-corpus"
    ).final_ledger.digest()
    claimless_digest_b = assemble_scheduler_result(
        scheduled_b, corpus_id="claimless-corpus"
    ).final_ledger.digest()
    assert claimless_digest_a != claimless_digest_b
    claimless_commit = next(
        event
        for event in assemble_scheduler_result(
            scheduled_a, corpus_id="claimless-corpus"
        ).final_ledger.events
        if event.event_type == "batch_committed"
    )
    claimless_outcome = claimless_commit.payload["paper_outcomes"][0]
    assert claimless_outcome["status"] == "succeeded"
    assert claimless_outcome["source_path"] == "paper-x.json"
    assert claimless_outcome["position_in_batch"] == 1
    assert claimless_outcome["packet_digest"].startswith("sha256:")


def test_resume_requires_and_uses_initial_ledger() -> None:
    first_packet = _packet(
        "paper-1", "Treatment increases response at 3 h.", "positive"
    )
    first_scheduled = run_paper_study_scheduler(
        [PaperIndexEntry(paper_id="paper-1", source_path="paper-1.json")],
        lambda _entry, _context: first_packet,
        batch_size=1,
    )
    first = assemble_scheduler_result(first_scheduled, corpus_id="resume-corpus")

    second_packet = _packet(
        "paper-2", "Treatment increases response at 6 h.", "positive"
    )
    second_scheduled = run_paper_study_scheduler(
        [PaperIndexEntry(paper_id="paper-2", source_path="paper-2.json")],
        lambda _entry, _context: second_packet,
        batch_size=1,
        initial_context=first_scheduled.final_context,
    )
    with pytest.raises(ValueError, match="requires initial_ledger"):
        assemble_scheduler_result(second_scheduled, corpus_id="resume-corpus")

    resumed = assemble_scheduler_result(
        second_scheduled,
        corpus_id="resume-corpus",
        initial_ledger=first.final_ledger,
    )
    assert [snapshot.revision for snapshot in resumed.ledger_snapshots] == [1, 2]
    assert resumed.final_ledger.parent_digest == first.final_ledger.digest()
    assert resumed.deliveries[0].generation_context.ledger_digest == (
        first.final_ledger.digest()
    )
    assert resumed.deliveries[0].generation_context.included_assertion_ids == (
        first.final_ledger.assertions[0].assertion_id,
    )


def test_assembly_rejects_inconsistent_scheduler_audit_and_is_deterministic() -> None:
    packet = _packet("paper-1", "Treatment increases response.", "positive")
    scheduled = run_paper_study_scheduler(
        [PaperIndexEntry(paper_id="paper-1", source_path="paper-1.json")],
        lambda _entry, _context: packet,
        batch_size=1,
    )
    first = assemble_scheduler_result(scheduled, corpus_id="deterministic-corpus")
    second = assemble_scheduler_result(scheduled, corpus_id="deterministic-corpus")
    assert first.final_ledger.digest() == second.final_ledger.digest()
    assert first.deliveries == second.deliveries

    bad_audit = scheduled.batches[0].papers[0].model_copy(
        update={"input_context_digest": "sha256:not-the-input-context"}
    )
    bad_batch = scheduled.batches[0].model_copy(update={"papers": (bad_audit,)})
    bad_result = scheduled.model_copy(update={"batches": (bad_batch,)})
    with pytest.raises(ValueError, match="input_context_digest"):
        assemble_scheduler_result(bad_result, corpus_id="deterministic-corpus")
