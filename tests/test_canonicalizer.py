from __future__ import annotations

from collections import Counter
import json
from pathlib import Path

from odracir.paper_study.canonicalization import (
    apply_canonicalization_plan,
    complete_link_clusters,
    extract_protected_conditions,
    normalize_scientific_text,
    plan_canonicalization,
)
from odracir.paper_study.models import PaperStudyPacketV2, Provenance


FIXTURE = Path(__file__).parent / "fixtures" / "paper_study" / "5-3.packet.json"


def _load_packet() -> PaperStudyPacketV2:
    return PaperStudyPacketV2.model_validate_json(FIXTURE.read_text(encoding="utf-8"))


def _key_map(packet: PaperStudyPacketV2) -> dict[tuple[str, str], tuple[str, str]]:
    plan = plan_canonicalization(packet)
    return {
        (record.ref.entity_type, record.ref.source_entity_id): (
            record.key.digest,
            record.key.canonical_id,
        )
        for record in plan.keyed_entities
    }


def _canonical_id(plan, entity_type: str, source_id: str) -> str:
    matches = [
        rewrite.canonical_id
        for rewrite in plan.id_rewrites
        if rewrite.source.entity_type == entity_type
        and rewrite.source.source_entity_id == source_id
    ]
    assert len(matches) == 1
    return matches[0]


def _find_unit(packet: PaperStudyPacketV2, unit_id: str):
    matches = [
        unit
        for question in packet.research_questions
        for unit in question.study_units
        if unit.unit_id == unit_id
    ]
    assert len(matches) == 1
    return matches[0]


