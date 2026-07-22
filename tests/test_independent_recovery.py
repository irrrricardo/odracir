from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import fitz
import pytest

from odracir.paper_study.extraction import JsonCompletionResult
from odracir.paper_study.independent_recovery import recover_independent_failures
from odracir.paper_study.models import PaperStudyPacketV2
from odracir.paper_study.run_reporting import PaperRunRecord, PricingSnapshot


SOURCE_TEXT = "The intervention increased the response by 20 percent."


class RecoveryProvider:
    provider_name = "fake"
    model = "recovery-fixture"

    def complete_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
    ) -> JsonCompletionResult:
        del system_prompt, max_tokens
        payload = json.loads(user_prompt.split("\n", 1)[1])
        if payload.get("audit_protocol") == "semantic-prf-v1":
            return JsonCompletionResult(
                payload={"incorrect_items": [], "missed_core_items": []},
                usage={"prompt_tokens": 10, "completion_tokens": 5},
                finish_reason="stop",
            )
        paper_id = payload["paper_id"]
        chunk = payload["chunks"][0]
        provenance = {
            "chunk_id": chunk["chunk_id"],
            "page_start": chunk["page_start"],
            "page_end": chunk["page_end"],
            "text_excerpt": SOURCE_TEXT,
            "paraphrased": False,
        }
        return JsonCompletionResult(
            payload={
                "research_questions": [
                    {
                        "question_id": "RQ1",
                        "statement": "Does the intervention alter the response?",
                        "study_units": [
                            {
                                "unit_id": "SU1",
                                "name": "Intervention experiment",
                                "experiments_or_tasks": ["Compare treated samples."],
                                "results": [
                                    {
                                        "result_id": "R1",
                                        "metric_name": "Response",
                                        "value_raw_text": "Increased by 20 percent.",
                                        "provenance": provenance,
                                    }
                                ],
                                "claims": [
                                    {
                                        "claim_id": "C1",
                                        "statement": f"{paper_id} reports an increase.",
                                        "polarity": "positive",
                                        "inference_basis_ids": ["R1"],
                                        "provenance": provenance,
                                    }
                                ],
                                "evidence_spans": [
                                    {
                                        "span_id": "E1",
                                        "content": SOURCE_TEXT,
                                        "provenance": provenance,
                                    }
                                ],
                            }
                        ],
                    }
                ],
                "limitations_and_boundaries": [
                    "Only one model system was studied.",
                    "The mechanism was not directly tested.",
                    "Long-term outcomes were not evaluated.",
                ],
            },
            usage={"prompt_tokens": 20, "completion_tokens": 10},
            finish_reason="stop",
        )


def _write_pdf(path: Path) -> str:
    with fitz.open() as document:
        page = document.new_page()
        page.insert_text((72, 72), SOURCE_TEXT)
        document.save(path)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_failure_report(path: Path, *, paper_id: str, source_sha256: str) -> None:
    record = PaperRunRecord(
        paper_id=paper_id,
        source_file=f"{paper_id}.pdf",
        source_sha256=source_sha256,
        status="failed",
        error_type="ValueError",
        error_message="DeepSeek returned invalid JSON content",
    )
    path.write_text(record.model_dump_json() + "\n", encoding="utf-8")


def test_recovery_merges_validated_packet_without_overwriting_delivery(
    tmp_path: Path,
) -> None:
    paper_root = tmp_path / "papers"
    paper_root.mkdir()
    source_sha = _write_pdf(paper_root / "paper-2.pdf")
    source_report = tmp_path / "papers.jsonl"
    _write_failure_report(
        source_report,
        paper_id="paper-2",
        source_sha256=source_sha,
    )
    delivery = tmp_path / "delivery"
    delivery.mkdir()
    sentinel = delivery / "existing-success.json"
    sentinel.write_text('{"keep": true}\n', encoding="utf-8")
    sentinel_bytes = sentinel.read_bytes()

    summary = recover_independent_failures(
        source_report,
        RecoveryProvider(),
        paper_folder=paper_root,
        delivery_folder=delivery,
        work_folder=tmp_path / "work",
        report_folder=tmp_path / "recovery-report",
        max_chunks=1,
        pricing=PricingSnapshot(
            input_usd_per_million_tokens=1.0,
            output_usd_per_million_tokens=2.0,
            pricing_as_of="2026-07-22",
        ),
    )

    assert summary.status == "completed"
    assert summary.requested_paper_ids == ("paper-2",)
    assert summary.attempted_paper_ids == ("paper-2",)
    assert summary.merged_paper_ids == ("paper-2",)
    assert summary.failures == {}
    assert sentinel.read_bytes() == sentinel_bytes
    delivered = delivery / "paper-2.json"
    packet = PaperStudyPacketV2.model_validate_json(delivered.read_text())
    assert packet.paper_id == "paper-2"
    assert packet.metadata["source_sha256"] == source_sha
    assert packet.quality_score == 1.0
    audit = json.loads(Path(summary.audit_path).read_text(encoding="utf-8"))
    assert audit["status"] == "completed"
    assert audit["merged_paper_ids"] == ["paper-2"]
    assert audit["parameters"]["max_chunks"] == 1
    assert (tmp_path / "recovery-report" / "run" / "papers.jsonl").is_file()


def test_recovery_refuses_changed_source_without_explicit_permission(
    tmp_path: Path,
) -> None:
    paper_root = tmp_path / "papers"
    paper_root.mkdir()
    _write_pdf(paper_root / "paper-2.pdf")
    source_report = tmp_path / "papers.jsonl"
    _write_failure_report(
        source_report,
        paper_id="paper-2",
        source_sha256="0" * 64,
    )

    with pytest.raises(ValueError, match="source PDF changed"):
        recover_independent_failures(
            source_report,
            RecoveryProvider(),
            paper_folder=paper_root,
            delivery_folder=tmp_path / "delivery",
            work_folder=tmp_path / "work",
            report_folder=tmp_path / "recovery-report",
            max_chunks=1,
        )
