from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from odracir.paper_study.planning import ChunkArtifact, SourceChunk
from odracir.paper_study.recon import (
    CorpusManifest,
    DuplicatePaperGroup,
    PaperProfile,
    build_corpus_manifest,
    build_corpus_manifest_from_entries,
    build_corpus_manifest_from_paths,
    build_feature_vocabulary,
    cluster_paper_profiles,
    extract_paper_profile,
    profile_feature_map,
    profile_distance,
    project_profile,
    write_corpus_manifest,
)
from odracir.paper_study.scheduler import PaperIndexEntry


BIO_TEXT = (
    "Knockdown of the receptor reduced protein expression in cultured cells. "
    "However, the untreated control did not show the same response. "
    "In contrast, receptor overexpression increased the molecular readout. "
)

METHOD_TEXT = (
    "The software pipeline uses cross-validation, a benchmark dataset, and an "
    "ablation study to compare runtime and prediction accuracy with baselines. "
)

METADATA_TEXT = (
    "Title: Receptor control in a mouse model\n"
    "Authors: Ada Example; Bo Researcher\n"
    "Publication Year: 2024\n"
    "In vivo mouse tissue was analysed by western blot and qPCR. "
    "A reconstitution rescue experiment restored the phenotype. "
)


def _artifact(
    paper_id: str,
    text: str,
    *,
    section_hint: str = "results",
    token_estimate: int = 40,
    source_sha256: str | None = None,
) -> ChunkArtifact:
    # Repeat source prose so a healthy fixture also exercises the nontrivial-text
    # component of the source-only quality proxy.
    source_text = text * 2
    chunk = SourceChunk(
        chunk_id=f"{paper_id}-chunk-1",
        ordinal=1,
        section_hint=section_hint,
        page_start=2,
        page_end=3,
        char_count=len(source_text),
        token_estimate=token_estimate,
        content_sha256=f"content-{paper_id}",
        text=source_text,
    )
    return ChunkArtifact(
        schema_version="0.1",
        paper_id=paper_id,
        source_file=f"{paper_id}.pdf",
        source_sha256=source_sha256 or f"source-{paper_id}",
        text_artifact=f"texts/{paper_id}.json",
        text_artifact_sha256=f"text-{paper_id}",
        chunker="fixture",
        chunker_version="1.0",
        chunked_at="2026-07-13T00:00:00Z",
        chunk_count=1,
        chunks=[chunk],
    )


def _write_artifact(root: Path, artifact: ChunkArtifact) -> Path:
    path = root / f"{artifact.paper_id}.json"
    path.write_text(artifact.model_dump_json(by_alias=True), encoding="utf-8")
    return path


def test_extract_profile_is_source_only_deterministic_and_auditable(tmp_path: Path) -> None:
    artifact = _artifact("paper-a", BIO_TEXT)
    source_path = tmp_path / "paper-a.json"

    first = extract_paper_profile(artifact, source_path=source_path)
    second = extract_paper_profile(artifact, source_path=source_path)

    assert first == second
    assert first.digest() == first.profile_digest
    assert first.source_path == str(source_path.resolve())
    assert first.page_start == 2
    assert first.page_end == 3
    assert first.feature_tokens
    assert first.feature_counts["receptor"] == 4
    assert first.conflict_signals == ("did not", "however", "in contrast")
    assert first.conflict_score > 0.0
    assert first.quality_proxy == 1.0
    assert first.metadata_features.title is None
    assert first.metadata_features.author is None
    assert first.metadata_features.year is None
    assert first.experimental_systems == ("cultured_cells",)
    assert first.methods == ("gene_knockdown", "gene_overexpression")
    assert first.causal_rungs == ("intervention",)
    payload = first.model_dump(mode="json")
    assert "claims" not in payload
    assert "results" not in payload
    assert "text" not in payload


def test_profile_digest_rejects_mutation() -> None:
    profile = extract_paper_profile(_artifact("paper-a", BIO_TEXT))
    payload = profile.model_dump(mode="python")
    payload["quality_proxy"] = 0.25

    with pytest.raises(ValidationError, match="profile_digest"):
        PaperProfile.model_validate(payload)


def test_explicit_metadata_and_controlled_routing_labels_enter_features() -> None:
    profile = extract_paper_profile(_artifact("paper-meta", METADATA_TEXT))
    features = profile_feature_map(profile)

    assert profile.metadata_features.title == "Receptor control in a mouse model"
    assert profile.metadata_features.author == "Ada Example; Bo Researcher"
    assert profile.metadata_features.year == 2024
    assert profile.experimental_systems == ("in_vivo", "mouse", "tissue")
    assert profile.methods == ("immunoblot", "qpcr")
    assert profile.causal_rungs == ("rescue",)
    assert "metadata:title_token:receptor" in features
    assert "metadata:author:ada example; bo researcher" in features
    assert "metadata:year:2024" in features
    assert "experimental_system:mouse" in features
    assert "method:immunoblot" in features
    assert "causal_rung:rescue" in features

    payload = profile.model_dump(mode="python")
    payload["methods"] = (*profile.methods, "simulation")
    with pytest.raises(ValidationError, match="profile_digest"):
        PaperProfile.model_validate(payload)


