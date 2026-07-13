from __future__ import annotations

import csv
import json
from pathlib import Path

from odracir.paper_study.assembly import assemble_scheduler_result
from odracir.paper_study.models import (
    Claim,
    Dataset,
    EvidenceSpan,
    Method,
    PacketStatus,
    PacketValidationWarning,
    PaperStudyPacketV2,
    Provenance,
    ResearchQuestion,
    ResultObservation,
    StudyUnit,
)
from odracir.paper_study.scheduler import PaperIndexEntry, run_paper_study_scheduler
from odracir.paper_study.reconciliation import reconcile_corpus
from odracir.paper_study.sciengram_export import export_sciengram_packets


def _packet(
    paper_id: str,
    statement: str,
    *,
    status: PacketStatus = "accepted",
    quality_score: float = 0.9,
) -> PaperStudyPacketV2:
    provenance = Provenance(
        chunk_id=f"{paper_id}-chunk-1",
        page_start=2,
        page_end=3,
        text_excerpt=f"Source evidence for {statement}",
        paraphrased=True,
    )
    unit_id = f"{paper_id}-unit-1"
    result_id = f"{paper_id}-result-1"
    return PaperStudyPacketV2(
        paper_id=paper_id,
        status=status,
        requires_reconciliation=status == "provisional",
        metadata={
            "title": f"Title for {paper_id}",
            "source_file": f"{paper_id}.pdf",
            "source_sha256": f"sha256-{paper_id}",
        },
        quality_score=quality_score,
        coverage_ledger={f"{paper_id}-chunk-1": "extracted"},
        limitations_and_boundaries=["The experiment used one cell line."],
        validation_warnings=(
            [
                PacketValidationWarning(
                    code="page_normalized",
                    message="A page locator was normalized.",
                    json_path="/research_questions/0",
                    repair="Converted the locator to an integer range.",
                )
            ]
            if status == "provisional"
            else []
        ),
        research_questions=[
            ResearchQuestion(
                question_id=f"{paper_id}-question-1",
                statement="What changed after perturbation?",
                study_units=[
                    StudyUnit(
                        unit_id=unit_id,
                        name="Primary perturbation experiment",
                        experiments_or_tasks=["CRISPR perturbation at 24 h"],
                        datasets=[
                            Dataset(
                                dataset_id=f"{paper_id}-dataset-1",
                                name="single-cell perturbation data",
                                version_or_split="test",
                            )
                        ],
                        methods=[
                            Method(
                                method_id=f"{paper_id}-method-1",
                                name="prediction model",
                                protocol_description="Fit on the training split.",
                            )
                        ],
                        results=[
                            ResultObservation(
                                result_id=result_id,
                                metric_name="Pearson correlation",
                                value_raw_text="Pearson correlation was 0.82.",
                                quantitative_value=0.82,
                                provenance=provenance,
                            )
                        ],
                        claims=[
                            Claim(
                                claim_id=f"{paper_id}-claim-1",
                                statement=statement,
                                polarity="positive",
                                inference_basis_ids=[result_id],
                                provenance=provenance,
                            )
                        ],
                        evidence_spans=[
                            EvidenceSpan(
                                span_id=f"{paper_id}-span-1",
                                content="An additional verbatim observation.",
                                provenance=provenance,
                            )
                        ],
                    )
                ],
            )
        ],
    )


def _assembly():
    shared = "The perturbation model predicts held-out responses."
    packets = {
        "paper-core": _packet("paper-core", shared),
        "paper-noncore": _packet(
            "paper-noncore",
            "A separate model predicts dose response.",
        ),
        "paper-provisional": _packet(
            "paper-provisional",
            shared,
            status="provisional",
            quality_score=0.7,
        ),
    }
    scheduled = run_paper_study_scheduler(
        [
            PaperIndexEntry(paper_id=paper_id, source_path=f"{paper_id}.json")
            for paper_id in packets
        ],
        lambda entry, _context: packets[entry.paper_id],
        batch_size=3,
    )
    return assemble_scheduler_result(scheduled, corpus_id="export-corpus")


