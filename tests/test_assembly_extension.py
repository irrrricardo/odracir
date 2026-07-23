from __future__ import annotations

import json
from pathlib import Path

import pytest

from odracir.paper_study.assembly import (
    CorpusAssemblyResult,
    assemble_scheduler_result,
    extend_corpus_assembly,
    load_corpus_assembly,
    write_corpus_assembly,
)
from odracir.paper_study.models import (
    Claim,
    PaperStudyPacketV2,
    Provenance,
    ResearchQuestion,
    ResultObservation,
    StudyUnit,
)
from odracir.paper_study.scheduler import (
    PaperIndexEntry,
    run_paper_study_scheduler,
)


def _packet(paper_id: str, statement: str) -> PaperStudyPacketV2:
    result_id = f"{paper_id}-result"
    provenance = Provenance(
        chunk_id=f"{paper_id}-chunk",
        page_start=1,
        page_end=1,
        text_excerpt=statement,
        paraphrased=True,
    )
    return PaperStudyPacketV2(
        paper_id=paper_id,
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
                            ),
                        ],
                        claims=[
                            Claim(
                                claim_id=f"{paper_id}-claim",
                                statement=statement,
                                polarity="positive",
                                inference_basis_ids=[result_id],
                                provenance=provenance,
                            ),
                        ],
                    ),
                ],
            ),
        ],
    )


def _schedule(
    packets: tuple[PaperStudyPacketV2, ...],
    *,
    initial_context=None,
):
    packet_by_id = {packet.paper_id: packet for packet in packets}
    return run_paper_study_scheduler(
        tuple(
            PaperIndexEntry(
                paper_id=packet.paper_id,
                source_path=f"{packet.paper_id}.json",
            )
            for packet in packets
        ),
        lambda entry, _context: packet_by_id[entry.paper_id],
        batch_size=1,
        initial_context=initial_context,
    )


def _claim_basis(delivery) -> tuple[str, ...]:
    return delivery.packet.research_questions[0].study_units[0].claims[
        0
    ].inference_basis_ids


def test_load_and_extend_preserve_generation_plane_and_realign_every_claim(
    tmp_path: Path,
) -> None:
    first_scheduler = _schedule(
        (_packet("paper-1", "Treatment increases response at 3 h."),)
    )
    initial = assemble_scheduler_result(first_scheduler, corpus_id="extension-corpus")
    paths = write_corpus_assembly(initial, tmp_path / "initial")
    loaded = load_corpus_assembly(paths["assembly_manifest"])
    assert loaded == initial

    old_delivery = loaded.deliveries[0]
    old_packet_json = old_delivery.packet.model_dump_json()
    old_packet_digest = old_delivery.packet_digest
    old_generation = old_delivery.generation_context
    old_alignment_id = old_delivery.alignments[0].alignment_id
    old_output_digest = old_delivery.alignments[0].output_ledger_digest
    old_basis = _claim_basis(old_delivery)

    appended_scheduler = _schedule(
        (_packet("paper-2", "A distinct perturbation increases viability."),),
        initial_context=first_scheduler.final_context,
    )
    extended = extend_corpus_assembly(loaded, appended_scheduler)

    assert [snapshot.revision for snapshot in extended.ledger_snapshots] == [0, 1, 2]
    assert extended.ledger_snapshots[2].parent_digest == (
        extended.ledger_snapshots[1].digest()
    )
    carried = next(
        delivery
        for delivery in extended.deliveries
        if delivery.packet.paper_id == "paper-1"
    )
    assert carried.packet.model_dump_json() == old_packet_json
    assert carried.packet_digest == old_packet_digest
    assert carried.generation_context == old_generation
    assert _claim_basis(carried) == old_basis
    assert carried.alignments[0].alignment_id != old_alignment_id
    assert carried.alignments[0].output_ledger_digest != old_output_digest
    assert carried.alignments[0].output_ledger_digest == extended.final_ledger.digest()

    snapshots = {
        snapshot.revision: snapshot for snapshot in extended.ledger_snapshots
    }
    for delivery in extended.deliveries:
        assert all(
            alignment.output_ledger_digest == extended.final_ledger.digest()
            for alignment in delivery.alignments
        )
        assert (
            delivery.validate_against_ledgers(
                snapshots[delivery.generation_context.ledger_revision],
                extended.final_ledger,
            )
            is delivery
        )

    extended_paths = write_corpus_assembly(extended, tmp_path / "extended")
    assert load_corpus_assembly(extended_paths["assembly_manifest"]) == extended


def test_extension_rejects_duplicate_successful_paper() -> None:
    scheduler = _schedule((_packet("paper-1", "Treatment increases response."),))
    initial = assemble_scheduler_result(scheduler, corpus_id="duplicate-corpus")
    repeated = _schedule(
        (_packet("paper-1", "Treatment increases response."),),
        initial_context=scheduler.final_context,
    )

    with pytest.raises(ValueError, match="already committed"):
        extend_corpus_assembly(initial, repeated)


def test_extension_rejects_incomplete_prior_successor_chain() -> None:
    scheduler = _schedule(
        (
            _packet("paper-1", "Treatment increases response."),
            _packet("paper-2", "Perturbation increases viability."),
        )
    )
    complete = assemble_scheduler_result(scheduler, corpus_id="broken-chain-corpus")
    broken = CorpusAssemblyResult(
        corpus_id=complete.corpus_id,
        ledger_snapshots=(
            complete.ledger_snapshots[0],
            complete.ledger_snapshots[2],
        ),
        deliveries=complete.deliveries,
    )
    appended = _schedule(
        (_packet("paper-3", "Another intervention increases response."),),
        initial_context=scheduler.final_context,
    )

    with pytest.raises(ValueError, match="complete revision chain"):
        extend_corpus_assembly(broken, appended)


def test_loader_rejects_manifest_with_noncontinuous_snapshot_list(
    tmp_path: Path,
) -> None:
    scheduler = _schedule(
        (
            _packet("paper-1", "Treatment increases response."),
            _packet("paper-2", "Perturbation increases viability."),
        )
    )
    result = assemble_scheduler_result(scheduler, corpus_id="load-chain-corpus")
    paths = write_corpus_assembly(result, tmp_path / "assembly")
    manifest_path = Path(paths["assembly_manifest"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["snapshot_paths"] = [
        manifest["snapshot_paths"][0],
        manifest["snapshot_paths"][2],
    ]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="complete revision chain"):
        load_corpus_assembly(manifest_path)
