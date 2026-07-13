from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from odracir.paper_study.assembly import (
    assemble_scheduler_result,
    write_corpus_assembly,
)
from odracir.paper_study.extraction import JsonCompletionResult
from odracir.paper_study.pipeline import (
    PaperStudyPipeline,
    PaperStudyPipelineConfig,
    PipelineRunManifest,
    build_run_manifest,
    write_run_manifest,
)
from odracir.paper_study.planning import ChunkArtifact, SourceChunk
from odracir.paper_study.recovery import (
    Stage3RecoveryConfig,
    recover_stage3_run,
)
from odracir.paper_study.scheduler import (
    PaperIndexEntry,
    run_paper_study_scheduler,
)


class FixtureProvider:
    provider_name = "fixture"
    model = "fixture-json"

    def __init__(
        self,
        *,
        fail_paper_ids: set[str] | None = None,
        invalid_basis: bool = False,
    ) -> None:
        self.fail_paper_ids = fail_paper_ids or set()
        self.invalid_basis = invalid_basis
        self.requests: list[dict[str, Any]] = []

    def complete_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
    ) -> JsonCompletionResult:
        source = json.loads(user_prompt.split("\n", 1)[1])
        paper_id = source["paper_id"]
        self.requests.append(source)
        if paper_id in self.fail_paper_ids:
            raise RuntimeError(f"intentional failure for {paper_id}")
        chunk = source["chunks"][0]
        provenance = {
            "chunk_id": chunk["chunk_id"],
            "page_start": chunk["page_start"],
            "page_end": chunk["page_end"],
            "text_excerpt": chunk["text"],
            "paraphrased": False,
        }
        return JsonCompletionResult(
            payload={
                "research_questions": [
                    {
                        "question_id": "RQ1",
                        "statement": "Does treatment alter the measured response?",
                        "study_units": [
                            {
                                "unit_id": "SU1",
                                "name": "Perturbation experiment",
                                "experiments_or_tasks": [
                                    "Compare treated and untreated samples."
                                ],
                                "results": [
                                    {
                                        "result_id": "R1",
                                        "metric_name": "Response",
                                        "value_raw_text": chunk["text"],
                                        "provenance": provenance,
                                    }
                                ],
                                "claims": [
                                    {
                                        "claim_id": "C1",
                                        "statement": chunk["text"],
                                        "polarity": "positive",
                                        "inference_basis_ids": [
                                            "missing-result"
                                            if self.invalid_basis
                                            else "R1"
                                        ],
                                        "provenance": provenance,
                                    }
                                ],
                                "evidence_spans": [
                                    {
                                        "span_id": "E1",
                                        "content": chunk["text"],
                                        "provenance": provenance,
                                    }
                                ],
                            }
                        ],
                    }
                ],
                "limitations_and_boundaries": [
                    "The experiment used one model system and may not generalize.",
                    "The molecular mechanism was not directly tested in this study.",
                    "Long-term outcomes beyond the observation period remain unknown.",
                ],
            },
            usage={"prompt_tokens": 10, "completion_tokens": 20},
            finish_reason="stop",
        )


def _write_chunk(root: Path, paper_id: str, text: str) -> Path:
    chunk = SourceChunk(
        chunk_id=f"{paper_id}-chunk-1",
        ordinal=1,
        section_hint="results",
        page_start=1,
        page_end=1,
        char_count=len(text),
        token_estimate=8,
        content_sha256=f"content-{paper_id}",
        text=text,
    )
    artifact = ChunkArtifact(
        schema_version="0.1",
        paper_id=paper_id,
        source_file=f"{paper_id}.pdf",
        source_sha256=f"source-{paper_id}",
        text_artifact=f".odracir/texts/{paper_id}.json",
        text_artifact_sha256=f"text-{paper_id}",
        chunker="fixture",
        chunker_version="1.0",
        chunked_at="2026-01-01T00:00:00Z",
        chunk_count=1,
        chunks=[chunk],
    )
    path = root / ".odracir" / "chunks" / f"{paper_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(artifact.model_dump_json(by_alias=True), encoding="utf-8")
    return path


def _make_partial_run(tmp_path: Path) -> tuple[Path, PipelineRunManifest]:
    output_root = tmp_path / "formal-output"
    entries = (
        PaperIndexEntry(
            paper_id="paper-good",
            source_path=str(
                _write_chunk(
                    tmp_path,
                    "paper-good",
                    "Treatment A increased the measured response.",
                ).resolve()
            ),
        ),
        PaperIndexEntry(
            paper_id="paper-failed",
            source_path=str(
                _write_chunk(
                    tmp_path,
                    "paper-failed",
                    "Treatment B decreased the measured response.",
                ).resolve()
            ),
        ),
    )
    pipeline = PaperStudyPipeline(
        FixtureProvider(fail_paper_ids={"paper-failed"}),
        PaperStudyPipelineConfig(
            output_root=str(output_root),
            max_chunks=1,
            validation_retries=0,
        ),
    )
    scheduler = run_paper_study_scheduler(entries, pipeline, batch_size=2)
    assembly = assemble_scheduler_result(scheduler, corpus_id="fixture-corpus")
    assembly_paths = write_corpus_assembly(assembly, output_root)
    manifest = build_run_manifest(
        paper_folder=tmp_path,
        pipeline=pipeline,
        scheduler_result=scheduler,
    )
    manifest = PipelineRunManifest.model_validate(
        {
            **manifest.model_dump(mode="python"),
            "assembly_manifest_path": assembly_paths["assembly_manifest"],
            "global_state_ledger_path": assembly_paths["ledger"],
            "delivery_paths": {
                key.removeprefix("delivery:"): value
                for key, value in assembly_paths.items()
                if key.startswith("delivery:")
            },
        }
    )
    manifest_path = output_root / "run_manifest.json"
    write_run_manifest(manifest, manifest_path)
    return manifest_path, manifest