def _load(path: str | Path) -> dict[str, object]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def test_export_maps_v2_entities_and_gates_registered_supports(
    tmp_path: Path,
) -> None:
    assembly = _assembly()
    core_assertion_id = next(
        assertion.assertion_id
        for assertion in assembly.final_ledger.assertions
        if any(item.claim.paper_id == "paper-core" for item in assertion.evidence)
    )
    assertion_by_paper = {
        evidence.claim.paper_id: assertion.assertion_id
        for assertion in assembly.final_ledger.assertions
        for evidence in assertion.evidence
    }
    reconciliation = {
        "core_snapshot": {"assertions": [{"assertion_id": core_assertion_id}]},
        "decision_log": {
            "policy_digest": "sha256:test-reconciliation-policy",
            "evidence_decisions": [
                {
                    "assertion_id": assertion_by_paper["paper-core"],
                    "paper_id": "paper-core",
                    "claim_id": "paper-core-claim-1",
                    "disposition": "core_accepted",
                    "quality_ppm": 900_000,
                    "base_weight_ppm": 1_000_000,
                    "effective_weight_ppm": 900_000,
                    "reason_codes": ["accepted_complete_chain"],
                },
                {
                    "assertion_id": assertion_by_paper["paper-noncore"],
                    "paper_id": "paper-noncore",
                    "claim_id": "paper-noncore-claim-1",
                    "disposition": "deferred",
                    "quality_ppm": 900_000,
                    "base_weight_ppm": 1_000_000,
                    "effective_weight_ppm": 0,
                    "reason_codes": ["not_in_core"],
                },
                {
                    "assertion_id": assertion_by_paper["paper-provisional"],
                    "paper_id": "paper-provisional",
                    "claim_id": "paper-provisional-claim-1",
                    "disposition": "deferred",
                    "quality_ppm": 700_000,
                    "base_weight_ppm": 350_000,
                    "effective_weight_ppm": 245_000,
                    "reason_codes": ["provisional_source"],
                },
            ],
        },
    }

    exported = export_sciengram_packets(
        assembly,
        tmp_path / "export",
        reconciliation=reconciliation,
    )
    packets = {
        paper_id: _load(path) for paper_id, path in exported.packet_paths.items()
    }
    core = packets["paper-core"]
    noncore = packets["paper-noncore"]
    provisional = packets["paper-provisional"]

    assert core["schema_version"] == "0.1"
    assert len(core["experiments"]) == 1
    assert len(core["methods"]) == 1
    assert len(core["datasets"]) == 1
    assert len(core["metrics"]) == 1
    assert len(core["results"]) == 1
    assert len(core["claims"]) == 1
    assert {edge["relation_type"] for edge in core["edges"]} == {
        "produces",
        "uses_method",
        "uses_data",
        "measured_by",
        "supports",
    }
    support = next(edge for edge in core["edges"] if edge["relation_type"] == "supports")
    assert support["source_id"] == "paper-core-result-1"
    assert support["target_id"] == "paper-core-claim-1"
    assert support["reconciliation_disposition"] == "core_accepted"
    assert support["reconciliation_effective_weight_ppm"] == 900_000
    assert core["relation_candidates"] == []

    # Accepted evidence outside the reconciliation core and every provisional
    # inference basis remain inspectable, but cannot become registered belief edges.
    for packet, expected_weight in ((noncore, 1_000_000), (provisional, 350_000)):
        assert not any(edge["relation_type"] == "supports" for edge in packet["edges"])
        assert len(packet["relation_candidates"]) == 1
        assert packet["relation_candidates"][0]["weight_ppm"] == expected_weight
        claim = packet["claims"][0]
        assert claim["inference_basis_ids"] == [
            f"{packet['paper_id']}-result-1"
        ]
        assert claim["reconciliation_disposition"] == "deferred"
        claim_evidence_ids = set(claim["evidence_span_ids"])
        claim_evidence = [
            item for item in packet["evidence_spans"]
            if item["evidence_id"] in claim_evidence_ids
        ]
        assert claim_evidence
        assert all(item["supports_claim_ids"] == [] for item in claim_evidence)

    source_delivery = next(
        item for item in assembly.deliveries if item.packet.paper_id == "paper-provisional"
    )
    receipts = provisional["source_artifacts"]["odracir_v2"]
    assert receipts["generation_context"] == source_delivery.generation_context.model_dump(
        mode="json"
    )
    assert receipts["alignments"] == [
        item.model_dump(mode="json") for item in source_delivery.alignments
    ]
    assert provisional["admission_status"] == "provisional"
    assert provisional["requires_reconciliation"] is True
    assert provisional["claims"][0]["weight_ppm"] == 350_000
    assert provisional["claims"][0]["reconciliation_quality_ppm"] == 700_000
    assert (
        provisional["claims"][0]["reconciliation_effective_weight_ppm"]
        == 245_000
    )
    assert provisional["validation_needs"]
    assert provisional["v2_crosswalk"] == receipts["crosswalk"]

    manifest = _load(exported.manifest_path)
    assert manifest["packet_count"] == 3
    assert manifest["id_count_closure"] == {
        "valid": True,
        "input_delivery_count": 3,
        "output_packet_count": 3,
        "input_claim_count": 3,
        "output_claim_count": 3,
        "input_inference_basis_reference_count": 3,
        "classified_inference_basis_reference_count": 3,
        "core_support_edge_count": 1,
        "relation_candidate_count": 2,
        "disposition_counts": {"core_accepted": 1, "deferred": 2},
    }
    with Path(exported.quality_report_path).open(newline="", encoding="utf-8") as handle:
        rows = {row["paper_id"]: row for row in csv.DictReader(handle)}
    assert rows["paper-core"]["supports_edges"] == "1"
    assert rows["paper-noncore"]["relation_candidates"] == "1"
    assert rows["paper-provisional"]["packet_status"] == "provisional"


