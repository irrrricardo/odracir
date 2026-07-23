from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from odracir.paper_study.assembly import assemble_scheduler_result
from odracir.paper_study.conflict_review import (
    ClaimSelector,
    ConflictSpec,
    CriticalConflictReport,
    generate_critical_conflicts,
    resolve_critical_conflicts,
)
from odracir.paper_study.models import (
    Claim,
    PacketStatus,
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


def _packet(
    paper_id: str,
    claim_id: str,
    statement: str,
    polarity: str,
    *,
    status: PacketStatus,
    quality_score: float,
    basis_ids: list[str] | None = None,
    result_ids: tuple[str, ...] = ("result-1",),
) -> PaperStudyPacketV2:
    provenance = Provenance(
        chunk_id=f"{paper_id}-chunk",
        page_start=2,
        page_end=2,
        text_excerpt=f"Source evidence for {statement}",
        paraphrased=True,
    )
    results = [
        ResultObservation(
            result_id=f"{paper_id}-{result_id}",
            metric_name="prediction error",
            value_raw_text=f"observed value {index}",
            quantitative_value=float(index),
            provenance=provenance,
        )
        for index, result_id in enumerate(result_ids, start=1)
    ]
    resolved_basis_ids = (
        [result.result_id for result in results]
        if basis_ids is None
        else basis_ids
    )
    return PaperStudyPacketV2(
        paper_id=paper_id,
        status=status,
        requires_reconciliation=status == "provisional",
        quality_score=quality_score,
        research_questions=[
            ResearchQuestion(
                question_id=f"{paper_id}-question",
                statement="Which conclusion is supported?",
                study_units=[
                    StudyUnit(
                        unit_id=f"{paper_id}-unit",
                        name="Synthetic benchmark",
                        experiments_or_tasks=["Compare a method with a baseline."],
                        results=results,
                        claims=[
                            Claim(
                                claim_id=claim_id,
                                statement=statement,
                                polarity=polarity,
                                inference_basis_ids=resolved_basis_ids,
                                provenance=provenance,
                            )
                        ],
                    )
                ],
            )
        ],
    )


def _assembly(
    *,
    left_basis_ids: list[str] | None = None,
    left_result_ids: tuple[str, ...] = ("result-1", "result-2"),
):
    packets = {
        "paper-a": _packet(
            "paper-a",
            "claim-a",
            "Method improves prediction at 24 h.",
            "positive",
            status="accepted",
            quality_score=0.93,
            basis_ids=left_basis_ids,
            result_ids=left_result_ids,
        ),
        "paper-b": _packet(
            "paper-b",
            "claim-b",
            "Method does not improve prediction at 24 h.",
            "negative",
            status="provisional",
            quality_score=0.81,
        ),
    }
    scheduled = run_paper_study_scheduler(
        [
            PaperIndexEntry(paper_id=paper_id, source_path=f"{paper_id}.pdf")
            for paper_id in packets
        ],
        lambda entry, _context: packets[entry.paper_id],
        batch_size=1,
    )
    return assemble_scheduler_result(scheduled, corpus_id="synthetic-corpus")


def _spec(
    *,
    side_a: ClaimSelector | None = None,
    side_b: ClaimSelector | None = None,
) -> ConflictSpec:
    return ConflictSpec(
        conflict_id="conflict-001",
        classification="explicit_contradiction",
        title="Synthetic method-performance conflict",
        rationale="The two claims report opposing conclusions under one condition.",
        review_question="Which comparison protocol should govern the core snapshot?",
        side_a=side_a or ClaimSelector(paper_id="paper-a", claim_id="claim-a"),
        side_b=side_b or ClaimSelector(paper_id="paper-b", claim_id="claim-b"),
    )


def test_resolves_complete_audited_claim_result_and_assertion_chain() -> None:
    assembly = _assembly()

    report = resolve_critical_conflicts(assembly, [_spec()])
    repeated = resolve_critical_conflicts(assembly, [_spec()])

    assert report == repeated
    assert report.corpus_id == "synthetic-corpus"
    assert report.ledger_digest == assembly.final_ledger.digest()
    assert report.report_digest.startswith("sha256:")
    conflict = report.conflicts[0]
    assert conflict.side_a.selector.paper_id == "paper-a"
    assert conflict.side_a.packet_quality_score == 0.93
    assert conflict.side_a.packet_status == "accepted"
    assert conflict.side_a.assertion_status == conflict.side_a.assertion.status
    assert conflict.side_a.evidence_weight_ppm == 1_000_000
    assert [result.result_id for result in conflict.side_a.basis_results] == [
        "paper-a-result-1",
        "paper-a-result-2",
    ]
    assert conflict.side_a.claim.provenance.chunk_id == "paper-a-chunk"
    assert conflict.side_a.basis_results[0].provenance.page_start == 2
    assert conflict.side_b.packet_status == "provisional"
    assert conflict.side_b.requires_reconciliation is True
    assert conflict.side_b.assertion_status == "unresolved"
    assert conflict.side_b.evidence_weight_ppm == 350_000


def test_writes_deterministic_full_fidelity_json_csv_markdown_and_checksums(
    tmp_path: Path,
) -> None:
    report, artifacts = generate_critical_conflicts(
        _assembly(), [_spec()], tmp_path / "review"
    )

    assert Path(artifacts.json_path).name == "critical_conflicts.json"
    assert Path(artifacts.csv_path).name == "critical_conflicts.csv"
    assert Path(artifacts.markdown_path).name == "critical_conflicts.md"
    assert Path(artifacts.checksum_path).name == "critical_conflicts.sha256"
    persisted = CriticalConflictReport.model_validate_json(
        Path(artifacts.json_path).read_text(encoding="utf-8")
    )
    assert persisted == report

    with Path(artifacts.csv_path).open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 3
    assert {row["side"] for row in rows} == {"a", "b"}
    assert all(row["report_digest"] == report.report_digest for row in rows)
    assert json.loads(rows[0]["claim_json"])["provenance"]["chunk_id"] in {
        "paper-a-chunk",
        "paper-b-chunk",
    }
    assert json.loads(rows[0]["result_json"])["result_id"] == rows[0]["result_id"]

    markdown = Path(artifacts.markdown_path).read_text(encoding="utf-8")
    assert report.report_digest in markdown
    assert "Side A" in markdown and "Side B" in markdown
    assert "paper-a-chunk" in markdown and "paper-b-chunk" in markdown

    checksum_lines = Path(artifacts.checksum_path).read_text(
        encoding="utf-8"
    ).splitlines()
    expected_paths = [
        Path(artifacts.json_path),
        Path(artifacts.csv_path),
        Path(artifacts.markdown_path),
    ]
    assert checksum_lines == [
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}"
        for path in expected_paths
    ]


