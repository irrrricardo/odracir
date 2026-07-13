from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from odracir.paper_study.models import (
    Claim,
    PaperStudyPacketV2,
    Provenance,
    ResearchQuestion,
    ResultObservation,
    StudyUnit,
)
from odracir.paper_study.planning import ChunkArtifact, SourceChunk
from odracir.paper_study.recon import build_corpus_manifest
from odracir.paper_study.scheduler import (
    BatchAssignment,
    GlobalContext,
    MedoidBatcher,
    PaperIndexEntry,
    StrategicBatchPlan,
    load_paper_index,
    run_paper_study_scheduler,
)


def _packet(paper_id: str, *, claim_suffix: str = "finding") -> PaperStudyPacketV2:
    provenance = Provenance(
        chunk_id=f"{paper_id}-chunk-1",
        page_start=1,
        page_end=1,
        text_excerpt=f"Evidence for {paper_id}.",
        paraphrased=False,
    )
    result_id = f"{paper_id}-result-1"
    return PaperStudyPacketV2(
        paper_id=paper_id,
        research_questions=[
            ResearchQuestion(
                question_id=f"{paper_id}-question-1",
                statement="What was observed?",
                study_units=[
                    StudyUnit(
                        unit_id=f"{paper_id}-unit-1",
                        name="Primary experiment",
                        results=[
                            ResultObservation(
                                result_id=result_id,
                                metric_name="response",
                                value_raw_text="The response increased.",
                                provenance=provenance,
                            )
                        ],
                        claims=[
                            Claim(
                                claim_id=f"{paper_id}-claim-1",
                                statement=f"{paper_id} key {claim_suffix}.",
                                polarity="positive",
                                inference_basis_ids=[result_id],
                                provenance=provenance,
                            )
                        ],
                    )
                ],
            )
        ],
    )


def _routing_artifact(paper_id: str, text: str) -> ChunkArtifact:
    source_text = text * 3
    chunk = SourceChunk(
        chunk_id=f"{paper_id}-chunk-1",
        ordinal=1,
        section_hint="results",
        page_start=1,
        page_end=1,
        char_count=len(source_text),
        token_estimate=50,
        content_sha256=f"content-{paper_id}",
        text=source_text,
    )
    return ChunkArtifact(
        schema_version="0.1",
        paper_id=paper_id,
        source_file=f"{paper_id}.pdf",
        source_sha256=f"source-{paper_id}",
        text_artifact=f"texts/{paper_id}.json",
        text_artifact_sha256=f"text-{paper_id}",
        chunker="scheduler-fixture",
        chunker_version="1.0",
        chunked_at="2026-07-13T00:00:00Z",
        chunk_count=1,
        chunks=[chunk],
    )


