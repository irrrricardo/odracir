from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

import pytest
from pydantic import ValidationError

from odracir.paper_study.models import (
    AlignmentReceipt,
    AssertionEvidenceRef,
    AssertionRelation,
    GenerationContextReceipt,
    GlobalAssertion,
    GlobalStateLedger,
    LedgerEntityRef,
    LedgerEvent,
    PaperStudyDeliveryV2,
    PaperStudyPacketV2,
    PacketValidationWarning,
    Provenance,
    Claim,
    ResearchQuestion,
    ResultObservation,
    StudyUnit,
    packet_content_digest,
)


_DIGEST_A = "sha256:" + "a" * 64
_DIGEST_B = "sha256:" + "b" * 64
_DIGEST_C = "sha256:" + "c" * 64


def _packet() -> PaperStudyPacketV2:
    provenance = Provenance(
        chunk_id="chunk-1",
        page_start=1,
        page_end=1,
        text_excerpt="The response increased.",
        paraphrased=False,
    )
    return PaperStudyPacketV2(
        paper_id="paper-1",
        research_questions=[
            ResearchQuestion(
                question_id="question-1",
                statement="What changed?",
                study_units=[
                    StudyUnit(
                        unit_id="unit-1",
                        name="Primary experiment",
                        results=[
                            ResultObservation(
                                result_id="result-1",
                                metric_name="response",
                                value_raw_text="increased",
                                provenance=provenance,
                            )
                        ],
                        claims=[
                            Claim(
                                claim_id="claim-1",
                                statement="The response increased.",
                                polarity="positive",
                                inference_basis_ids=["result-1"],
                                provenance=provenance,
                            )
                        ],
                    )
                ],
            )
        ],
    )


def _alignment(
    packet: PaperStudyPacketV2,
    *,
    alignment_id: str = "alignment-1",
    target_assertion_id: str = "assertion-a",
    policy_version: str = "alignment-v1",
    output_digest: str = _DIGEST_C,
) -> AlignmentReceipt:
    packet_digest = packet_content_digest(packet)
    return AlignmentReceipt(
        alignment_id=alignment_id,
        source=LedgerEntityRef(
            paper_id=packet.paper_id,
            entity_type="claim",
            canonical_id="claim-1",
            packet_digest=packet_digest,
        ),
        target_assertion_id=target_assertion_id,
        relation_type="new_assertion",
        score_ppm=1_000_000,
        alignment_policy_version=policy_version,
        output_ledger_digest=output_digest,
    )


def _delivery(
    *,
    generation_context: GenerationContextReceipt | None = None,
    alignment: AlignmentReceipt | None = None,
) -> PaperStudyDeliveryV2:
    packet = _packet()
    return PaperStudyDeliveryV2(
        packet=packet,
        packet_digest=packet_content_digest(packet),
        generation_context=generation_context
        or GenerationContextReceipt(
            ledger_digest=_genesis().digest(),
            ledger_revision=0,
            through_batch=0,
            projection_policy_version="projection-v1",
            prompt_projection_digest=_DIGEST_B,
        ),
        alignments=(alignment or _alignment(packet),),
    )


def _evidence(
    assertion_suffix: str,
    *,
    chunk_id: str = "chunk-1",
    packet_digest: str = _DIGEST_A,
) -> AssertionEvidenceRef:
    return AssertionEvidenceRef(
        claim=LedgerEntityRef(
            paper_id=f"paper-{assertion_suffix}",
            entity_type="claim",
            canonical_id=f"claim-{assertion_suffix}",
            packet_digest=packet_digest,
        ),
        result_ids=(f"result-{assertion_suffix}",),
        source_chunk_ids=(chunk_id,),
    )


def _assertion(assertion_id: str, evidence: tuple[AssertionEvidenceRef, ...]) -> GlobalAssertion:
    return GlobalAssertion(
        assertion_id=assertion_id,
        proposition_key=f"proposition:{assertion_id}",
        preferred_statement=f"Statement for {assertion_id}.",
        polarity="positive",
        status="supported",
        conditions=("adult",),
        evidence=evidence,
    )


