from __future__ import annotations

import json
import shutil
import csv
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from odracir.cli import run_extract_paper_study
from odracir.paper_study.extraction import (
    JsonCompletionResult,
    MethodIdCorrectionAudit,
    _apply_safe_provenance_corrections,
    _build_repair_prompt,
    extract_paper_study,
    write_extraction_report,
)
from odracir.paper_study.models import (
    PROVENANCE_SIMILARITY_THRESHOLD,
    PROVENANCE_SOURCE_TEXT_CONTEXT_KEY,
    PaperStudyPacketV2,
    Provenance,
    provenance_text_similarity_ratio,
)
from odracir.paper_study.planning import (
    ChunkArtifact,
    SourceChunk,
    build_extraction_plan,
    load_chunk_artifact,
)


SOURCE_TEXT = "The intervention increased the response by 20 percent."


class FakeJsonProvider:
    provider_name = "fake"
    model = "deterministic-fixture"

    def __init__(
        self,
        *,
        complete_boundaries: bool = True,
        provenance_excerpt: str = SOURCE_TEXT,
        provenance_paraphrased: bool | None = False,
        provenance_chunk_id: str | None = None,
        provenance_page_start: object | None = None,
        provenance_page_end: object | None = None,
        miss_core_item: bool = False,
        invalid_judge_excerpt_once: bool = False,
    ) -> None:
        self.requests: list[dict[str, Any]] = []
        self.payloads: list[dict[str, Any]] = []
        self.complete_boundaries = complete_boundaries
        self.provenance_excerpt = provenance_excerpt
        self.provenance_paraphrased = provenance_paraphrased
        self.provenance_chunk_id = provenance_chunk_id
        self.provenance_page_start = provenance_page_start
        self.provenance_page_end = provenance_page_end
        self.miss_core_item = miss_core_item
        self.invalid_judge_excerpt_once = invalid_judge_excerpt_once
        self._judge_calls = 0
        self._judge_chunk_id: str | None = None

    def complete_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
    ) -> JsonCompletionResult:
        if user_prompt.startswith("Correct the quality-audit JSON"):
            self._judge_calls += 1
            self.requests.append(
                {"request_type": "quality_judge_repair", "max_tokens": max_tokens}
            )
            return JsonCompletionResult(
                payload={
                    "incorrect_items": [],
                    "missed_core_items": [
                        {
                            "item_id": None,
                            "reason": "A core outcome was omitted.",
                            "source_chunk_id": self._judge_chunk_id,
                            "source_excerpt": SOURCE_TEXT,
                        }
                    ],
                },
                usage={"prompt_tokens": 7, "completion_tokens": 3},
                finish_reason="stop",
            )
        source = json.loads(user_prompt.split("\n", 1)[1])
        if source.get("audit_protocol") == "semantic-prf-v1":
            self._judge_calls += 1
            self._judge_chunk_id = source["source_chunks"][0]["chunk_id"]
            self.requests.append(
                {
                    "request_type": "quality_judge",
                    "item_count": len(source["extracted_items"]),
                    "max_tokens": max_tokens,
                }
            )
            return JsonCompletionResult(
                payload={
                    "incorrect_items": [],
                    "missed_core_items": (
                        [
                            {
                                "item_id": None,
                                "reason": "A core outcome was omitted.",
                                "source_chunk_id": source["source_chunks"][0]["chunk_id"],
                                "source_excerpt": (
                                    "This is not a source excerpt."
                                    if self.invalid_judge_excerpt_once
                                    and self._judge_calls == 1
                                    else SOURCE_TEXT
                                ),
                            }
                        ]
                        if self.miss_core_item
                        else []
                    ),
                },
                usage={"prompt_tokens": 10, "completion_tokens": 5},
                finish_reason="stop",
            )
        self.requests.append(
            {
                "request_type": "extraction",
                "max_tokens": max_tokens,
                "paper_id": source["paper_id"],
                "source_keys": sorted(source),
                "system_prompt": system_prompt,
            }
        )
        paper_id = source["paper_id"]
        chunk = source["chunks"][0]
        provenance = {
            "chunk_id": self.provenance_chunk_id or chunk["chunk_id"],
            "page_start": (
                chunk["page_start"]
                if self.provenance_page_start is None
                else self.provenance_page_start
            ),
            "page_end": (
                chunk["page_end"]
                if self.provenance_page_end is None
                else self.provenance_page_end
            ),
            "text_excerpt": self.provenance_excerpt,
        }
        if self.provenance_paraphrased is not None:
            provenance["paraphrased"] = self.provenance_paraphrased
        payload = {
            "research_questions": [
                {
                    "question_id": "RQ1",
                    "statement": "Does the intervention alter the response?",
                    "study_units": [
                        {
                            "unit_id": "SU1",
                            "name": "Intervention experiment",
                            "experiments_or_tasks": [
                                "Compare treated and untreated samples."
                            ],
                            "results": [
                                {
                                    "result_id": "R1",
                                    "metric_name": "Response",
                                    "value_raw_text": "The response increased by 20 percent.",
                                    "provenance": provenance,
                                }
                            ],
                            "claims": [
                                {
                                    "claim_id": "C1",
                                    "statement": f"{paper_id} reports an increased response.",
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
            "limitations_and_boundaries": (
                [
                    "The experiment was restricted to one model system and may not generalize.",
                    "The mechanism linking intervention and response was not directly tested.",
                    "Long-term outcomes beyond the observation period were not evaluated.",
                ]
                if self.complete_boundaries
                else []
            ),
        }
        self.payloads.append(payload)
        return JsonCompletionResult(
            payload=payload,
            usage={"prompt_tokens": 10, "completion_tokens": 20},
            finish_reason="stop",
        )


class LowSimilarityFalseProvider(FakeJsonProvider):
    """Return a supported logical paraphrase with an intentionally unsafe flag."""

    def complete_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
    ) -> JsonCompletionResult:
        completion = super().complete_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=max_tokens,
        )

        def rewrite(value: Any) -> None:
            if isinstance(value, dict):
                if "text_excerpt" in value and "paraphrased" in value:
                    value["text_excerpt"] = "Treatment caused a larger measured outcome."
                    value["paraphrased"] = False
                for child in value.values():
                    rewrite(child)
            elif isinstance(value, list):
                for child in value:
                    rewrite(child)

        rewrite(completion.payload)
        return completion


def _write_chunk_artifact(
    root: Path,
    paper_id: str,
    *,
    chunk_count: int = 1,
    source_sha256: str | None = None,
    first_chunk_page_start: int = 1,
    first_chunk_page_end: int = 1,
) -> Path:
    chunks = []
    for ordinal in range(1, chunk_count + 1):
        text = SOURCE_TEXT if ordinal == 1 else f"Background chunk {ordinal}."
        chunks.append(
            SourceChunk(
                chunk_id=f"{paper_id}-chunk-{ordinal}",
                ordinal=ordinal,
                section_hint="results" if ordinal == 1 else "background",
                page_start=(first_chunk_page_start if ordinal == 1 else ordinal),
                page_end=(first_chunk_page_end if ordinal == 1 else ordinal),
                char_count=len(text),
                token_estimate=10,
                content_sha256=f"content-sha-{ordinal}",
                text=text,
            )
        )
    artifact = ChunkArtifact(
        schema_version="0.1",
        paper_id=paper_id,
        source_file=f"{paper_id}.pdf",
        source_sha256=source_sha256 or f"source-sha-{paper_id}",
        text_artifact=f".odracir/texts/{paper_id}.json",
        text_artifact_sha256="text-sha",
        chunker="test",
        chunker_version="1.0",
        chunked_at="2026-01-01T00:00:00Z",
        chunk_count=chunk_count,
        chunks=chunks,
    )
    path = root / ".odracir" / "chunks" / f"{paper_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(artifact.model_dump_json(by_alias=True), encoding="utf-8")
    return path


def test_cli_extracts_each_paper_independently_to_one_json(tmp_path: Path) -> None:
    first = _write_chunk_artifact(tmp_path, "paper-1")
    second = _write_chunk_artifact(tmp_path, "paper-2")
    (tmp_path / "odracir_index.json").write_text(
        json.dumps(
            {
                "schema_version": "0.2",
                "papers": [
                    {
                        "id": "paper-2",
                        "year": 2021,
                        "chunk_artifact": str(second.relative_to(tmp_path)),
                        "chunking_status": "chunked",
                    },
                    {
                        "id": "paper-1",
                        "year": 2020,
                        "chunk_artifact": str(first.relative_to(tmp_path)),
                        "chunking_status": "chunked",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    provider = FakeJsonProvider()
    output = tmp_path / "output"

    summary = run_extract_paper_study(
        [
            "--paper-folder",
            str(tmp_path),
            "--output-folder",
            str(output),
            "--max-chunks",
            "1",
            "--input-usd-per-million-tokens",
            "1.0",
            "--output-usd-per-million-tokens",
            "2.0",
            "--pricing-as-of",
            "2026-07-19",
        ],
        provider=provider,
    )

    assert summary.succeeded == 2
    assert summary.failed == 0
    assert summary.paper_ids == ("paper-1", "paper-2")
    extraction_requests = [request for request in provider.requests if request["request_type"] == "extraction"]
    assert len(extraction_requests) == 2
    assert all("prior_global_context" not in request["source_keys"] for request in extraction_requests)
    assert all("Prior Global Context" not in request["system_prompt"] for request in extraction_requests)
    assert "PROVENANCE SEMANTICS AND HARD RULE" in extraction_requests[1][
        "system_prompt"
    ]
    assert "logical propositions (Claims)" in extraction_requests[1]["system_prompt"]
    assert "scientific observations (Results)" in extraction_requests[1]["system_prompt"]
    assert "similarity ratio is at least 0.95" in extraction_requests[1]["system_prompt"]
    assert "always emit either true or false explicitly" in extraction_requests[1][
        "system_prompt"
    ]
    assert 'every occurrence of "paraphrased": false' in extraction_requests[1][
        "system_prompt"
    ]
    assert (
        extraction_requests[1]["system_prompt"].count(
            "PROVENANCE SEMANTICS AND HARD RULE"
        )
        == 2
    )
    assert "FINAL MANDATORY PROVENANCE CHECK" in extraction_requests[1]["system_prompt"]
    system_prompt = extraction_requests[1]["system_prompt"]
    assert "PROVENANCE DECISION FEW-SHOTS" in system_prompt
    assert "near-verbatim punctuation variation" in system_prompt
    assert 'Required decision: "paraphrased": false' in system_prompt
    assert "logical restatement with no verbatim source phrase" in system_prompt
    assert 'Required decision: "paraphrased": true' in system_prompt
    assert "SILENT SIMILARITY CHECK / SELF-CORRECTION" in system_prompt
    assert "find the best local" in system_prompt
    assert "Do not reveal chain-of-thought" in system_prompt
    assert "only the final schema-valid JSON object" in system_prompt

    assert {path.name for path in output.iterdir()} == {"paper-1.json", "paper-2.json"}
    report = tmp_path / "output-report"
    assert {path.name for path in report.iterdir()} == {
        "summary.json",
        "papers.csv",
        "papers.jsonl",
    }
    run_summary = json.loads((report / "summary.json").read_text(encoding="utf-8"))
    assert run_summary["succeeded"] == 2
    assert run_summary["failed"] == 0
    assert run_summary["total_prompt_tokens"] == 40
    assert run_summary["total_completion_tokens"] == 50
    assert run_summary["total_tokens"] == 90
    assert run_summary["estimated_cost_usd"] == pytest.approx(0.00014)
    assert run_summary["pricing"]["pricing_as_of"] == "2026-07-19"
    jsonl_records = [
        json.loads(line)
        for line in (report / "papers.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    with (report / "papers.csv").open(encoding="utf-8", newline="") as handle:
        csv_records = list(csv.DictReader(handle))
    assert [record["paper_id"] for record in jsonl_records] == ["paper-1", "paper-2"]
    assert [record["paper_id"] for record in csv_records] == ["paper-1", "paper-2"]
    assert all(record["extraction"]["prompt_tokens"] == 10 for record in jsonl_records)
    assert all(record["quality_judge"]["completion_tokens"] == 5 for record in jsonl_records)
    assert summary.report_paths == {
        "summary": str((report / "summary.json").resolve()),
        "jsonl": str((report / "papers.jsonl").resolve()),
        "csv": str((report / "papers.csv").resolve()),
    }
    for paper_id in ("paper-1", "paper-2"):
        packet = PaperStudyPacketV2.model_validate_json(
            (output / f"{paper_id}.json").read_text(encoding="utf-8")
        )
        assert packet.schema_version == "2.2"
        assert packet.quality_assessment is not None
        assert packet.quality_score == packet.quality_assessment.f1 == 1.0
        raw_packet = json.loads((output / f"{paper_id}.json").read_text(encoding="utf-8"))
        assert {"status", "requires_reconciliation", "merge_decisions"}.isdisjoint(
            raw_packet
        )
        unit = packet.research_questions[0].study_units[0]
        assert unit.unit_id.startswith("su_")
        assert unit.results[0].result_id.startswith("res_")
        assert unit.claims[0].claim_id.startswith("clm_")
        assert unit.claims[0].inference_basis_ids == [unit.results[0].result_id]
        assert packet.quality_score == 1.0


def test_cli_prepares_bare_pdf_and_writes_only_final_packet(
    tmp_path: Path,
) -> None:
    import fitz

    pdf_path = tmp_path / "formal-paper.pdf"
    with fitz.open() as document:
        page = document.new_page()
        page.insert_text((72, 72), SOURCE_TEXT)
        document.save(pdf_path)
    output = tmp_path / "formal-output"

    summary = run_extract_paper_study(
        [
            "--paper-folder",
            str(tmp_path),
            "--output-folder",
            str(output),
            "--max-chunks",
            "1",
        ],
        provider=FakeJsonProvider(),
    )

    assert summary.succeeded == 1
    assert summary.failed == 0
    assert summary.paper_ids == ("formal-paper",)
    assert (tmp_path / ".odracir" / "chunks" / "formal-paper.json").is_file()
    assert [path.name for path in output.iterdir()] == ["formal-paper.json"]


def test_cli_keeps_byte_identical_pdfs_as_independent_inputs(
    tmp_path: Path,
) -> None:
    import fitz

    first_pdf = tmp_path / "1_14.pdf"
    with fitz.open() as document:
        page = document.new_page()
        page.insert_text((72, 72), SOURCE_TEXT)
        document.save(first_pdf)
    second_pdf = tmp_path / "1_13.pdf"
    shutil.copyfile(first_pdf, second_pdf)
    assert first_pdf.read_bytes() == second_pdf.read_bytes()

    provider = FakeJsonProvider()
    output = tmp_path / "formal-output"
    summary = run_extract_paper_study(
        [
            "--paper-folder",
            str(tmp_path),
            "--output-folder",
            str(output),
            "--max-chunks",
            "1",
        ],
        provider=provider,
    )

    extraction_requests = [request for request in provider.requests if request["request_type"] == "extraction"]
    assert len(extraction_requests) == 2
    assert [request["paper_id"] for request in extraction_requests] == ["1_13", "1_14"]
    assert summary.paper_ids == ("1_13", "1_14")
    assert summary.succeeded == 2
    assert {path.name for path in output.iterdir()} == {"1_13.json", "1_14.json"}


def test_quality_failure_is_isolated_and_does_not_emit_partial_json(
    tmp_path: Path,
) -> None:
    _write_chunk_artifact(tmp_path, "paper-low", chunk_count=2)
    provider = FakeJsonProvider(complete_boundaries=False, miss_core_item=True)
    output = tmp_path / "output"

    summary = run_extract_paper_study(
        [
            "--paper-folder",
            str(tmp_path),
            "--output-folder",
            str(output),
            "--minimum-quality-score",
            "1.0",
            "--max-chunks",
            "1",
        ],
        provider=provider,
    )

    assert summary.succeeded == 0
    assert summary.failed == 1
    assert "paper-low" in summary.failures
    assert list(output.iterdir()) == []
    failure_record = json.loads(
        (tmp_path / "output-report" / "papers.jsonl").read_text(encoding="utf-8")
    )
    assert failure_record["status"] == "failed"
    assert failure_record["quality_score"] < 1.0
    assert failure_record["extraction"]["total_tokens"] == 30
    assert failure_record["quality_judge"]["total_tokens"] == 15
    assert failure_record["error_type"] == "ValueError"


def test_output_folder_must_be_empty_to_prevent_stale_corpus_files(
    tmp_path: Path,
) -> None:
    _write_chunk_artifact(tmp_path, "paper-provisional")
    output = tmp_path / "output"
    output.mkdir()
    (output / "stale.json").write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="output folder must be empty"):
        run_extract_paper_study(
            ["--paper-folder", str(tmp_path), "--output-folder", str(output)],
            provider=FakeJsonProvider(),
        )


def test_quality_judge_repairs_bad_excerpt_and_reports_both_attempts(
    tmp_path: Path,
) -> None:
    _write_chunk_artifact(tmp_path, "paper-repair")
    output = tmp_path / "output"
    summary = run_extract_paper_study(
        ["--paper-folder", str(tmp_path), "--output-folder", str(output)],
        provider=FakeJsonProvider(
            miss_core_item=True,
            invalid_judge_excerpt_once=True,
        ),
    )

    assert summary.succeeded == 1
    record = json.loads(
        (tmp_path / "output-report" / "papers.jsonl").read_text(encoding="utf-8")
    )
    assert record["quality_judge"]["attempts"] == 2
    assert record["quality_judge"]["prompt_tokens"] == 17
    assert record["quality_judge"]["completion_tokens"] == 8
    assert record["missed_core_item_count"] == 1


def test_cli_rejects_an_empty_index_instead_of_reporting_success(
    tmp_path: Path,
) -> None:
    (tmp_path / "odracir_index.json").write_text(
        json.dumps({"papers": []}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="contains no entries"):
        run_extract_paper_study(
            ["--paper-folder", str(tmp_path)],
            provider=FakeJsonProvider(),
        )


def test_repair_prompt_repeats_the_hard_provenance_rule() -> None:
    prompt = _build_repair_prompt(
        original_user_prompt="Original evidence request",
        invalid_payload={"research_questions": []},
        error=ValueError(
            "text_excerpt similarity ratio 0.7000 is below 0.95; "
            "it must be marked paraphrased=True"
        ),
    )

    assert "PROVENANCE SEMANTICS AND HARD RULE" in prompt
    assert "logical proof passage" in prompt
    assert "below-threshold excerpt marked paraphrased=false" in prompt
    assert "always emit either true or false explicitly" in prompt
    assert prompt.count("PROVENANCE SEMANTICS AND HARD RULE") == 2
    assert "FINAL MANDATORY REPAIR CHECK" in prompt
    assert "re-audit every provenance object" in prompt
    assert "every provenance object referencing that chunk" in prompt
    assert 'Scan every "paraphrased": false' in prompt
    assert "PROVENANCE DECISION FEW-SHOTS" in prompt
    assert "near-verbatim punctuation variation" in prompt
    assert "logical restatement with no verbatim source phrase" in prompt
    assert "SILENT SIMILARITY CHECK / SELF-CORRECTION" in prompt
    assert "Do not reveal chain-of-thought" in prompt
    assert "only the final schema-valid JSON object" in prompt


def test_few_shot_punctuation_variation_is_098_and_accepts_false() -> None:
    source = "The intervention increased the response by 20 percent."
    excerpt = "The intervention increased the response by 20 percent,"
    ratio = provenance_text_similarity_ratio(excerpt, source)
    assert ratio == pytest.approx(0.981481, abs=1e-6)
    assert ratio >= PROVENANCE_SIMILARITY_THRESHOLD

    provenance = Provenance.model_validate(
        {
            "chunk_id": "chunk-1",
            "page_start": 1,
            "page_end": 1,
            "text_excerpt": excerpt,
            "paraphrased": False,
        },
        context={PROVENANCE_SOURCE_TEXT_CONTEXT_KEY: {"chunk-1": source}},
    )

    assert provenance.paraphrased is False


def test_few_shot_logical_restatement_requires_true() -> None:
    source = "The intervention increased the response by 20 percent."
    restatement = "Treatment yielded a one-fifth gain in the measured outcome."
    assert provenance_text_similarity_ratio(restatement, source) == pytest.approx(
        0.371681,
        abs=1e-6,
    )
    payload = {
        "chunk_id": "chunk-1",
        "page_start": 1,
        "page_end": 1,
        "text_excerpt": restatement,
        "paraphrased": False,
    }
    context = {PROVENANCE_SOURCE_TEXT_CONTEXT_KEY: {"chunk-1": source}}

    with pytest.raises(ValidationError, match="similarity ratio .* below 0.95"):
        Provenance.model_validate(payload, context=context)

    paraphrased = Provenance.model_validate(
        {**payload, "paraphrased": True},
        context=context,
    )
    assert paraphrased.paraphrased is True


def test_provenance_requires_an_explicit_paraphrased_decision() -> None:
    assert "paraphrased" in Provenance.model_json_schema()["required"]
    with pytest.raises(ValidationError, match="paraphrased"):
        Provenance.model_validate(
            {
                "chunk_id": "chunk-1",
                "page_start": 1,
                "page_end": 1,
                "text_excerpt": "Evidence text.",
            }
        )


def test_provenance_similarity_finds_the_true_best_local_window() -> None:
    excerpt = "".join(f"{value:04x}" for value in range(25))
    decoy = "XXXXXX" + excerpt[6:]
    target_characters = list(excerpt)
    for index in (10, 30, 50, 70, 90):
        target_characters[index] = "Z"
    target = "".join(target_characters)
    source = decoy + "Q" * 20 + target + "W" * 20

    assert provenance_text_similarity_ratio(excerpt, decoy) == pytest.approx(0.94)
    assert provenance_text_similarity_ratio(excerpt, source) == pytest.approx(0.95)


def _extract_fixture_with_provider(
    tmp_path: Path,
    provider: FakeJsonProvider,
    *,
    validation_retries: int = 0,
    chunk_page_start: int = 1,
    chunk_page_end: int = 1,
):
    artifact_path = _write_chunk_artifact(
        tmp_path,
        "paper-correction",
        first_chunk_page_start=chunk_page_start,
        first_chunk_page_end=chunk_page_end,
    )
    artifact = load_chunk_artifact(artifact_path)
    plan = build_extraction_plan(
        artifact,
        source_chunk_artifact=artifact_path,
        max_chunks=1,
    )
    return extract_paper_study(
        artifact,
        plan,
        provider,
        validation_retries=validation_retries,
    )


def test_extraction_corrects_low_similarity_false_to_true_and_audits(
    tmp_path: Path,
) -> None:
    restatement = "Treatment yielded a one-fifth gain in the measured outcome."
    provider = FakeJsonProvider(provenance_excerpt=restatement)

    result = _extract_fixture_with_provider(tmp_path, provider)

    unit = result.packet.research_questions[0].study_units[0]
    assert unit.results[0].provenance.paraphrased is True
    assert unit.claims[0].provenance.paraphrased is True
    assert unit.evidence_spans[0].provenance.paraphrased is True
    assert len(result.provenance_corrections) == 3
    expected_ratio = provenance_text_similarity_ratio(restatement, SOURCE_TEXT)
    assert {item.chunk_id for item in result.provenance_corrections} == {
        "paper-correction-chunk-1"
    }
    assert all(
        item.attempt == 1
        and item.ratio == pytest.approx(expected_ratio)
        and item.from_paraphrased is False
        and item.to_paraphrased is True
        and item.json_path.startswith("$.research_questions[0].study_units[0]")
        and item.json_path.endswith(".provenance.paraphrased")
        for item in result.provenance_corrections
    )
    # The provider-owned payload is not mutated by the deterministic correction.
    source_unit = provider.payloads[0]["research_questions"][0]["study_units"][0]
    assert source_unit["results"][0]["provenance"]["paraphrased"] is False

    report_path = write_extraction_report(
        result,
        tmp_path / "extraction_report.json",
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert len(report["provenance_corrections"]) == 3
    assert report["provenance_corrections"][0]["attempt"] == 1
    assert report["provenance_corrections"][0]["from_paraphrased"] is False
    assert report["provenance_corrections"][0]["to_paraphrased"] is True


def test_extraction_keeps_098_similarity_false_without_correction(
    tmp_path: Path,
) -> None:
    provider = FakeJsonProvider(
        provenance_excerpt="The intervention increased the response by 20 percent,"
    )

    result = _extract_fixture_with_provider(tmp_path, provider)

    provenance = (
        result.packet.research_questions[0]
        .study_units[0]
        .results[0]
        .provenance
    )
    assert provenance.paraphrased is False
    assert result.provenance_corrections == ()


def test_extraction_resets_out_of_chunk_pages_and_audits(
    tmp_path: Path,
) -> None:
    provider = FakeJsonProvider(
        provenance_page_start=0,
        provenance_page_end=5,
    )

    result = _extract_fixture_with_provider(
        tmp_path,
        provider,
        chunk_page_start=1,
        chunk_page_end=3,
    )

    unit = result.packet.research_questions[0].study_units[0]
    provenances = (
        unit.results[0].provenance,
        unit.claims[0].provenance,
        unit.evidence_spans[0].provenance,
    )
    assert all(
        provenance.page_start == 1 and provenance.page_end == 3
        for provenance in provenances
    )
    assert len(result.provenance_page_corrections) == 3
    assert all(
        correction.attempt == 1
        and correction.json_path.startswith(
            "$.research_questions[0].study_units[0]"
        )
        and correction.chunk_id == "paper-correction-chunk-1"
        and correction.from_page_start == 0
        and correction.from_page_end == 5
        and correction.to_page_start == 1
        and correction.to_page_end == 3
        for correction in result.provenance_page_corrections
    )
    report_path = write_extraction_report(
        result,
        tmp_path / "page-correction-report.json",
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["provenance_page_corrections"][0] == {
        "attempt": 1,
        "json_path": (
            "$.research_questions[0].study_units[0].results[0].provenance"
        ),
        "chunk_id": "paper-correction-chunk-1",
        "from_page_start": 0,
        "from_page_end": 5,
        "to_page_start": 1,
        "to_page_end": 3,
    }


def test_extraction_keeps_a_legal_page_subrange(tmp_path: Path) -> None:
    provider = FakeJsonProvider(
        provenance_page_start=2,
        provenance_page_end=2,
    )

    result = _extract_fixture_with_provider(
        tmp_path,
        provider,
        chunk_page_start=1,
        chunk_page_end=3,
    )

    provenance = (
        result.packet.research_questions[0]
        .study_units[0]
        .results[0]
        .provenance
    )
    assert (provenance.page_start, provenance.page_end) == (2, 2)
    assert result.provenance_page_corrections == ()


def test_page_correction_skips_unknown_and_inverted_ranges() -> None:
    payload = {
        "unknown": {
            "chunk_id": "unknown-chunk",
            "page_start": 0,
            "page_end": 9,
            "text_excerpt": "Unknown source.",
            "paraphrased": True,
        },
        "inverted": {
            "chunk_id": "known-chunk",
            "page_start": 3,
            "page_end": 2,
            "text_excerpt": "Known source.",
            "paraphrased": True,
        },
    }

    corrected, text_corrections, page_corrections, method_corrections = (
        _apply_safe_provenance_corrections(
            payload,
            source_texts={"known-chunk": "Known source."},
            source_page_ranges={"known-chunk": (1, 4)},
            attempt=1,
        )
    )

    assert corrected == payload
    assert text_corrections == ()
    assert page_corrections == ()
    assert method_corrections == ()


def test_extraction_never_changes_explicit_true_to_false(tmp_path: Path) -> None:
    provider = FakeJsonProvider(
        provenance_excerpt=SOURCE_TEXT,
        provenance_paraphrased=True,
    )

    result = _extract_fixture_with_provider(tmp_path, provider)

    provenance = (
        result.packet.research_questions[0]
        .study_units[0]
        .results[0]
        .provenance
    )
    assert provenance.paraphrased is True
    assert result.provenance_corrections == ()


def test_repair_prompt_uses_the_safely_corrected_payload(tmp_path: Path) -> None:
    class RepairProvider(FakeJsonProvider):
        repair_prompt: str | None = None

        def complete_json(
            self,
            *,
            system_prompt: str,
            user_prompt: str,
            max_tokens: int,
        ) -> JsonCompletionResult:
            if not self.payloads:
                completion = super().complete_json(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    max_tokens=max_tokens,
                )
                completion.payload["unexpected"] = "force a repair"
                return completion

            self.repair_prompt = user_prompt
            repaired = json.loads(json.dumps(self.payloads[0]))
            repaired.pop("unexpected")
            unit = repaired["research_questions"][0]["study_units"][0]
            unit["results"][0]["provenance"]["paraphrased"] = True
            unit["claims"][0]["provenance"]["paraphrased"] = True
            unit["evidence_spans"][0]["provenance"]["paraphrased"] = True
            return JsonCompletionResult(
                payload=repaired,
                usage={"prompt_tokens": 1, "completion_tokens": 1},
                finish_reason="stop",
            )

    provider = RepairProvider(
        provenance_excerpt="Treatment yielded a one-fifth gain in the measured outcome."
    )

    result = _extract_fixture_with_provider(
        tmp_path,
        provider,
        validation_retries=1,
    )

    assert result.attempts == 2
    assert {correction.attempt for correction in result.provenance_corrections} == {1}
    assert provider.repair_prompt is not None
    invalid_json = provider.repair_prompt.split(
        "Previous invalid JSON:\n",
        1,
    )[1].split("\n\nOriginal evidence request:", 1)[0]
    invalid_payload = json.loads(invalid_json)
    invalid_unit = invalid_payload["research_questions"][0]["study_units"][0]
    assert invalid_unit["results"][0]["provenance"]["paraphrased"] is True
    assert invalid_unit["claims"][0]["provenance"]["paraphrased"] is True
    assert invalid_unit["evidence_spans"][0]["provenance"]["paraphrased"] is True


def test_extraction_does_not_fill_missing_paraphrased_decision(
    tmp_path: Path,
) -> None:
    provider = FakeJsonProvider(provenance_paraphrased=None)

    with pytest.raises(
        ValueError,
        match="Model output failed v2 validation after 1 attempts",
    ) as exc_info:
        _extract_fixture_with_provider(tmp_path, provider)
    assert "paraphrased" in str(exc_info.value)


def test_duplicate_method_ids_are_renamed_and_packet_is_provisional(
    tmp_path: Path,
) -> None:
    class DuplicateMethodProvider(FakeJsonProvider):
        def complete_json(
            self,
            *,
            system_prompt: str,
            user_prompt: str,
            max_tokens: int,
        ) -> JsonCompletionResult:
            completion = super().complete_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=max_tokens,
            )
            unit = completion.payload["research_questions"][0]["study_units"][0]
            unit["methods"] = [
                {
                    "method_id": "METHOD",
                    "name": "First protocol",
                    "protocol_description": "First method content.",
                },
                {
                    "method_id": "METHOD",
                    "name": "Second protocol",
                    "protocol_description": "Second method content.",
                },
                {
                    "method_id": "METHOD",
                    "name": "Third protocol",
                    "protocol_description": "Third method content.",
                },
            ]
            return completion

    result = _extract_fixture_with_provider(tmp_path, DuplicateMethodProvider())

    methods = result.packet.research_questions[0].study_units[0].methods
    assert [method.method_id for method in methods] == [
        "METHOD",
        "METHOD__dup2",
        "METHOD__dup3",
    ]
    assert [method.protocol_description for method in methods] == [
        "First method content.",
        "Second method content.",
        "Third method content.",
    ]
    assert result.packet.status == "provisional"
    assert result.packet.requires_reconciliation is True
    assert {warning.code for warning in result.packet.validation_warnings} == {
        "extraction.duplicate_method_id_renamed"
    }
    assert [audit.from_method_id for audit in result.method_id_corrections] == [
        "METHOD",
        "METHOD",
    ]
    assert [audit.to_method_id for audit in result.method_id_corrections] == [
        "METHOD__dup2",
        "METHOD__dup3",
    ]

    report_path = write_extraction_report(result, tmp_path / "method-report.json")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["extraction_mode"] == "hierarchical"
    assert report["method_id_corrections"][0] == {
        "attempt": 1,
        "json_path": (
            "$.research_questions[0].study_units[0].methods[1].method_id"
        ),
        "from": "METHOD",
        "to": "METHOD__dup2",
    }
    assert MethodIdCorrectionAudit.model_validate(
        report["method_id_corrections"][0]
    ) == result.method_id_corrections[0]


def test_duplicate_result_ids_trigger_one_strict_flat_fallback(
    tmp_path: Path,
) -> None:
    class FlatFallbackProvider(FakeJsonProvider):
        prompts: list[str]

        def __init__(self) -> None:
            super().__init__()
            self.prompts = []

        def complete_json(
            self,
            *,
            system_prompt: str,
            user_prompt: str,
            max_tokens: int,
        ) -> JsonCompletionResult:
            self.prompts.append(user_prompt)
            if len(self.prompts) == 1:
                completion = super().complete_json(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    max_tokens=max_tokens,
                )
                unit = completion.payload["research_questions"][0]["study_units"][0]
                unit["results"].append(json.loads(json.dumps(unit["results"][0])))
                return completion

            assert "STRUCTURAL FLAT FALLBACK EXTRACTION" in user_prompt
            flattened = json.loads(json.dumps(self.payloads[0]))
            question = flattened["research_questions"][0]
            unit = question["study_units"][0]
            unit["name"] = "Provisional flat extraction"
            unit["results"] = [unit["results"][0]]
            unit["datasets"] = []
            unit["methods"] = []
            return JsonCompletionResult(
                payload=flattened,
                usage={"prompt_tokens": 3, "completion_tokens": 4},
                finish_reason="stop",
            )

    provider = FlatFallbackProvider()
    result = _extract_fixture_with_provider(tmp_path, provider)

    assert len(provider.prompts) == 2
    assert "STRUCTURAL FLAT FALLBACK EXTRACTION" not in provider.prompts[0]
    assert "STRUCTURAL FLAT FALLBACK EXTRACTION" in provider.prompts[1]
    assert result.attempts == 2
    assert result.extraction_mode == "flat_fallback"
    assert result.packet.status == "provisional"
    assert result.packet.requires_reconciliation is True
    assert [warning.code for warning in result.packet.validation_warnings] == [
        "extraction.flat_fallback"
    ]
    unit = result.packet.research_questions[0].study_units[0]
    assert unit.name == "Provisional flat extraction"
    assert len(result.packet.research_questions) == 1
    assert len(result.packet.research_questions[0].study_units) == 1
    assert len(unit.results) == 1
    assert unit.claims[0].inference_basis_ids == [unit.results[0].result_id]


def test_unknown_provenance_chunk_never_uses_flat_fallback(tmp_path: Path) -> None:
    class PromptRecordingProvider(FakeJsonProvider):
        def __init__(self) -> None:
            super().__init__(provenance_chunk_id="unknown-chunk")
            self.prompts: list[str] = []

        def complete_json(
            self,
            *,
            system_prompt: str,
            user_prompt: str,
            max_tokens: int,
        ) -> JsonCompletionResult:
            self.prompts.append(user_prompt)
            return super().complete_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=max_tokens,
            )

    provider = PromptRecordingProvider()
    with pytest.raises(ValueError, match="Model output failed v2 validation"):
        _extract_fixture_with_provider(tmp_path, provider)

    assert len(provider.prompts) == 1
    assert "STRUCTURAL FLAT FALLBACK EXTRACTION" not in provider.prompts[0]


def test_transient_invalid_json_provider_failure_retries_without_warning(
    tmp_path: Path,
) -> None:
    class TransientProvider(FakeJsonProvider):
        calls = 0

        def complete_json(
            self,
            *,
            system_prompt: str,
            user_prompt: str,
            max_tokens: int,
        ) -> JsonCompletionResult:
            self.calls += 1
            if self.calls == 1:
                raise ValueError("DeepSeek returned invalid JSON content")
            return super().complete_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=max_tokens,
            )

    provider = TransientProvider()
    result = _extract_fixture_with_provider(
        tmp_path,
        provider,
        validation_retries=1,
    )

    assert provider.calls == 2
    assert result.attempts == 2
    assert result.extraction_mode == "hierarchical"
    assert result.packet.status == "accepted"
    assert result.packet.requires_reconciliation is False
    assert result.packet.validation_warnings == []