def _provenance_set(*groups: list[Provenance]) -> set[str]:
    return {
        json.dumps(
            provenance.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        for group in groups
        for provenance in group
    }


def _assert_reference_integrity(packet: PaperStudyPacketV2) -> None:
    unit_ids: set[str] = set()
    result_ids: set[str] = set()
    claim_ids: set[str] = set()
    for question in packet.research_questions:
        for unit in question.study_units:
            assert unit.unit_id not in unit_ids
            unit_ids.add(unit.unit_id)
            local_results = {result.result_id for result in unit.results}
            assert len(local_results) == len(unit.results)
            assert not (local_results & result_ids)
            result_ids.update(local_results)
            local_claims = {claim.claim_id for claim in unit.claims}
            assert len(local_claims) == len(unit.claims)
            assert not (local_claims & claim_ids)
            claim_ids.update(local_claims)
            for claim in unit.claims:
                assert set(claim.inference_basis_ids) <= local_results


def _packet_with_isomorphic_restatements() -> PaperStudyPacketV2:
    packet = _load_packet().model_copy(deep=True)
    unit = packet.research_questions[0].study_units[1]
    source_result = next(result for result in unit.results if result.result_id == "R8")
    source_claim = next(claim for claim in unit.claims if claim.claim_id == "C4")
    shared_result_provenance = source_result.provenance.model_copy(
        update={"chunk_id": "synthetic-shared-result-provenance"}
    )
    source_result_additional = source_result.provenance.model_copy(
        update={"chunk_id": "synthetic-source-result-additional"}
    )
    restated_result_provenance = source_result.provenance.model_copy(
        update={"chunk_id": "synthetic-restatement-result-primary"}
    )
    restated_result_additional = source_result.provenance.model_copy(
        update={"chunk_id": "synthetic-restatement-result-additional"}
    )
    source_result.additional_provenance = [
        source_result_additional,
        shared_result_provenance,
    ]
    shared_claim_provenance = source_claim.provenance.model_copy(
        update={"chunk_id": "synthetic-shared-claim-provenance"}
    )
    source_claim_additional = source_claim.provenance.model_copy(
        update={"chunk_id": "synthetic-source-claim-additional"}
    )
    restated_claim_provenance = source_claim.provenance.model_copy(
        update={"chunk_id": "synthetic-restatement-claim-primary"}
    )
    restated_claim_additional = source_claim.provenance.model_copy(
        update={"chunk_id": "synthetic-restatement-claim-additional"}
    )
    source_claim.additional_provenance = [
        source_claim_additional,
        shared_claim_provenance,
    ]
    unit.results.append(
        source_result.model_copy(
            deep=True,
            update={
                "result_id": "R8_RESTATEMENT",
                "value_raw_text": source_result.value_raw_text.upper(),
                "provenance": restated_result_provenance,
                "additional_provenance": [
                    restated_result_additional,
                    shared_result_provenance,
                ],
            },
        )
    )
    unit.claims.append(
        source_claim.model_copy(
            deep=True,
            update={
                "claim_id": "C4_RESTATEMENT",
                "statement": source_claim.statement.upper(),
                "inference_basis_ids": ["R8_RESTATEMENT"],
                "provenance": restated_claim_provenance,
                "additional_provenance": [
                    restated_claim_additional,
                    shared_claim_provenance,
                ],
            },
        )
    )
    return packet


def _packet_with_duplicate_study_unit() -> PaperStudyPacketV2:
    packet = _load_packet().model_copy(deep=True)
    question = packet.research_questions[0]
    source = next(unit for unit in question.study_units if unit.unit_id == "SU2")
    duplicate = source.model_copy(deep=True)
    duplicate.unit_id = "SU2_COPY"
    result_ids: dict[str, str] = {}
    for result in duplicate.results:
        old_id = result.result_id
        result.result_id = f"{old_id}_COPY"
        result_ids[old_id] = result.result_id
        result.provenance = result.provenance.model_copy(
            update={"chunk_id": f"synthetic-unit-copy-{old_id}"}
        )
    for claim in duplicate.claims:
        old_id = claim.claim_id
        claim.claim_id = f"{old_id}_COPY"
        claim.inference_basis_ids = [
            result_ids[result_id] for result_id in claim.inference_basis_ids
        ]
        claim.provenance = claim.provenance.model_copy(
            update={"chunk_id": f"synthetic-unit-copy-{old_id}"}
        )
    question.study_units.append(duplicate)
    return packet


def test_zero_false_merges_for_5_3_packet() -> None:
    packet = _load_packet()
    plan = plan_canonicalization(packet)

    counts = Counter(record.ref.entity_type for record in plan.keyed_entities)
    assert counts == {"study_unit": 4, "result": 14, "claim": 6}
    assert plan.merge_cluster_count == 0
    assert all(len(cluster.members) == 1 for cluster in plan.clusters)
    assert packet.merge_decisions == []

    canonical = apply_canonicalization_plan(packet, plan)
    canonical_counts = Counter(
        entity_type
        for question in canonical.research_questions
        for unit in question.study_units
        for entity_type in (
            ["study_unit"]
            + ["result"] * len(unit.results)
            + ["claim"] * len(unit.claims)
        )
    )
    assert canonical_counts == counts
    assert canonical.merge_decisions == []
    assert all(
        unit.unit_id.startswith("su_")
        and all(result.result_id.startswith("res_") for result in unit.results)
        and all(claim.claim_id.startswith("clm_") for claim in unit.claims)
        for question in canonical.research_questions
        for unit in question.study_units
    )
    _assert_reference_integrity(canonical)
    PaperStudyPacketV2.model_validate(canonical.model_dump(mode="python"))

    conditions = extract_protected_conditions(
        "At E14.5, 3 h compression was sufficient, but YAP was not increased."
    )
    condition_pairs = {(condition.kind, condition.value) for condition in conditions}
    assert ("development_stage", "e14.5") in condition_pairs
    assert ("time", "3 h") in condition_pairs
    assert ("modality", "sufficient") in condition_pairs
    assert ("negation", "not") in condition_pairs


def test_isomorphic_restatements_are_automatically_merged() -> None:
    packet = _packet_with_isomorphic_restatements()
    plan = plan_canonicalization(packet)

    duplicate_clusters = [cluster for cluster in plan.clusters if len(cluster.members) > 1]
    assert Counter(cluster.entity_type for cluster in duplicate_clusters) == {
        "result": 1,
        "claim": 1,
    }
    canonical_unit_id = _canonical_id(plan, "study_unit", "SU2")
    canonical_result_id = _canonical_id(plan, "result", "R8")
    canonical_claim_id = _canonical_id(plan, "claim", "C4")
    assert canonical_result_id == _canonical_id(plan, "result", "R8_RESTATEMENT")
    assert canonical_claim_id == _canonical_id(plan, "claim", "C4_RESTATEMENT")

    source_unit = next(
        unit
        for question in packet.research_questions
        for unit in question.study_units
        if unit.unit_id == "SU2"
    )
    source_results = [
        result
        for result in source_unit.results
        if result.result_id in {"R8", "R8_RESTATEMENT"}
    ]
    source_claims = [
        claim
        for claim in source_unit.claims
        if claim.claim_id in {"C4", "C4_RESTATEMENT"}
    ]

    canonical = apply_canonicalization_plan(packet, plan)
    unit = _find_unit(canonical, canonical_unit_id)
    assert len(unit.results) == 4
    assert len(unit.claims) == 2
    merged_result = next(
        result for result in unit.results if result.result_id == canonical_result_id
    )
    merged_claim = next(
        claim for claim in unit.claims if claim.claim_id == canonical_claim_id
    )
    assert merged_claim.inference_basis_ids == [canonical_result_id]
    assert _provenance_set(
        [merged_result.provenance], merged_result.additional_provenance
    ) == _provenance_set(
        *(
            [result.provenance, *result.additional_provenance]
            for result in source_results
        )
    )
    assert _provenance_set(
        [merged_claim.provenance], merged_claim.additional_provenance
    ) == _provenance_set(
        *(
            [claim.provenance, *claim.additional_provenance]
            for claim in source_claims
        )
    )
    assert not {
        "R8",
        "R8_RESTATEMENT",
        "C4",
        "C4_RESTATEMENT",
    } & {
        entity_id
        for question in canonical.research_questions
        for canonical_unit in question.study_units
        for entity_id in (
            [canonical_unit.unit_id]
            + [result.result_id for result in canonical_unit.results]
            + [claim.claim_id for claim in canonical_unit.claims]
        )
    }
    assert len(canonical.merge_decisions) == 2
    decisions = {decision.surviving_id: decision for decision in canonical.merge_decisions}
    assert decisions[canonical_result_id].merged_ids == ["R8", "R8_RESTATEMENT"]
    assert decisions[canonical_claim_id].merged_ids == ["C4", "C4_RESTATEMENT"]
    for surviving_id, entity_type in (
        (canonical_result_id, "result"),
        (canonical_claim_id, "claim"),
    ):
        reason = json.loads(decisions[surviving_id].reason)
        assert reason["audit_schema"] == "odracir.paper-study.merge-decision/v1"
        assert reason["entity_type"] == entity_type
        assert reason["match_rule"] == "exact_canonical_key_v1"
        assert reason["score_ppm"] == 1_000_000
        assert reason["algorithm_version"] == "1.0"
        assert len(reason["source_entities"]) == 2
    _assert_reference_integrity(canonical)


def test_hard_negative_results_and_claims_are_retained() -> None:
    packet = _load_packet()
    plan = plan_canonicalization(packet)
    keys = _key_map(packet)

    assert keys[("result", "R9")] != keys[("result", "R10")]
    assert keys[("result", "R11")] != keys[("result", "R14")]
    assert keys[("claim", "C4")] != keys[("claim", "C5")]
    assert plan.merge_cluster_count == 0
    canonical = apply_canonicalization_plan(packet, plan)
    canonical_entity_ids = {
        entity_id
        for question in canonical.research_questions
        for unit in question.study_units
        for entity_id in (
            [result.result_id for result in unit.results]
            + [claim.claim_id for claim in unit.claims]
        )
    }
    for left, right, entity_type in (
        ("R9", "R10", "result"),
        ("R11", "R14", "result"),
        ("C4", "C5", "claim"),
    ):
        left_id = _canonical_id(plan, entity_type, left)
        right_id = _canonical_id(plan, entity_type, right)
        assert left_id != right_id
        assert {left_id, right_id} <= canonical_entity_ids
    assert canonical.merge_decisions == []
    _assert_reference_integrity(canonical)


def test_canonical_keys_are_invariant_to_list_order() -> None:
    original = _load_packet()
    shuffled = original.model_copy(deep=True)
    shuffled.research_questions.reverse()
    for question in shuffled.research_questions:
        question.study_units.reverse()
        for unit in question.study_units:
            unit.experiments_or_tasks.reverse()
            unit.datasets.reverse()
            unit.methods.reverse()
            unit.results.reverse()
            unit.claims.reverse()
            unit.evidence_spans.reverse()
            for claim in unit.claims:
                claim.inference_basis_ids.reverse()

    assert _key_map(original) == _key_map(shuffled)
    canonical_original = apply_canonicalization_plan(
        original, plan_canonicalization(original)
    )
    canonical_shuffled = apply_canonicalization_plan(
        shuffled, plan_canonicalization(shuffled)
    )
    assert canonical_original.model_dump(mode="json") == canonical_shuffled.model_dump(
        mode="json"
    )
    assert normalize_scientific_text("SOX9  at E14.5") == normalize_scientific_text(
        "sox9 at  E14.5"
    )


def test_consecutive_canonicalization_is_idempotent() -> None:
    packet = _packet_with_isomorphic_restatements()
    first = apply_canonicalization_plan(packet, plan_canonicalization(packet))
    second = apply_canonicalization_plan(first, plan_canonicalization(first))

    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_duplicate_study_unit_rebuilds_the_complete_reference_chain() -> None:
    packet = _packet_with_duplicate_study_unit()
    source_unit = next(
        unit
        for unit in packet.research_questions[0].study_units
        if unit.unit_id == "SU2"
    )
    plan = plan_canonicalization(packet)
    canonical_unit_id = _canonical_id(plan, "study_unit", "SU2")
    assert canonical_unit_id == _canonical_id(plan, "study_unit", "SU2_COPY")

    canonical = apply_canonicalization_plan(packet, plan)
    unit = _find_unit(canonical, canonical_unit_id)
    assert len(canonical.research_questions[0].study_units) == 4
    assert len(unit.results) == len(source_unit.results)
    assert len(unit.claims) == len(source_unit.claims)
    for result in source_unit.results:
        assert _canonical_id(plan, "result", result.result_id) == _canonical_id(
            plan, "result", f"{result.result_id}_COPY"
        )
    for claim in source_unit.claims:
        assert _canonical_id(plan, "claim", claim.claim_id) == _canonical_id(
            plan, "claim", f"{claim.claim_id}_COPY"
        )
    decision_types = Counter(
        json.loads(decision.reason)["entity_type"]
        for decision in canonical.merge_decisions
    )
    assert decision_types == {
        "study_unit": 1,
        "result": len(source_unit.results),
        "claim": len(source_unit.claims),
    }
    assert all(
        len([result.provenance, *result.additional_provenance]) == 2
        for result in unit.results
    )
    assert all(
        len([claim.provenance, *claim.additional_provenance]) == 2
        for claim in unit.claims
    )
    _assert_reference_integrity(canonical)
    second = apply_canonicalization_plan(canonical, plan_canonicalization(canonical))
    assert canonical.model_dump(mode="json") == second.model_dump(mode="json")


def test_complete_link_does_not_transitively_chain() -> None:
    pair_scores = {
        ("a", "b"): 900_000,
        ("a", "c"): 700_000,
        ("b", "c"): 900_000,
    }

    def score(left: str, right: str) -> int:
        return pair_scores[tuple(sorted((left, right)))]

    forward = complete_link_clusters(
        ["a", "b", "c"],
        score=score,
        threshold_ppm=800_000,
        stable_key=lambda item: item,
    )
    reversed_input = complete_link_clusters(
        ["c", "b", "a"],
        score=score,
        threshold_ppm=800_000,
        stable_key=lambda item: item,
    )

    forward_shape = tuple(cluster.members for cluster in forward)
    reversed_shape = tuple(cluster.members for cluster in reversed_input)
    assert forward_shape == reversed_shape == (("a", "b"), ("c",))