@pytest.mark.parametrize(
    ("selector", "message"),
    [
        (ClaimSelector(paper_id="missing", claim_id="claim-a"), "missing paper"),
        (ClaimSelector(paper_id="paper-a", claim_id="missing"), "missing claim"),
    ],
)
def test_rejects_missing_paper_or_claim(
    selector: ClaimSelector,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        resolve_critical_conflicts(_assembly(), [_spec(side_a=selector)])


def test_rejects_claim_without_inference_basis() -> None:
    with pytest.raises(ValueError, match="no inference basis"):
        resolve_critical_conflicts(
            _assembly(left_basis_ids=[]),
            [_spec()],
        )


def test_rejects_missing_inference_basis_result() -> None:
    with pytest.raises(ValueError, match="missing basis results"):
        resolve_critical_conflicts(
            _assembly(left_basis_ids=["paper-a-result-missing"]),
            [_spec()],
        )


def test_rejects_duplicate_ids_pairs_and_self_comparison() -> None:
    spec = _spec()
    duplicate_id = spec.model_copy(
        update={
            "side_a": spec.side_b,
            "side_b": spec.side_a,
        }
    )
    with pytest.raises(ValueError, match="unique conflict_id"):
        resolve_critical_conflicts(_assembly(), [spec, duplicate_id])

    second_id = duplicate_id.model_copy(update={"conflict_id": "conflict-002"})
    with pytest.raises(ValueError, match="same claim pair"):
        resolve_critical_conflicts(_assembly(), [spec, second_id])

    with pytest.raises(ValidationError, match="distinct claims"):
        _spec(side_b=ClaimSelector(paper_id="paper-a", claim_id="claim-a"))


def test_rejects_tampered_report_digest() -> None:
    report = resolve_critical_conflicts(_assembly(), [_spec()])
    payload = report.model_dump(mode="json")
    payload["report_digest"] = "sha256:" + "0" * 64

    with pytest.raises(ValidationError, match="report_digest"):
        CriticalConflictReport.model_validate_json(json.dumps(payload))