def _event(
    sequence: int,
    revision: int,
    event_type: str,
    subject_id: str,
    *,
    payload: dict[str, Any] | None = None,
    payload_digest: str | None = None,
) -> LedgerEvent:
    event_payload = payload or {"subject_id": subject_id}
    canonical_payload = json.dumps(
        event_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return LedgerEvent.model_validate(
        {
            "event_id": f"event-{sequence}",
            "sequence": sequence,
            "revision": revision,
            "event_type": event_type,
            "subject_id": subject_id,
            "payload": event_payload,
            "payload_digest": payload_digest
            or f"sha256:{hashlib.sha256(canonical_payload).hexdigest()}",
        }
    )


def _genesis() -> GlobalStateLedger:
    return GlobalStateLedger(
        corpus_id="corpus-1",
        reducer_policy_version="reducer-v1",
        alignment_policy_version="alignment-v1",
    )


def _revision_one() -> GlobalStateLedger:
    genesis = _genesis()
    assertions = (
        _assertion("assertion-a", (_evidence("a"),)),
        _assertion("assertion-b", (_evidence("b", packet_digest=_DIGEST_B),)),
    )
    relation = AssertionRelation(
        relation_id="relation-1",
        source_assertion_id="assertion-a",
        target_assertion_id="assertion-b",
        relation_type="contradicts",
        score_ppm=975_000,
        policy_version="alignment-v1",
    )
    return GlobalStateLedger(
        corpus_id="corpus-1",
        revision=1,
        through_batch=1,
        parent_digest=genesis.digest(),
        reducer_policy_version="reducer-v1",
        alignment_policy_version="alignment-v1",
        assertions=assertions,
        relations=(relation,),
        events=(
            _event(1, 1, "assertion_added", "assertion-a"),
            _event(2, 1, "assertion_added", "assertion-b"),
            _event(3, 1, "relation_added", "relation-1"),
            _event(4, 1, "batch_committed", "batch:1"),
        ),
    )


def _mutate(model: Any, **changes: Any) -> dict[str, Any]:
    return {**model.model_dump(mode="python"), **changes}


def test_packet_remains_decoupled_from_global_state_contracts() -> None:
    packet = _packet()

    assert "generation_context" not in packet.model_dump(mode="json")
    assert "global_context_snapshot" not in PaperStudyPacketV2.model_json_schema()[
        "properties"
    ]


def test_legacy_packet_data_defaults_to_accepted_admission() -> None:
    legacy_data = _packet().model_dump(mode="python")
    legacy_data.pop("status")
    legacy_data.pop("requires_reconciliation")
    legacy_data.pop("validation_warnings")

    packet = PaperStudyPacketV2.model_validate(legacy_data)

    assert packet.status == "accepted"
    assert packet.requires_reconciliation is False
    assert packet.validation_warnings == []


@pytest.mark.parametrize(
    ("status", "requires_reconciliation"),
    [("accepted", True), ("provisional", False)],
)
def test_packet_admission_status_requires_consistent_reconciliation_flag(
    status: str,
    requires_reconciliation: bool,
) -> None:
    with pytest.raises(ValidationError, match="if and only if"):
        PaperStudyPacketV2.model_validate(
            {
                **_packet().model_dump(mode="python"),
                "status": status,
                "requires_reconciliation": requires_reconciliation,
            }
        )


def test_packet_warning_contract_is_strict_stable_and_round_trips() -> None:
    first = PacketValidationWarning(
        code="duplicate_method_id_repaired",
        message="A duplicate method identifier was renamed.",
        json_path="/research_questions/0/study_units/0/methods/1/method_id",
        repair="Renamed method-1 to method-1-2.",
    )
    second = PacketValidationWarning(
        code="page_range_adjusted",
        message="The evidence page range was clamped to the source chunk.",
    )
    packet = PaperStudyPacketV2(
        paper_id="paper-warning",
        status="provisional",
        requires_reconciliation=True,
        validation_warnings=[second, first, second],
    )

    assert packet.validation_warnings == [first, second]
    assert PaperStudyPacketV2.model_validate_json(packet.model_dump_json()) == packet
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        PacketValidationWarning.model_validate(
            {
                "code": "unknown",
                "message": "Unknown warning.",
                "severity": "warning",
            }
        )


def test_packet_status_schema_is_closed_and_warning_fields_are_typed() -> None:
    with pytest.raises(ValidationError):
        PaperStudyPacketV2(paper_id="paper-invalid", status="rejected")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        PacketValidationWarning(code="", message="Invalid empty code.")
    with pytest.raises(ValidationError):
        PacketValidationWarning(code="page_adjusted", message="")


@pytest.mark.parametrize(
    ("admission_status", "weight_ppm", "valid"),
    [
        ("accepted", 1_000_000, True),
        ("accepted", 999_999, False),
        ("provisional", 500_000, True),
        ("provisional", 1, True),
        ("provisional", 500_001, False),
        ("provisional", 0, False),
    ],
)
def test_assertion_evidence_admission_weight_contract(
    admission_status: str,
    weight_ppm: int,
    valid: bool,
) -> None:
    data = {
        **_evidence("weighted").model_dump(mode="python"),
        "admission_status": admission_status,
        "weight_ppm": weight_ppm,
    }

    if valid:
        evidence = AssertionEvidenceRef.model_validate(data)
        assert evidence.admission_status == admission_status
        assert evidence.weight_ppm == weight_ppm
        assert AssertionEvidenceRef.model_validate_json(
            evidence.model_dump_json()
        ) == evidence
    else:
        with pytest.raises(ValidationError):
            AssertionEvidenceRef.model_validate(data)


def test_legacy_assertion_evidence_defaults_to_full_accepted_weight() -> None:
    data = _evidence("legacy").model_dump(mode="python")
    data.pop("admission_status")
    data.pop("weight_ppm")

    evidence = AssertionEvidenceRef.model_validate(data)

    assert evidence.admission_status == "accepted"
    assert evidence.weight_ppm == 1_000_000


def test_genesis_and_revision_have_stable_content_digests() -> None:
    genesis = _genesis()
    revision = _revision_one()

    assert revision.parent_digest == genesis.digest()
    assert GlobalStateLedger.model_validate(
        revision.model_dump(mode="python")
    ).digest() == revision.digest()
    assert revision.digest().startswith("sha256:")


def test_ledger_event_payload_is_immutable_digest_checked_and_round_trips() -> None:
    event = _event(
        1,
        1,
        "assertion_added",
        "assertion-a",
        payload={"assertion": {"id": "assertion-a", "conditions": ["adult"]}},
    )

    with pytest.raises(TypeError):
        event.payload["new"] = True  # type: ignore[index]
    assertion_payload = event.payload["assertion"]
    assert isinstance(assertion_payload, Mapping)
    with pytest.raises(TypeError):
        assertion_payload["id"] = "changed"  # type: ignore[index]

    encoded = event.model_dump_json()
    assert LedgerEvent.model_validate_json(encoded) == event
    with pytest.raises(ValidationError, match="payload_digest does not match"):
        LedgerEvent.model_validate(
            {**event.model_dump(mode="python"), "payload_digest": _DIGEST_C}
        )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"parent_digest": None}, "requires parent_digest"),
        ({"through_batch": 2}, "revision must equal"),
        ({"assertions": tuple(reversed(_revision_one().assertions))}, "sorted"),
        (
            {
                "events": (
                    _event(1, 1, "batch_committed", "batch:1"),
                    _event(2, 1, "assertion_added", "assertion-a"),
                    _event(3, 1, "assertion_added", "assertion-b"),
                    _event(4, 1, "relation_added", "relation-1"),
                )
            },
            "must end",
        ),
    ],
)
def test_ledger_rejects_invalid_snapshot_invariants(
    changes: dict[str, Any],
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        GlobalStateLedger.model_validate(_mutate(_revision_one(), **changes))


def test_relation_requires_existing_endpoints_and_canonical_symmetric_order() -> None:
    revision = _revision_one()
    missing = AssertionRelation(
        relation_id="relation-missing",
        source_assertion_id="assertion-a",
        target_assertion_id="assertion-c",
        relation_type="supports",
        score_ppm=900_000,
        policy_version="alignment-v1",
    )

    with pytest.raises(ValidationError, match="endpoint"):
        GlobalStateLedger.model_validate(
            _mutate(
                revision,
                relations=(missing,),
                events=(
                    _event(1, 1, "assertion_added", "assertion-a"),
                    _event(2, 1, "assertion_added", "assertion-b"),
                    _event(3, 1, "relation_added", "relation-missing"),
                    _event(4, 1, "batch_committed", "batch:1"),
                ),
            )
        )
    with pytest.raises(ValidationError, match="ascending"):
        AssertionRelation(
            relation_id="reverse",
            source_assertion_id="assertion-b",
            target_assertion_id="assertion-a",
            relation_type="same_as",
            score_ppm=1_000_000,
            policy_version="alignment-v1",
        )


def test_successor_preserves_event_prefix_and_adds_evidence() -> None:
    previous = _revision_one()
    old_a, assertion_b = previous.assertions
    new_a = old_a.model_copy(
        update={"evidence": (*old_a.evidence, _evidence("c", chunk_id="chunk-3"))}
    )
    successor = GlobalStateLedger(
        corpus_id=previous.corpus_id,
        revision=2,
        through_batch=2,
        parent_digest=previous.digest(),
        reducer_policy_version=previous.reducer_policy_version,
        alignment_policy_version=previous.alignment_policy_version,
        assertions=(new_a, assertion_b),
        relations=previous.relations,
        events=(
            *previous.events,
            _event(5, 2, "assertion_evidence_added", "assertion-a"),
            _event(6, 2, "batch_committed", "batch:2"),
        ),
    )

    assert successor.validate_successor_of(previous) is successor

    silent_update = successor.model_copy(
        update={
            "events": (
                *previous.events,
                _event(5, 2, "batch_committed", "batch:2"),
            )
        }
    )
    with pytest.raises(ValueError, match="requires an audit event"):
        silent_update.validate_successor_of(previous)


def test_ledger_requires_one_evidence_event_per_additional_reference() -> None:
    genesis = _genesis()
    assertion = _assertion("assertion-a", (_evidence("a"), _evidence("b")))

    with pytest.raises(ValidationError, match="exactly one assertion_evidence_added"):
        GlobalStateLedger(
            corpus_id="corpus-1",
            revision=1,
            through_batch=1,
            parent_digest=genesis.digest(),
            reducer_policy_version="reducer-v1",
            alignment_policy_version="alignment-v1",
            assertions=(assertion,),
            events=(
                _event(1, 1, "assertion_added", "assertion-a"),
                _event(2, 1, "batch_committed", "batch:1"),
            ),
        )

    with pytest.raises(ValidationError, match="exactly one assertion_evidence_added"):
        GlobalStateLedger(
            corpus_id="corpus-1",
            revision=1,
            through_batch=1,
            parent_digest=genesis.digest(),
            reducer_policy_version="reducer-v1",
            alignment_policy_version="alignment-v1",
            assertions=(_assertion("assertion-a", (_evidence("a"),)),),
            events=(
                _event(1, 1, "assertion_added", "assertion-a"),
                _event(2, 1, "assertion_evidence_added", "assertion-a"),
                _event(3, 1, "batch_committed", "batch:1"),
            ),
        )


def test_successor_requires_one_event_for_each_new_evidence_reference() -> None:
    previous = _revision_one()
    old_a, assertion_b = previous.assertions
    new_a = old_a.model_copy(
        update={
            "evidence": (
                *old_a.evidence,
                _evidence("c", chunk_id="chunk-3"),
                _evidence("d", chunk_id="chunk-4"),
            )
        }
    )
    successor = previous.model_copy(
        update={
            "revision": 2,
            "through_batch": 2,
            "parent_digest": previous.digest(),
            "assertions": (new_a, assertion_b),
            "events": (
                *previous.events,
                _event(5, 2, "assertion_evidence_added", "assertion-a"),
                _event(6, 2, "batch_committed", "batch:2"),
            ),
        }
    )

    with pytest.raises(ValueError, match="exactly one assertion_evidence_added"):
        successor.validate_successor_of(previous)


def test_receipts_require_stable_context_and_valid_packet_links() -> None:
    packet = _packet()
    packet_digest = packet_content_digest(packet)
    generation_context = GenerationContextReceipt(
        ledger_digest=_genesis().digest(),
        ledger_revision=0,
        through_batch=0,
        projection_policy_version="projection-v1",
        prompt_projection_digest=_DIGEST_B,
        included_assertion_ids=(),
    )
    alignment = AlignmentReceipt(
        alignment_id="alignment-1",
        source=LedgerEntityRef(
            paper_id=packet.paper_id,
            entity_type="claim",
            canonical_id="claim-1",
            packet_digest=packet_digest,
        ),
        target_assertion_id="assertion-a",
        relation_type="new_assertion",
        score_ppm=1_000_000,
        alignment_policy_version="alignment-v1",
        output_ledger_digest=_DIGEST_C,
    )

    delivery = PaperStudyDeliveryV2(
        packet=packet,
        packet_digest=packet_digest,
        generation_context=generation_context,
        alignments=(alignment,),
    )

    assert delivery.packet is packet
    with pytest.raises(ValidationError, match="packet_digest does not match"):
        PaperStudyDeliveryV2(
            packet=packet,
            packet_digest=_DIGEST_A,
            generation_context=generation_context,
            alignments=(),
        )
    bad_alignment = alignment.model_copy(
        update={
            "source": alignment.source.model_copy(update={"canonical_id": "missing"})
        }
    )
    with pytest.raises(ValidationError, match="source must exist"):
        PaperStudyDeliveryV2(
            packet=packet,
            packet_digest=packet_digest,
            generation_context=generation_context,
            alignments=(bad_alignment,),
        )


def test_context_receipt_rejects_unsorted_or_mismatched_versions() -> None:
    with pytest.raises(ValidationError, match="sorted and unique"):
        GenerationContextReceipt(
            ledger_digest=_DIGEST_A,
            ledger_revision=1,
            through_batch=1,
            projection_policy_version="projection-v1",
            prompt_projection_digest=_DIGEST_B,
            included_assertion_ids=("b", "a"),
        )
    with pytest.raises(ValidationError, match="must equal"):
        GenerationContextReceipt(
            ledger_digest=_DIGEST_A,
            ledger_revision=2,
            through_batch=1,
            projection_policy_version="projection-v1",
            prompt_projection_digest=_DIGEST_B,
        )


def test_delivery_requires_exactly_one_claim_alignment_and_unique_receipts() -> None:
    packet = _packet()
    packet_digest = packet_content_digest(packet)
    context = GenerationContextReceipt(
        ledger_digest=_genesis().digest(),
        ledger_revision=0,
        through_batch=0,
        projection_policy_version="projection-v1",
        prompt_projection_digest=_DIGEST_B,
    )
    alignment = _alignment(packet)

    with pytest.raises(ValidationError, match="every packet claim"):
        PaperStudyDeliveryV2(
            packet=packet,
            packet_digest=packet_digest,
            generation_context=context,
            alignments=(),
        )
    with pytest.raises(ValidationError, match="alignment_id values must be unique"):
        PaperStudyDeliveryV2(
            packet=packet,
            packet_digest=packet_digest,
            generation_context=context,
            alignments=(alignment, alignment),
        )
    with pytest.raises(ValidationError, match="one output_ledger_digest"):
        PaperStudyDeliveryV2(
            packet=packet,
            packet_digest=packet_digest,
            generation_context=context,
            alignments=(
                alignment,
                alignment.model_copy(
                    update={
                        "alignment_id": "alignment-2",
                        "output_ledger_digest": _DIGEST_B,
                    }
                ),
            ),
        )
    with pytest.raises(ValidationError, match="one alignment_policy_version"):
        PaperStudyDeliveryV2(
            packet=packet,
            packet_digest=packet_digest,
            generation_context=context,
            alignments=(
                alignment,
                alignment.model_copy(
                    update={
                        "alignment_id": "alignment-2",
                        "alignment_policy_version": "alignment-v2",
                    }
                ),
            ),
        )


def test_delivery_validates_generation_and_alignment_receipts_against_ledgers() -> None:
    generation = _genesis()
    output = _revision_one()
    packet = _packet()
    delivery = _delivery(
        alignment=_alignment(packet, output_digest=output.digest())
    )

    assert delivery.validate_against_ledgers(generation, output) is delivery


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("generation_digest", "ledger_digest"),
        ("generation_revision", "ledger_revision"),
        ("generation_through_batch", "through_batch"),
        ("included_assertion", "included_assertion_ids"),
        ("target_assertion", "target_assertion_id"),
        ("output_digest", "output_ledger_digest"),
        ("alignment_policy", "alignment_policy_version"),
    ],
)
def test_delivery_rejects_receipts_that_do_not_match_ledgers(
    mutation: str,
    message: str,
) -> None:
    generation = _genesis()
    output = _revision_one()
    packet = _packet()
    context = GenerationContextReceipt(
        ledger_digest=generation.digest(),
        ledger_revision=0,
        through_batch=0,
        projection_policy_version="projection-v1",
        prompt_projection_digest=_DIGEST_B,
    )
    alignment = _alignment(packet, output_digest=output.digest())

    if mutation == "generation_digest":
        context = context.model_copy(update={"ledger_digest": _DIGEST_A})
    elif mutation == "generation_revision":
        context = context.model_copy(update={"ledger_revision": 1})
    elif mutation == "generation_through_batch":
        context = context.model_copy(update={"through_batch": 1})
    elif mutation == "included_assertion":
        context = context.model_copy(
            update={"included_assertion_ids": ("assertion-missing",)}
        )
    elif mutation == "target_assertion":
        alignment = alignment.model_copy(
            update={"target_assertion_id": "assertion-missing"}
        )
    elif mutation == "output_digest":
        alignment = alignment.model_copy(update={"output_ledger_digest": _DIGEST_C})
    elif mutation == "alignment_policy":
        alignment = alignment.model_copy(
            update={"alignment_policy_version": "alignment-v2"}
        )

    delivery = _delivery(
        alignment=_alignment(packet, output_digest=output.digest())
    ).model_copy(
        update={"generation_context": context, "alignments": (alignment,)}
    )
    with pytest.raises(ValueError, match=message):
        delivery.validate_against_ledgers(generation, output)