@pytest.mark.parametrize("collection_key", ["papers", "items"])
def test_load_object_index_sorts_dates_and_resolves_paths(
    tmp_path: Path,
    collection_key: str,
) -> None:
    paper_folder = tmp_path / "papers"
    index_path = tmp_path / f"{collection_key}.json"
    index_path.write_text(
        json.dumps(
            {
                collection_key: [
                    {
                        "id": "late",
                        "path": "late.json",
                        "publication_date": "2021-05",
                    },
                    {"paper_id": "undated", "chunk_path": "undated.json"},
                    {
                        "paper_id": "early",
                        "chunk_artifact": "nested/early.json",
                        "published_at": None,
                        "year": 2019,
                        "chunking_status": "done",
                        "legacy_field_not_in_the_v2_contract": ["ignored"],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    entries = load_paper_index(index_path, paper_folder=paper_folder)

    assert [entry.paper_id for entry in entries] == ["early", "late", "undated"]
    assert entries[0].published_at == datetime(2019, 1, 1, tzinfo=timezone.utc)
    assert entries[1].published_at == datetime(2021, 5, 1, tzinfo=timezone.utc)
    assert entries[2].published_at is None
    assert entries[0].source_path == str((paper_folder / "nested/early.json").resolve())


def test_load_list_index_accepts_path_entries(tmp_path: Path) -> None:
    index_path = tmp_path / "index.json"
    index_path.write_text(json.dumps(["b.json", "a.json"]), encoding="utf-8")

    entries = load_paper_index(index_path)

    assert [entry.paper_id for entry in entries] == ["a", "b"]
    assert entries[0].source_path == str((tmp_path / "a.json").resolve())


def test_batches_share_frozen_prior_context_and_pass_it_to_next_batch() -> None:
    entries = [
        PaperIndexEntry(
            paper_id="paper-3",
            source_path="/papers/3.json",
            published_at=datetime(2022, 1, 1, tzinfo=timezone.utc),
        ),
        PaperIndexEntry(
            paper_id="paper-1",
            source_path="/papers/1.json",
            published_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
        ),
        PaperIndexEntry(
            paper_id="paper-2",
            source_path="/papers/2.json",
            published_at=datetime(2021, 1, 1, tzinfo=timezone.utc),
        ),
    ]
    received: dict[str, GlobalContext] = {}

    def processor(entry: PaperIndexEntry, context: GlobalContext) -> PaperStudyPacketV2:
        received[entry.paper_id] = context
        return _packet(entry.paper_id)

    result = run_paper_study_scheduler(entries, processor, batch_size=2)

    assert [entry.paper_id for entry in result.ordered_entries] == [
        "paper-1",
        "paper-2",
        "paper-3",
    ]
    assert len(result.batches) == 2
    assert received["paper-1"].findings == ()
    assert received["paper-2"].findings == ()
    assert received["paper-1"].digest() == received["paper-2"].digest()
    assert [item.paper_id for item in received["paper-3"].findings] == [
        "paper-1",
        "paper-2",
    ]
    assert received["paper-3"].through_batch == 1
    assert result.final_context.through_batch == 2
    assert [item.paper_id for item in result.final_context.findings] == [
        "paper-1",
        "paper-2",
        "paper-3",
    ]
    assert "treat them as context, not as evidence" in received[
        "paper-3"
    ].render_for_prompt()


def test_processor_errors_are_audited_and_do_not_enter_context() -> None:
    entries = [
        PaperIndexEntry(paper_id=paper_id, source_path=f"/papers/{paper_id}.json")
        for paper_id in ("paper-1", "paper-2", "paper-3")
    ]
    received: dict[str, GlobalContext] = {}

    def processor(entry: PaperIndexEntry, context: GlobalContext) -> PaperStudyPacketV2:
        received[entry.paper_id] = context
        if entry.paper_id == "paper-2":
            raise RuntimeError("synthetic extraction failure")
        return _packet(entry.paper_id)

    result = run_paper_study_scheduler(entries, processor, batch_size=1)

    failed = result.batches[1].papers[0]
    assert failed.status == "failed"
    assert failed.packet is None
    assert failed.error_type == "RuntimeError"
    assert failed.error_message == "synthetic extraction failure"
    assert [item.paper_id for item in received["paper-3"].findings] == ["paper-1"]
    assert [packet.paper_id for packet in result.packets] == ["paper-1", "paper-3"]
    assert [item.paper_id for item in result.final_context.findings] == [
        "paper-1",
        "paper-3",
    ]


def test_context_bound_is_audited_and_keeps_most_recent_findings() -> None:
    entries = [
        PaperIndexEntry(paper_id=paper_id, source_path=f"/papers/{paper_id}.json")
        for paper_id in ("paper-1", "paper-2", "paper-3")
    ]

    result = run_paper_study_scheduler(
        entries,
        lambda entry, context: _packet(entry.paper_id),
        batch_size=1,
        max_context_findings=2,
    )

    assert [item.paper_id for item in result.final_context.findings] == [
        "paper-2",
        "paper-3",
    ]
    assert result.final_context.dropped_finding_count == 1


def test_medoid_batcher_seeds_diverse_skeletons_then_interleaves_routes() -> None:
    bio_text = (
        "Knockdown of the receptor reduced protein expression in cultured cells. "
        "The untreated control showed a stable molecular response. "
    )
    method_text = (
        "The software pipeline used cross-validation, a benchmark dataset, an "
        "ablation study, runtime, and prediction accuracy. "
    )
    conflict_text = (
        "However, receptor knockdown did not reduce expression. In contrast, the "
        "untreated control increased the molecular response. "
    )
    manifest = build_corpus_manifest(
        (
            _routing_artifact("bio-a", bio_text),
            _routing_artifact("bio-b", bio_text),
            _routing_artifact("method-a", method_text),
            _routing_artifact("method-b", method_text),
            _routing_artifact("conflict", conflict_text),
        ),
        cluster_distance_threshold=0.0,
    )

    first = MedoidBatcher().plan(manifest, batch_size=2)
    second = MedoidBatcher().plan(manifest, batch_size=2)

    assert first == second
    assert first.manifest_digest == manifest.digest()
    assert first.seed_paper_ids == ("bio-a", "conflict", "method-a")
    assert first.batches == (
        ("bio-a", "conflict"),
        ("method-a",),
        ("bio-b", "method-b"),
    )
    assert [assignment.role for assignment in first.assignments] == [
        "seed_medoid",
        "seed_medoid",
        "seed_medoid",
        "skeleton_neighbor",
        "conflict_interleave",
    ]
    assert [cluster.member_paper_ids for cluster in manifest.clusters] == [
        ("bio-a", "bio-b"),
        ("conflict",),
        ("method-a", "method-b"),
    ]
    assert all(
        assignment.role == "seed_medoid" for assignment in first.assignments[:3]
    )


def test_strategic_plan_controls_batch_boundaries_and_context() -> None:
    entries = [
        PaperIndexEntry(
            paper_id=paper_id,
            source_path=f"/papers/{paper_id}.json",
            published_at=datetime(year, 1, 1, tzinfo=timezone.utc),
        )
        for paper_id, year in (("early", 2020), ("middle", 2021), ("late", 2022))
    ]
    plan = StrategicBatchPlan(
        policy_name="fixture",
        manifest_digest="sha256:fixture",
        batch_size=2,
        seed_paper_ids=("late", "early"),
        assignments=(
            BatchAssignment(
                paper_id="late",
                batch_number=1,
                position_in_batch=1,
                role="seed_medoid",
                anchor_paper_id="late",
                skeleton_similarity_ppm=1_000_000,
            ),
            BatchAssignment(
                paper_id="early",
                batch_number=1,
                position_in_batch=2,
                role="seed_medoid",
                anchor_paper_id="early",
                skeleton_similarity_ppm=1_000_000,
            ),
            BatchAssignment(
                paper_id="middle",
                batch_number=2,
                position_in_batch=1,
                role="skeleton_neighbor",
                anchor_paper_id="late",
                skeleton_similarity_ppm=500_000,
            ),
        ),
    )
    received: dict[str, GlobalContext] = {}

    def processor(entry: PaperIndexEntry, context: GlobalContext) -> PaperStudyPacketV2:
        received[entry.paper_id] = context
        return _packet(entry.paper_id)

    result = run_paper_study_scheduler(
        entries,
        processor,
        batch_size=2,
        strategic_plan=plan,
    )

    assert result.strategic_plan == plan
    assert [entry.paper_id for entry in result.ordered_entries] == [
        "late",
        "early",
        "middle",
    ]
    assert [paper.paper_id for paper in result.batches[0].papers] == ["late", "early"]
    assert received["late"].findings == ()
    assert received["early"].findings == ()
    assert [finding.paper_id for finding in received["middle"].findings] == [
        "late",
        "early",
    ]


def test_scheduler_can_build_plan_from_grouping_policy() -> None:
    artifacts = (
        _routing_artifact("paper-a", "receptor protein cultured cells control "),
        _routing_artifact("paper-b", "receptor protein cultured cells assay "),
        _routing_artifact("paper-c", "software benchmark runtime accuracy baseline "),
    )
    manifest = build_corpus_manifest(artifacts)
    entries = [
        PaperIndexEntry(paper_id=artifact.paper_id, source_path=artifact.source_file)
        for artifact in artifacts
    ]

    result = run_paper_study_scheduler(
        entries,
        lambda entry, context: _packet(entry.paper_id),
        batch_size=2,
        grouping_policy=MedoidBatcher(),
        corpus_manifest=manifest,
    )

    assert result.strategic_plan is not None
    assert result.strategic_plan.manifest_digest == manifest.digest()
    assert tuple(
        paper.paper_id for batch in result.batches for paper in batch.papers
    ) == result.strategic_plan.ordered_paper_ids


def test_strategic_plan_must_match_entries_and_batch_size() -> None:
    plan = StrategicBatchPlan(
        policy_name="fixture",
        manifest_digest="sha256:fixture",
        batch_size=1,
        seed_paper_ids=("paper-a",),
        assignments=(
            BatchAssignment(
                paper_id="paper-a",
                batch_number=1,
                position_in_batch=1,
                role="seed_medoid",
                anchor_paper_id="paper-a",
                skeleton_similarity_ppm=1_000_000,
            ),
        ),
    )
    entries = [PaperIndexEntry(paper_id="paper-b", source_path="/papers/b.json")]

    with pytest.raises(ValueError, match="paper IDs must exactly match"):
        run_paper_study_scheduler(
            entries,
            lambda entry, context: _packet(entry.paper_id),
            batch_size=1,
            strategic_plan=plan,
        )
    with pytest.raises(ValueError, match="batch_size does not match"):
        run_paper_study_scheduler(
            [PaperIndexEntry(paper_id="paper-a", source_path="/papers/a.json")],
            lambda entry, context: _packet(entry.paper_id),
            batch_size=2,
            strategic_plan=plan,
        )


def test_grouping_policy_requires_manifest() -> None:
    with pytest.raises(ValueError, match="requires corpus_manifest"):
        run_paper_study_scheduler(
            [PaperIndexEntry(paper_id="paper-a", source_path="/papers/a.json")],
            lambda entry, context: _packet(entry.paper_id),
            grouping_policy=MedoidBatcher(),
        )