def test_feature_projection_and_distance_ignore_document_identity() -> None:
    left = extract_paper_profile(_artifact("left", BIO_TEXT))
    same_content = extract_paper_profile(_artifact("right", BIO_TEXT))
    unrelated = extract_paper_profile(_artifact("method", METHOD_TEXT, section_hint="methods"))
    vocabulary = build_feature_vocabulary((left, same_content, unrelated))

    assert vocabulary == tuple(sorted(set(vocabulary)))
    assert len(project_profile(left, vocabulary)) == len(vocabulary)
    assert profile_distance(left, same_content) == 0.0
    assert profile_distance(left, unrelated) > 0.0
    assert profile_distance(left, unrelated) == profile_distance(unrelated, left)


def test_complete_link_clustering_is_stable_under_input_order() -> None:
    first = extract_paper_profile(_artifact("paper-a", BIO_TEXT))
    second = extract_paper_profile(_artifact("paper-b", BIO_TEXT))
    other = extract_paper_profile(_artifact("paper-c", METHOD_TEXT, section_hint="methods"))

    forward = cluster_paper_profiles((first, second, other), max_distance=0.0)
    reverse = cluster_paper_profiles((other, second, first), max_distance=0.0)

    assert forward == reverse
    assert [cluster.member_paper_ids for cluster in forward] == [
        ("paper-a", "paper-b"),
        ("paper-c",),
    ]
    assert forward[0].max_pairwise_distance == 0.0


def test_manifest_from_paths_is_content_addressed_and_order_stable(tmp_path: Path) -> None:
    first_path = _write_artifact(tmp_path, _artifact("paper-b", METHOD_TEXT))
    second_path = _write_artifact(tmp_path, _artifact("paper-a", BIO_TEXT))

    forward = build_corpus_manifest_from_paths((first_path, second_path))
    reverse = build_corpus_manifest_from_paths((second_path, first_path))

    assert forward == reverse
    assert forward.digest() == forward.manifest_digest
    assert [profile.paper_id for profile in forward.profiles] == ["paper-a", "paper-b"]
    assert set(forward.feature_vectors) == {"paper-a", "paper-b"}
    assert len(forward.feature_vectors["paper-a"]) == len(forward.feature_names)


def test_manifest_collapses_byte_identical_sources_with_stable_audit_group(
    tmp_path: Path,
) -> None:
    byte_digest = "b38b818b08d884d4f8566834b5a363a2940c61cb0af7a6e47c8c626aa1ba8c32"
    first_path = _write_artifact(
        tmp_path,
        _artifact("1_14", BIO_TEXT, source_sha256=byte_digest),
    )
    second_path = _write_artifact(
        tmp_path,
        _artifact("1_13", BIO_TEXT, source_sha256=byte_digest),
    )
    distinct_path = _write_artifact(
        tmp_path,
        _artifact("1_15", BIO_TEXT, source_sha256="different-source-hash"),
    )

    forward = build_corpus_manifest_from_paths(
        (first_path, distinct_path, second_path)
    )
    reverse = build_corpus_manifest_from_paths(
        (second_path, distinct_path, first_path)
    )

    assert forward == reverse
    assert forward.digest() == reverse.digest()
    assert [profile.paper_id for profile in forward.profiles] == ["1_13", "1_15"]
    assert set(forward.feature_vectors) == {"1_13", "1_15"}
    assert tuple(
        paper_id
        for cluster in forward.clusters
        for paper_id in cluster.member_paper_ids
    ) == ("1_13", "1_15")
    assert forward.duplicate_groups == (
        DuplicatePaperGroup(
            source_sha256=byte_digest,
            representative_paper_id="1_13",
            duplicate_paper_ids=("1_14",),
        ),
    )

    tampered = forward.model_dump(mode="python")
    tampered["duplicate_groups"][0]["duplicate_paper_ids"] = ("1_14", "1_13")
    with pytest.raises(ValidationError, match="duplicate_paper_ids"):
        CorpusManifest.model_validate(tampered)


def test_manifest_supports_scheduler_entries_and_checks_identity(tmp_path: Path) -> None:
    path = _write_artifact(tmp_path, _artifact("paper-a", BIO_TEXT))
    entry = PaperIndexEntry(paper_id="paper-a", source_path=str(path))

    manifest = build_corpus_manifest_from_entries((entry,))

    assert manifest.profiles[0].paper_id == "paper-a"
    assert manifest.profiles[0].source_path == str(path.resolve())

    mismatch = PaperIndexEntry(paper_id="wrong-paper", source_path=str(path))
    with pytest.raises(ValueError, match="does not match"):
        build_corpus_manifest((mismatch,))


def test_manifest_json_round_trip_and_digest_validation(tmp_path: Path) -> None:
    source_path = _write_artifact(tmp_path, _artifact("paper-a", BIO_TEXT))
    manifest = build_corpus_manifest((source_path,))
    output = write_corpus_manifest(manifest, tmp_path / "nested" / "manifest.json")

    restored = CorpusManifest.model_validate_json(output.read_text(encoding="utf-8"))

    assert restored == manifest
    assert json.loads(output.read_text(encoding="utf-8"))["manifest_digest"] == (
        manifest.manifest_digest
    )
    tampered = manifest.model_dump(mode="python")
    tampered["cluster_distance_threshold"] = 0.1
    with pytest.raises(ValidationError, match="manifest_digest"):
        CorpusManifest.model_validate(tampered)