def test_export_is_byte_deterministic(tmp_path: Path) -> None:
    assembly = _assembly()
    first = export_sciengram_packets(assembly, tmp_path / "first")
    second = export_sciengram_packets(assembly, tmp_path / "second")

    assert Path(first.manifest_path).read_bytes() == Path(second.manifest_path).read_bytes()
    assert Path(first.quality_report_path).read_bytes() == Path(
        second.quality_report_path
    ).read_bytes()
    for paper_id in first.packet_paths:
        assert Path(first.packet_paths[paper_id]).read_bytes() == Path(
            second.packet_paths[paper_id]
        ).read_bytes()
        assert Path(first.crosswalk_paths[paper_id]).read_bytes() == Path(
            second.crosswalk_paths[paper_id]
        ).read_bytes()


def test_export_accepts_final_reconciliation_result_without_an_adapter(
    tmp_path: Path,
) -> None:
    assembly = _assembly()
    reconciliation = reconcile_corpus(assembly)

    exported = export_sciengram_packets(
        assembly,
        tmp_path / "actual-reconciliation",
        reconciliation=reconciliation,
    )
    manifest = _load(exported.manifest_path)

    assert manifest["reconciliation_policy_digest"] == reconciliation.policy.digest()
    assert manifest["id_count_closure"]["core_support_edge_count"] == 2
    assert manifest["id_count_closure"]["relation_candidate_count"] == 1
    provisional = _load(exported.packet_paths["paper-provisional"])
    decision = next(
        item
        for item in reconciliation.decision_log.evidence_decisions
        if item.paper_id == "paper-provisional"
    )
    assert provisional["claims"][0]["reconciliation_effective_weight_ppm"] == (
        decision.effective_weight_ppm
    )