def test_recovery_appends_batch_and_rebuilds_ledger_and_deliveries(
    tmp_path: Path,
) -> None:
    manifest_path, initial = _make_partial_run(tmp_path)
    initial_bytes = manifest_path.read_bytes()
    initial_assembly = json.loads(
        Path(initial.assembly_manifest_path or "").read_text(encoding="utf-8")
    )
    old_good_delivery = json.loads(
        Path(initial.delivery_paths["paper-good"]).read_text(encoding="utf-8")
    )
    old_snapshots = [
        json.loads(Path(path).read_text(encoding="utf-8"))
        for path in initial_assembly["snapshot_paths"]
    ]
    provider = FixtureProvider()
    recovered_root = tmp_path / "recovered-output"

    result = recover_stage3_run(
        manifest_path,
        provider,
        output_root=recovered_root,
        config=Stage3RecoveryConfig(
            validation_retries=0,
        ),
    )

    assert result.recovery_manifest.status == "completed"
    assert result.recovery_manifest.attempted_paper_ids == ("paper-failed",)
    assert result.recovery_manifest.succeeded_paper_ids == ("paper-failed",)
    assert result.final_manifest is not None
    final = PipelineRunManifest.model_validate_json(
        Path(result.recovery_manifest.final_run_manifest_path or "").read_text(
            encoding="utf-8"
        )
    )
    assert manifest_path.read_bytes() == initial_bytes
    assert final.output_root == str(recovered_root.resolve())
    assert final.succeeded == 2
    assert final.failed == 0
    assert final.ordered_paper_ids == initial.ordered_paper_ids
    assert len(final.batches) == 2
    assert final.batches[: len(initial.batches)] == initial.batches
    assert final.batches[1].batch_number == initial.final_context.through_batch + 1
    assert final.batches[1].input_context == initial.final_context
    assert set(final.delivery_paths) == {"paper-good", "paper-failed"}
    ledger = json.loads(
        Path(final.global_state_ledger_path or "").read_text(encoding="utf-8")
    )
    assert ledger["revision"] == 2
    assert len(provider.requests) == 1
    assert provider.requests[0]["paper_id"] == "paper-failed"
    assert provider.requests[0]["prior_global_context"]["through_batch"] == 1

    preserved = Path(result.recovery_manifest.preserved_initial_manifest_path)
    assert preserved.read_bytes() == initial_bytes
    preserved_manifest = PipelineRunManifest.model_validate_json(
        preserved.read_text(encoding="utf-8")
    )
    assert preserved_manifest.failed == 1
    assert Path(result.recovery_manifest_path).is_file()
    assert Path(result.recovery_manifest.final_run_manifest_path or "").is_file()

    new_assembly = json.loads(
        Path(final.assembly_manifest_path or "").read_text(encoding="utf-8")
    )
    new_snapshots = [
        json.loads(Path(path).read_text(encoding="utf-8"))
        for path in new_assembly["snapshot_paths"]
    ]
    assert new_snapshots[: len(old_snapshots)] == old_snapshots
    assert new_snapshots[-1]["parent_digest"] == (
        result.recovery_manifest.parent_ledger_digest
    )
    assert result.recovery_manifest.parent_ledger_revision == 1
    new_good_delivery = json.loads(
        Path(final.delivery_paths["paper-good"]).read_text(encoding="utf-8")
    )
    assert new_good_delivery["packet"] == old_good_delivery["packet"]
    assert new_good_delivery["packet_digest"] == old_good_delivery["packet_digest"]
    assert (
        new_good_delivery["generation_context"]
        == old_good_delivery["generation_context"]
    )
    assert {
        alignment["output_ledger_digest"]
        for alignment in new_good_delivery["alignments"]
    } != {
        alignment["output_ledger_digest"]
        for alignment in old_good_delivery["alignments"]
    }

    recovered_packet = json.loads(
        (
            Path(final.output_root)
            / "paper-failed"
            / "PaperStudyPacketV2.json"
        ).read_text(encoding="utf-8")
    )
    unit = recovered_packet["research_questions"][0]["study_units"][0]
    assert unit["claims"][0]["inference_basis_ids"] == [
        unit["results"][0]["result_id"]
    ]


def test_recovery_does_not_guess_a_missing_claim_result_link(
    tmp_path: Path,
) -> None:
    manifest_path, _ = _make_partial_run(tmp_path)
    initial_bytes = manifest_path.read_bytes()
    recovered_root = tmp_path / "failed-recovery-output"

    result = recover_stage3_run(
        manifest_path,
        FixtureProvider(invalid_basis=True),
        output_root=recovered_root,
        config=Stage3RecoveryConfig(
            max_chunks=1,
            validation_retries=0,
        ),
    )

    assert result.recovery_manifest.status == "failed"
    assert result.recovery_manifest.failed_paper_ids == ("paper-failed",)
    assert "outside its StudyUnit" in result.recovery_manifest.failure_messages[
        "paper-failed"
    ]
    assert result.final_manifest is None
    assert manifest_path.read_bytes() == initial_bytes
    assert Path(result.recovery_manifest.preserved_initial_manifest_path).read_bytes() == (
        initial_bytes
    )


def test_recovery_refuses_to_write_into_the_parent_run(tmp_path: Path) -> None:
    manifest_path, initial = _make_partial_run(tmp_path)
    provider = FixtureProvider()

    with pytest.raises(ValueError, match="separate new directory"):
        recover_stage3_run(
            manifest_path,
            provider,
            output_root=initial.output_root,
            config=Stage3RecoveryConfig(validation_retries=0),
        )

    assert provider.requests == []
