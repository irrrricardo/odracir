from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from odracir.cli import main
from odracir.paper_study.ablation_evidence import (
    CHUNK_DOCUMENT_SCHEMA,
    LOCATOR_CROSSWALK_SCHEMA,
    export_ablation_evidence_bundle,
)
from odracir.paper_study.ingestion import extract_pdf_page_chunks
from odracir.paper_study.models import (
    Claim,
    EvidenceSpan,
    PaperStudyPacketV2,
    Provenance,
    ResearchQuestion,
    ResultObservation,
    StudyUnit,
)


fitz = pytest.importorskip("fitz")


def _write_source_pair(
    root: Path,
    horizon: str,
    group: str,
    paper_id: str,
) -> tuple[Path, Path]:
    corpus_group = root / "corpus" / horizon / group
    packet_group = root / "packets" / horizon / group
    corpus_group.mkdir(parents=True, exist_ok=True)
    packet_group.mkdir(parents=True, exist_ok=True)
    pdf_path = corpus_group / f"{paper_id}.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text(
        (72, 72),
        "The intervention increased the measured response by twenty percent. "
        "This exact statement supports the reported finding.",
    )
    document.save(pdf_path)
    document.close()
    source_sha256, _pages, chunks = extract_pdf_page_chunks(pdf_path)
    chunk = chunks[0]
    excerpt = "The intervention increased the measured response by twenty percent."
    provenance = Provenance(
        chunk_id=chunk.chunk_id,
        page_start=1,
        page_end=1,
        text_excerpt=excerpt,
        paraphrased=False,
    )
    packet = PaperStudyPacketV2(
        paper_id=paper_id,
        metadata={
            "source_file": pdf_path.name,
            "source_sha256": source_sha256,
            "source_chunk_schema_version": "0.1",
        },
        quality_score=1.0,
        coverage_ledger={chunk.chunk_id: "extracted"},
        research_questions=[
            ResearchQuestion(
                question_id="Q1",
                statement="Did the intervention change the response?",
                study_units=[
                    StudyUnit(
                        unit_id="U1",
                        name="Primary experiment",
                        experiments_or_tasks=["Measure the response"],
                        results=[
                            ResultObservation(
                                result_id="R1",
                                metric_name="response",
                                value_raw_text="The response increased by twenty percent.",
                                provenance=provenance,
                            )
                        ],
                        claims=[
                            Claim(
                                claim_id="C1",
                                statement="The intervention increased the response.",
                                polarity="positive",
                                inference_basis_ids=["R1"],
                                provenance=provenance,
                            )
                        ],
                        evidence_spans=[
                            EvidenceSpan(
                                span_id="E1",
                                content=excerpt,
                                provenance=provenance,
                            )
                        ],
                    )
                ],
            )
        ],
    )
    packet_path = packet_group / f"{paper_id}.json"
    packet_path.write_text(
        json.dumps(packet.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return pdf_path, packet_path


def _load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_export_writes_namespaced_lab_contract(tmp_path: Path) -> None:
    _write_source_pair(tmp_path, "long", "1", "1_1")
    output = tmp_path / "bundle"

    summary = export_ablation_evidence_bundle(
        tmp_path / "corpus",
        tmp_path / "packets",
        output,
        horizon="long",
        group="1",
    )

    assert summary.paper_count == 1
    packet = _load(output / "long/1/packets/1_1_long.json")
    chunks = _load(output / "long/1/evidence/chunks/1_1_long.json")
    crosswalk = _load(output / "long/1/evidence/crosswalks/1_1_long.json")
    assert packet["paper_id"] == chunks["paper_id"] == crosswalk["paper_id"] == "1_1_long"
    assert packet["metadata"]["ablation_original_paper_id"] == "1_1"
    assert chunks["schema"] == CHUNK_DOCUMENT_SCHEMA
    assert crosswalk["schema"] == LOCATOR_CROSSWALK_SCHEMA
    assert crosswalk["mode"] == "exact_chunk_id"
    assert crosswalk["provenance_reference_count"] == 3
    assert all(
        item["upstream_chunk_id"] == item["resolved_chunk_id"]
        for item in crosswalk["bindings"]
    )
    clean = {key: value for key, value in crosswalk.items() if key != "digest"}
    encoded = json.dumps(
        clean,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    assert crosswalk["digest"] == f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def test_horizon_suffix_resolves_long_short_id_collision(tmp_path: Path) -> None:
    _write_source_pair(tmp_path, "long", "1", "1_1")
    _write_source_pair(tmp_path, "short", "1", "1_1")
    output = tmp_path / "bundle"

    summary = export_ablation_evidence_bundle(
        tmp_path / "corpus",
        tmp_path / "packets",
        output,
    )

    assert summary.paper_count == 2
    assert (output / "long/1/packets/1_1_long.json").is_file()
    assert (output / "short/1/packets/1_1_short.json").is_file()


def test_export_fails_closed_on_chunk_namespace_drift(tmp_path: Path) -> None:
    _pdf, packet_path = _write_source_pair(tmp_path, "long", "1", "1_1")
    packet = _load(packet_path)
    packet["coverage_ledger"] = {"stale-chunk-id": "extracted"}
    packet_path.write_text(json.dumps(packet), encoding="utf-8")

    with pytest.raises(ValueError, match="namespace does not close"):
        export_ablation_evidence_bundle(
            tmp_path / "corpus",
            tmp_path / "packets",
            tmp_path / "bundle",
        )
    assert not (tmp_path / "bundle").exists()


def test_cli_exports_one_selected_paper_without_provider(tmp_path: Path, capsys) -> None:
    _write_source_pair(tmp_path, "long", "1", "1_1")
    output = tmp_path / "bundle"

    status = main(
        [
            "export-ablation-evidence",
            "--corpus-root",
            str(tmp_path / "corpus"),
            "--packets-root",
            str(tmp_path / "packets"),
            "--output-folder",
            str(output),
            "--horizon",
            "long",
            "--group",
            "1",
            "--paper-id",
            "1_1",
        ]
    )

    assert status == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["paper_count"] == 1
    assert (output / "long/1/evidence/crosswalks/1_1_long.json").is_file()
