"""Deterministic, source-only corpus profiling for reconciliation.

This module deliberately sits before semantic extraction.  It derives coarse
lexical and structural routing features from validated chunk artifacts, without
creating Claims or Results and without invoking a completion provider.  The
profiles are suitable for deterministic retrieval, batching, and reconciliation
experiments; they are not scientific conclusions.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import Field, model_validator

from odracir.paper_study.domains import PaperDomain, ScientificLogicMode
from odracir.paper_study.models import StrictModel
from odracir.paper_study.planning import (
    ChunkArtifact,
    SourceChunk,
    classify_paper,
    load_chunk_artifact,
)

if TYPE_CHECKING:
    from odracir.paper_study.scheduler import PaperIndexEntry


PROFILE_ALGORITHM_VERSION = "source-profile/v2"
DEFAULT_MAX_FEATURE_TOKENS = 96
DEFAULT_CLUSTER_DISTANCE_THRESHOLD = 0.45

_TOKEN_RE = re.compile(r"[^\W_]+(?:[-'][^\W_]+)*", re.UNICODE)
_STOPWORDS = frozenset(
    {
        "about",
        "after",
        "also",
        "among",
        "and",
        "are",
        "because",
        "been",
        "before",
        "between",
        "both",
        "but",
        "can",
        "could",
        "did",
        "does",
        "during",
        "each",
        "for",
        "from",
        "had",
        "has",
        "have",
        "into",
        "its",
        "may",
        "more",
        "most",
        "not",
        "our",
        "show",
        "shown",
        "shows",
        "such",
        "than",
        "that",
        "the",
        "their",
        "these",
        "this",
        "those",
        "through",
        "using",
        "was",
        "were",
        "which",
        "while",
        "with",
        "would",
    }
)

# These are routing hints only.  A match signals contrast, negation, or
# uncertainty in the source; it does not prove a cross-paper contradiction.
_CONFLICT_SIGNAL_PHRASES = (
    "although",
    "conflicting",
    "contrary to",
    "did not",
    "disagree",
    "failed to",
    "however",
    "in contrast",
    "inconsistent",
    "no evidence",
    "opposite",
    "whereas",
)

_EXPERIMENTAL_SYSTEM_PATTERNS: dict[str, tuple[str, ...]] = {
    "cell_line": ("cell line", "cell lines"),
    "cultured_cells": ("cell culture", "cultured cells"),
    "drosophila": ("drosophila", "fruit fly"),
    "ex_vivo": ("ex vivo",),
    "human_participants": ("human cohort", "participants", "patients"),
    "in_vitro": ("in vitro",),
    "in_vivo": ("in vivo",),
    "mouse": ("mice", "mouse", "murine"),
    "organoid": ("organoid", "organoids"),
    "primary_cells": ("primary cells",),
    "rat": ("rat", "rats"),
    "tissue": ("tissue", "tissues"),
    "yeast": ("yeast",),
    "zebrafish": ("zebrafish",),
}

_METHOD_PATTERNS: dict[str, tuple[str, ...]] = {
    "ablation_study": ("ablation study", "ablation studies"),
    "benchmarking": ("benchmark", "benchmarking"),
    "confocal_microscopy": ("confocal microscopy",),
    "crispr": ("crispr", "crispr-cas9"),
    "cross_validation": ("cross-validation", "cross validation"),
    "elisa": ("elisa",),
    "flow_cytometry": ("flow cytometry",),
    "gene_knockdown": ("gene knockdown", "knockdown", "sirna"),
    "gene_knockout": ("gene knockout", "knockout"),
    "gene_overexpression": ("overexpression", "overexpressed"),
    "immunoblot": ("immunoblot", "western blot"),
    "mass_spectrometry": ("mass spectrometry",),
    "microscopy": ("microscopy",),
    "qpcr": ("qpcr", "q-pcr", "quantitative pcr", "rt-pcr"),
    "randomized_trial": ("randomized controlled trial", "randomised controlled trial"),
    "regression": ("linear regression", "logistic regression", "regression model"),
    "rna_sequencing": ("rna-seq", "rna sequencing", "transcriptome sequencing"),
    "simulation": ("computer simulation", "simulation study"),
}

_CAUSAL_RUNG_PATTERNS: dict[str, tuple[str, ...]] = {
    "association": (
        "associated with",
        "association between",
        "correlated with",
        "correlation between",
    ),
    "intervention": (
        "intervention",
        "knockdown",
        "knockout",
        "overexpression",
        "perturbation",
        "randomized",
        "randomised",
        "treatment",
    ),
    "mechanism": (
        "causal mechanism",
        "mechanism",
        "mediated by",
        "mediates",
        "required for",
        "through the pathway",
    ),
    "rescue": (
        "phenotypic rescue",
        "reconstitution",
        "rescue experiment",
        "rescued the phenotype",
        "restored the phenotype",
    ),
    "temporal_order": ("before onset", "preceded", "prior to the response"),
}

_TITLE_LINE_RE = re.compile(
    r"(?im)^\s*(?:paper\s+title|title)\s*:\s*(?P<value>[^\r\n]+?)\s*$"
)
_AUTHOR_LINE_RE = re.compile(
    r"(?im)^\s*(?:authors?|by)\s*:\s*(?P<value>[^\r\n]+?)\s*$"
)
_YEAR_LINE_RE = re.compile(
    r"(?im)^\s*(?:publication\s+year|published|year)\s*:\s*"
    r"(?P<value>[12]\d{3})\s*$"
)


class SourceMetadataFeatures(StrictModel):
    """Explicitly labelled bibliographic routing metadata, when present."""

    title: str | None = Field(default=None, min_length=1)
    author: str | None = Field(default=None, min_length=1)
    year: int | None = Field(default=None, ge=1000, le=2999)


class PaperProfile(StrictModel):
    """Auditable source-only feature profile for one chunk artifact."""

    schema_version: Literal["1.0"] = "1.0"
    algorithm_version: Literal["source-profile/v2"] = PROFILE_ALGORITHM_VERSION
    paper_id: str = Field(min_length=1)
    source_path: str = Field(min_length=1)
    source_file: str = Field(min_length=1)
    source_sha256: str = Field(min_length=1)
    chunk_count: int = Field(ge=1)
    total_char_count: int = Field(ge=1)
    total_token_estimate: int = Field(ge=0)
    page_start: int = Field(ge=1)
    page_end: int = Field(ge=1)
    domain: PaperDomain
    logic_mode: ScientificLogicMode
    metadata_features: SourceMetadataFeatures
    experimental_systems: tuple[str, ...] = Field(default_factory=tuple)
    methods: tuple[str, ...] = Field(default_factory=tuple)
    causal_rungs: tuple[str, ...] = Field(default_factory=tuple)
    section_hints: tuple[str, ...] = Field(min_length=1)
    feature_tokens: tuple[str, ...] = Field(default_factory=tuple)
    feature_counts: dict[str, int] = Field(default_factory=dict)
    conflict_signals: tuple[str, ...] = Field(default_factory=tuple)
    conflict_signal_counts: dict[str, int] = Field(default_factory=dict)
    conflict_score: float = Field(ge=0.0, le=1.0)
    quality_proxy: float = Field(ge=0.0, le=1.0)
    profile_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_profile(self) -> PaperProfile:
        if self.page_end < self.page_start:
            raise ValueError("page_end must be greater than or equal to page_start")
        if len(self.feature_tokens) != len(set(self.feature_tokens)):
            raise ValueError("feature_tokens must be unique")
        if set(self.feature_counts) != set(self.feature_tokens):
            raise ValueError("feature_counts keys must exactly match feature_tokens")
        if any(count < 1 for count in self.feature_counts.values()):
            raise ValueError("feature_counts values must be positive")
        expected_token_order = tuple(
            sorted(
                self.feature_tokens,
                key=lambda token: (-self.feature_counts[token], token),
            )
        )
        if self.feature_tokens != expected_token_order:
            raise ValueError("feature_tokens must use deterministic frequency order")
        if self.section_hints != tuple(sorted(set(self.section_hints))):
            raise ValueError("section_hints must be sorted and unique")
        for field_name in ("experimental_systems", "methods", "causal_rungs"):
            values = getattr(self, field_name)
            if values != tuple(sorted(set(values))):
                raise ValueError(f"{field_name} must be sorted and unique")
        if self.conflict_signals != tuple(sorted(set(self.conflict_signals))):
            raise ValueError("conflict_signals must be sorted and unique")
        if set(self.conflict_signal_counts) != set(self.conflict_signals):
            raise ValueError(
                "conflict_signal_counts keys must exactly match conflict_signals"
            )
        if any(count < 1 for count in self.conflict_signal_counts.values()):
            raise ValueError("conflict_signal_counts values must be positive")
        expected = _model_digest(self, exclude={"profile_digest"})
        if self.profile_digest != expected:
            raise ValueError("profile_digest does not match the PaperProfile payload")
        return self

    def digest(self) -> str:
        """Return the validated content digest for this profile."""

        return self.profile_digest


class PaperCluster(StrictModel):
    """One deterministic complete-link cluster of source profiles."""

    cluster_id: str = Field(pattern=r"^pc_[0-9a-f]{24}$")
    member_paper_ids: tuple[str, ...] = Field(min_length=1)
    member_profile_digests: tuple[str, ...] = Field(min_length=1)
    max_pairwise_distance: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_cluster(self) -> PaperCluster:
        if self.member_paper_ids != tuple(sorted(set(self.member_paper_ids))):
            raise ValueError("member_paper_ids must be sorted and unique")
        if len(self.member_paper_ids) != len(self.member_profile_digests):
            raise ValueError("member IDs and profile digests must have equal length")
        expected = _cluster_id(
            tuple(zip(self.member_paper_ids, self.member_profile_digests, strict=True))
        )
        if self.cluster_id != expected:
            raise ValueError("cluster_id does not match cluster membership")
        return self


class DuplicatePaperGroup(StrictModel):
    """Byte-identical source papers collapsed before semantic extraction.

    ``source_sha256`` is copied from the ingestion artifact, where it is computed
    over the original PDF bytes.  Only the stable representative receives a
    :class:`PaperProfile`; the remaining IDs stay here as an explicit audit trail.
    """

    source_sha256: str = Field(min_length=1)
    representative_paper_id: str = Field(min_length=1)
    duplicate_paper_ids: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_group(self) -> DuplicatePaperGroup:
        expected_duplicates = tuple(
            sorted(
                set(self.duplicate_paper_ids),
                key=lambda paper_id: (paper_id.casefold(), paper_id),
            )
        )
        if self.duplicate_paper_ids != expected_duplicates:
            raise ValueError("duplicate_paper_ids must be sorted and unique")
        if self.representative_paper_id in self.duplicate_paper_ids:
            raise ValueError("representative_paper_id cannot also be a duplicate")
        return self


class CorpusManifest(StrictModel):
    """Content-addressed snapshot of deterministic corpus routing features."""

    schema_version: Literal["1.0"] = "1.0"
    profile_algorithm_version: Literal["source-profile/v2"] = (
        PROFILE_ALGORITHM_VERSION
    )
    profiles: tuple[PaperProfile, ...] = Field(min_length=1)
    duplicate_groups: tuple[DuplicatePaperGroup, ...] = Field(default_factory=tuple)
    feature_names: tuple[str, ...] = Field(default_factory=tuple)
    feature_vectors: dict[str, tuple[float, ...]] = Field(default_factory=dict)
    cluster_distance_threshold: float = Field(ge=0.0, le=1.0)
    clusters: tuple[PaperCluster, ...] = Field(min_length=1)
    manifest_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_manifest(self) -> CorpusManifest:
        expected_profiles = tuple(sorted(self.profiles, key=_profile_sort_key))
        if self.profiles != expected_profiles:
            raise ValueError("profiles must use deterministic paper order")
        paper_ids = tuple(profile.paper_id for profile in self.profiles)
        if len(paper_ids) != len(set(paper_ids)):
            raise ValueError("profiles must have unique paper_id values")
        source_hashes = tuple(profile.source_sha256 for profile in self.profiles)
        if len(source_hashes) != len(set(source_hashes)):
            raise ValueError(
                "profiles must contain one representative per source_sha256"
            )
        expected_duplicate_groups = tuple(
            sorted(self.duplicate_groups, key=_duplicate_group_sort_key)
        )
        if self.duplicate_groups != expected_duplicate_groups:
            raise ValueError("duplicate_groups must use deterministic source order")
        group_hashes = tuple(group.source_sha256 for group in self.duplicate_groups)
        if len(group_hashes) != len(set(group_hashes)):
            raise ValueError("duplicate_groups must have unique source_sha256 values")
        profile_by_id = {profile.paper_id: profile for profile in self.profiles}
        duplicate_ids = tuple(
            paper_id
            for group in self.duplicate_groups
            for paper_id in group.duplicate_paper_ids
        )
        if len(duplicate_ids) != len(set(duplicate_ids)):
            raise ValueError("a duplicate paper ID may occur in only one group")
        if set(duplicate_ids) & set(paper_ids):
            raise ValueError("duplicate paper IDs cannot also have profiles")
        for group in self.duplicate_groups:
            representative = profile_by_id.get(group.representative_paper_id)
            if representative is None:
                raise ValueError(
                    "each duplicate group representative must have a manifest profile"
                )
            if representative.source_sha256 != group.source_sha256:
                raise ValueError(
                    "duplicate group source_sha256 must match its representative"
                )
        if self.feature_names != tuple(sorted(set(self.feature_names))):
            raise ValueError("feature_names must be sorted and unique")
        expected_feature_names = build_feature_vocabulary(self.profiles)
        if self.feature_names != expected_feature_names:
            raise ValueError("feature_names do not match the manifest profiles")
        if set(self.feature_vectors) != set(paper_ids):
            raise ValueError("feature_vectors must contain exactly one vector per paper")
        if any(
            len(vector) != len(self.feature_names)
            for vector in self.feature_vectors.values()
        ):
            raise ValueError("feature vector dimensions must match feature_names")
        expected_vectors = {
            profile.paper_id: project_profile(profile, self.feature_names)
            for profile in self.profiles
        }
        if self.feature_vectors != expected_vectors:
            raise ValueError("feature_vectors do not match the manifest profiles")
        cluster_members = sorted(
            paper_id for cluster in self.clusters for paper_id in cluster.member_paper_ids
        )
        if cluster_members != sorted(paper_ids):
            raise ValueError("clusters must partition all manifest profiles exactly once")
        if self.clusters != tuple(
            sorted(self.clusters, key=lambda cluster: cluster.member_paper_ids)
        ):
            raise ValueError("clusters must use deterministic member order")
        expected_clusters = cluster_paper_profiles(
            self.profiles,
            max_distance=self.cluster_distance_threshold,
        )
        if self.clusters != expected_clusters:
            raise ValueError("clusters do not match the configured deterministic policy")
        expected_digest = _model_digest(self, exclude={"manifest_digest"})
        if self.manifest_digest != expected_digest:
            raise ValueError("manifest_digest does not match the CorpusManifest payload")
        return self

    def digest(self) -> str:
        """Return the validated content digest for this manifest."""

        return self.manifest_digest


def extract_paper_profile(
    artifact: ChunkArtifact,
    *,
    source_path: str | Path | None = None,
    max_feature_tokens: int = DEFAULT_MAX_FEATURE_TOKENS,
) -> PaperProfile:
    """Create a deterministic profile using source artifact content only."""

    if max_feature_tokens < 0:
        raise ValueError("max_feature_tokens must not be negative")
    chunks = tuple(sorted(artifact.chunks, key=lambda chunk: (chunk.ordinal, chunk.chunk_id)))
    source_text = "\n".join(chunk.text for chunk in chunks)
    normalized_text = _normalize_text(source_text)
    token_counts = Counter(_feature_tokens(normalized_text))
    ranked_tokens = sorted(token_counts, key=lambda token: (-token_counts[token], token))
    selected_tokens = tuple(ranked_tokens[:max_feature_tokens])
    feature_counts = {token: token_counts[token] for token in selected_tokens}

    conflict_counts = {
        phrase: count
        for phrase in _CONFLICT_SIGNAL_PHRASES
        if (count := _phrase_count(normalized_text, phrase)) > 0
    }
    conflict_signals = tuple(sorted(conflict_counts))
    all_token_count = len(_TOKEN_RE.findall(normalized_text))
    conflict_score = round(
        min(1.0, 50.0 * sum(conflict_counts.values()) / max(1, all_token_count)),
        12,
    )

    section_counts = Counter(
        _normalize_section_hint(chunk.section_hint) for chunk in chunks
    )
    section_hints = tuple(sorted(section_counts))
    classification = classify_paper(artifact)
    metadata_features = _extract_metadata_features(chunks)
    experimental_systems = _match_controlled_labels(
        normalized_text,
        _EXPERIMENTAL_SYSTEM_PATTERNS,
    )
    methods = _match_controlled_labels(normalized_text, _METHOD_PATTERNS)
    causal_rungs = _match_controlled_labels(
        normalized_text,
        _CAUSAL_RUNG_PATTERNS,
    )
    resolved_source_path = (
        artifact.source_file
        if source_path is None
        else str(Path(source_path).expanduser().resolve())
    )
    quality_proxy = _source_quality_proxy(artifact)

    payload = {
        "schema_version": "1.0",
        "algorithm_version": PROFILE_ALGORITHM_VERSION,
        "paper_id": artifact.paper_id,
        "source_path": resolved_source_path,
        "source_file": artifact.source_file,
        "source_sha256": artifact.source_sha256,
        "chunk_count": artifact.chunk_count,
        "total_char_count": sum(chunk.char_count for chunk in chunks),
        "total_token_estimate": sum(chunk.token_estimate for chunk in chunks),
        "page_start": min(chunk.page_start for chunk in chunks),
        "page_end": max(chunk.page_end for chunk in chunks),
        "domain": classification.domain,
        "logic_mode": classification.logic_mode,
        "metadata_features": metadata_features,
        "experimental_systems": experimental_systems,
        "methods": methods,
        "causal_rungs": causal_rungs,
        "section_hints": section_hints,
        "feature_tokens": selected_tokens,
        "feature_counts": feature_counts,
        "conflict_signals": conflict_signals,
        "conflict_signal_counts": conflict_counts,
        "conflict_score": conflict_score,
        "quality_proxy": quality_proxy,
    }
    return PaperProfile(**payload, profile_digest=_payload_digest(payload))


def profile_feature_map(profile: PaperProfile) -> dict[str, float]:
    """Project a profile into a sparse, identity-free routing feature map."""

    features: dict[str, float] = {
        f"domain:{profile.domain.value}": 1.0,
        f"logic:{profile.logic_mode.value}": 1.0,
    }
    metadata = profile.metadata_features
    if metadata.title:
        title_tokens = tuple(sorted(set(_feature_tokens(_normalize_text(metadata.title)))))
        title_weight = 0.5 / max(1, len(title_tokens))
        for token in title_tokens:
            features[f"metadata:title_token:{token}"] = title_weight
    if metadata.author:
        normalized_author = _normalize_text(metadata.author)
        features[f"metadata:author:{normalized_author}"] = 0.25
    if metadata.year is not None:
        features[f"metadata:year:{metadata.year}"] = 0.25
    for namespace, labels in (
        ("experimental_system", profile.experimental_systems),
        ("method", profile.methods),
        ("causal_rung", profile.causal_rungs),
    ):
        label_weight = 0.75 / max(1, len(labels))
        for label in labels:
            features[f"{namespace}:{label}"] = label_weight
    token_total = sum(profile.feature_counts.values())
    for token, count in profile.feature_counts.items():
        features[f"token:{token}"] = count / max(1, token_total)
    section_weight = 1.0 / len(profile.section_hints)
    for section in profile.section_hints:
        features[f"section:{section}"] = section_weight
    signal_total = sum(profile.conflict_signal_counts.values())
    for signal, count in profile.conflict_signal_counts.items():
        features[f"conflict:{signal}"] = 0.25 * count / max(1, signal_total)
    return {name: features[name] for name in sorted(features)}


def build_feature_vocabulary(profiles: Sequence[PaperProfile]) -> tuple[str, ...]:
    """Return the sorted union of sparse profile feature names."""

    return tuple(
        sorted(
            {
                feature_name
                for profile in profiles
                for feature_name in profile_feature_map(profile)
            }
        )
    )


def project_profile(
    profile: PaperProfile,
    feature_names: Sequence[str],
) -> tuple[float, ...]:
    """Project one sparse profile onto an explicit shared vocabulary."""

    vocabulary = tuple(feature_names)
    if vocabulary != tuple(sorted(set(vocabulary))):
        raise ValueError("feature_names must be sorted and unique")
    sparse = profile_feature_map(profile)
    return tuple(sparse.get(name, 0.0) for name in vocabulary)


def profile_distance(left: PaperProfile, right: PaperProfile) -> float:
    """Return deterministic cosine distance over source-only routing features."""

    vocabulary = build_feature_vocabulary((left, right))
    left_vector = project_profile(left, vocabulary)
    right_vector = project_profile(right, vocabulary)
    numerator = math.fsum(a * b for a, b in zip(left_vector, right_vector, strict=True))
    left_norm = math.sqrt(math.fsum(value * value for value in left_vector))
    right_norm = math.sqrt(math.fsum(value * value for value in right_vector))
    if left_norm == 0.0 and right_norm == 0.0:
        return 0.0
    if left_norm == 0.0 or right_norm == 0.0:
        return 1.0
    similarity = numerator / (left_norm * right_norm)
    return round(min(1.0, max(0.0, 1.0 - similarity)), 12)


def cluster_paper_profiles(
    profiles: Sequence[PaperProfile],
    *,
    max_distance: float = DEFAULT_CLUSTER_DISTANCE_THRESHOLD,
) -> tuple[PaperCluster, ...]:
    """Deterministically complete-link cluster profiles at a distance bound."""

    if not math.isfinite(max_distance) or not 0.0 <= max_distance <= 1.0:
        raise ValueError("max_distance must be finite and between 0 and 1")
    ordered = tuple(sorted(profiles, key=_profile_sort_key))
    paper_ids = [profile.paper_id for profile in ordered]
    if len(paper_ids) != len(set(paper_ids)):
        raise ValueError("profiles must have unique paper_id values")
    if not ordered:
        return ()

    pair_distances = {
        _ordered_pair(left.paper_id, right.paper_id): profile_distance(left, right)
        for left_index, left in enumerate(ordered)
        for right in ordered[left_index + 1 :]
    }
    working: list[tuple[PaperProfile, ...]] = [(profile,) for profile in ordered]
    while True:
        proposals: list[
            tuple[float, tuple[str, ...], int, int]
        ] = []
        for left_index, left_cluster in enumerate(working):
            for right_index in range(left_index + 1, len(working)):
                right_cluster = working[right_index]
                complete_link_distance = max(
                    pair_distances[_ordered_pair(left.paper_id, right.paper_id)]
                    for left in left_cluster
                    for right in right_cluster
                )
                if complete_link_distance <= max_distance:
                    member_ids = tuple(
                        sorted(
                            profile.paper_id
                            for profile in (*left_cluster, *right_cluster)
                        )
                    )
                    proposals.append(
                        (
                            complete_link_distance,
                            member_ids,
                            left_index,
                            right_index,
                        )
                    )
        if not proposals:
            break
        _, _, left_index, right_index = min(
            proposals, key=lambda item: (item[0], item[1])
        )
        merged = tuple(
            sorted((*working[left_index], *working[right_index]), key=_profile_sort_key)
        )
        working = [
            cluster
            for index, cluster in enumerate(working)
            if index not in {left_index, right_index}
        ]
        working.append(merged)
        working.sort(key=lambda cluster: tuple(item.paper_id for item in cluster))

    clusters = tuple(_build_cluster(cluster, pair_distances) for cluster in working)
    return tuple(sorted(clusters, key=lambda cluster: cluster.member_paper_ids))


def build_corpus_manifest(
    items: Sequence[PaperIndexEntry | str | Path | ChunkArtifact],
    *,
    max_feature_tokens: int = DEFAULT_MAX_FEATURE_TOKENS,
    cluster_distance_threshold: float = DEFAULT_CLUSTER_DISTANCE_THRESHOLD,
) -> CorpusManifest:
    """Build a manifest from scheduler entries, artifact paths, or artifacts."""

    profiles: list[PaperProfile] = []
    for item in items:
        expected_paper_id: str | None = None
        if isinstance(item, ChunkArtifact):
            artifact = item
            source_path: str | Path | None = None
        elif isinstance(item, (str, Path)):
            source_path = item
            artifact = load_chunk_artifact(source_path)
        else:
            source_path = getattr(item, "source_path", None)
            expected_paper_id = getattr(item, "paper_id", None)
            if not isinstance(source_path, str) or not source_path:
                raise TypeError("manifest entries must provide a non-empty source_path")
            if not isinstance(expected_paper_id, str) or not expected_paper_id:
                raise TypeError("manifest entries must provide a non-empty paper_id")
            artifact = load_chunk_artifact(source_path)
        if expected_paper_id is not None and artifact.paper_id != expected_paper_id:
            raise ValueError(
                "PaperIndexEntry paper_id does not match its chunk artifact: "
                f"{expected_paper_id!r} != {artifact.paper_id!r}"
            )
        profiles.append(
            extract_paper_profile(
                artifact,
                source_path=source_path,
                max_feature_tokens=max_feature_tokens,
            )
        )

    if not profiles:
        raise ValueError("a corpus manifest requires at least one paper")
    input_paper_ids = [profile.paper_id for profile in profiles]
    if len(input_paper_ids) != len(set(input_paper_ids)):
        duplicate_ids = sorted(
            {
                paper_id
                for paper_id in input_paper_ids
                if input_paper_ids.count(paper_id) > 1
            }
        )
        raise ValueError(f"manifest inputs contain duplicate paper IDs: {duplicate_ids}")

    profiles_by_source: dict[str, list[PaperProfile]] = {}
    for profile in profiles:
        profiles_by_source.setdefault(profile.source_sha256, []).append(profile)

    representative_profiles: list[PaperProfile] = []
    duplicate_groups: list[DuplicatePaperGroup] = []
    for source_sha256, source_profiles in profiles_by_source.items():
        ordered_source_profiles = sorted(
            source_profiles,
            key=_duplicate_representative_sort_key,
        )
        representative = ordered_source_profiles[0]
        representative_profiles.append(representative)
        if len(ordered_source_profiles) > 1:
            duplicate_groups.append(
                DuplicatePaperGroup(
                    source_sha256=source_sha256,
                    representative_paper_id=representative.paper_id,
                    duplicate_paper_ids=tuple(
                        profile.paper_id for profile in ordered_source_profiles[1:]
                    ),
                )
            )

    ordered_profiles = tuple(sorted(representative_profiles, key=_profile_sort_key))
    ordered_duplicate_groups = tuple(
        sorted(duplicate_groups, key=_duplicate_group_sort_key)
    )
    feature_names = build_feature_vocabulary(ordered_profiles)
    feature_vectors = {
        profile.paper_id: project_profile(profile, feature_names)
        for profile in ordered_profiles
    }
    clusters = cluster_paper_profiles(
        ordered_profiles,
        max_distance=cluster_distance_threshold,
    )
    payload = {
        "schema_version": "1.0",
        "profile_algorithm_version": PROFILE_ALGORITHM_VERSION,
        "profiles": ordered_profiles,
        "duplicate_groups": ordered_duplicate_groups,
        "feature_names": feature_names,
        "feature_vectors": feature_vectors,
        "cluster_distance_threshold": cluster_distance_threshold,
        "clusters": clusters,
    }
    return CorpusManifest(**payload, manifest_digest=_payload_digest(payload))


def build_corpus_manifest_from_entries(
    entries: Sequence[PaperIndexEntry],
    *,
    max_feature_tokens: int = DEFAULT_MAX_FEATURE_TOKENS,
    cluster_distance_threshold: float = DEFAULT_CLUSTER_DISTANCE_THRESHOLD,
) -> CorpusManifest:
    """Typed facade for scheduler ``PaperIndexEntry`` inputs."""

    return build_corpus_manifest(
        entries,
        max_feature_tokens=max_feature_tokens,
        cluster_distance_threshold=cluster_distance_threshold,
    )


def build_corpus_manifest_from_paths(
    paths: Sequence[str | Path],
    *,
    max_feature_tokens: int = DEFAULT_MAX_FEATURE_TOKENS,
    cluster_distance_threshold: float = DEFAULT_CLUSTER_DISTANCE_THRESHOLD,
) -> CorpusManifest:
    """Typed facade for chunk artifact path inputs."""

    return build_corpus_manifest(
        paths,
        max_feature_tokens=max_feature_tokens,
        cluster_distance_threshold=cluster_distance_threshold,
    )


def write_corpus_manifest(manifest: CorpusManifest, path: str | Path) -> Path:
    """Atomically write a validated manifest as stable, human-readable JSON."""

    validated = CorpusManifest.model_validate(manifest)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp")
    temporary.write_text(
        json.dumps(
            validated.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)
    return target


def _feature_tokens(normalized_text: str) -> list[str]:
    return [
        token
        for token in _TOKEN_RE.findall(normalized_text)
        if len(token) >= 3 and not token.isdigit() and token not in _STOPWORDS
    ]


def _normalize_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _normalize_section_hint(value: str) -> str:
    normalized = _normalize_text(value)
    return normalized or "(unspecified)"


def _extract_metadata_features(
    chunks: Sequence[SourceChunk],
) -> SourceMetadataFeatures:
    """Read only explicit metadata labels, never infer bibliography from prose."""

    title: str | None = None
    author: str | None = None
    year: int | None = None
    for chunk in chunks:
        if title is None and (match := _TITLE_LINE_RE.search(chunk.text)):
            title = _clean_metadata_value(match.group("value")) or None
        if author is None and (match := _AUTHOR_LINE_RE.search(chunk.text)):
            author = _clean_metadata_value(match.group("value")) or None
        if year is None and (match := _YEAR_LINE_RE.search(chunk.text)):
            year = int(match.group("value"))
        if title is not None and author is not None and year is not None:
            break
    return SourceMetadataFeatures(title=title, author=author, year=year)


def _clean_metadata_value(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split()).strip()


def _match_controlled_labels(
    normalized_text: str,
    vocabulary: dict[str, tuple[str, ...]],
) -> tuple[str, ...]:
    """Return sorted labels whose versioned source patterns occur explicitly."""

    return tuple(
        sorted(
            label
            for label, patterns in vocabulary.items()
            if any(_phrase_count(normalized_text, pattern) for pattern in patterns)
        )
    )


def _phrase_count(text: str, phrase: str) -> int:
    pattern = re.compile(rf"(?<!\w){re.escape(phrase)}(?!\w)")
    return len(pattern.findall(text))


def _source_quality_proxy(artifact: ChunkArtifact) -> float:
    chunks = artifact.chunks
    count = len(chunks)
    nontrivial_text = sum(chunk.char_count >= 80 for chunk in chunks) / count
    token_estimates = sum(chunk.token_estimate > 0 for chunk in chunks) / count
    section_hints = sum(bool(chunk.section_hint.strip()) for chunk in chunks) / count
    unique_content = len({chunk.content_sha256 for chunk in chunks}) / count
    return round(
        0.4 * nontrivial_text
        + 0.2 * token_estimates
        + 0.2 * section_hints
        + 0.2 * unique_content,
        12,
    )


def _build_cluster(
    profiles: tuple[PaperProfile, ...],
    pair_distances: dict[tuple[str, str], float],
) -> PaperCluster:
    ordered = tuple(sorted(profiles, key=_profile_sort_key))
    members = tuple((profile.paper_id, profile.profile_digest) for profile in ordered)
    distances = [
        pair_distances[_ordered_pair(left.paper_id, right.paper_id)]
        for left_index, left in enumerate(ordered)
        for right in ordered[left_index + 1 :]
    ]
    return PaperCluster(
        cluster_id=_cluster_id(members),
        member_paper_ids=tuple(member[0] for member in members),
        member_profile_digests=tuple(member[1] for member in members),
        max_pairwise_distance=max(distances, default=0.0),
    )


def _cluster_id(members: tuple[tuple[str, str], ...]) -> str:
    return f"pc_{_hex_digest(members)[:24]}"


def _profile_sort_key(profile: PaperProfile) -> tuple[str, str, str]:
    return (profile.paper_id.casefold(), profile.paper_id, profile.profile_digest)


def _duplicate_representative_sort_key(
    profile: PaperProfile,
) -> tuple[str, str, str]:
    return (profile.paper_id.casefold(), profile.paper_id, profile.source_path)


def _duplicate_group_sort_key(
    group: DuplicatePaperGroup,
) -> tuple[str, str, str]:
    return (
        group.source_sha256,
        group.representative_paper_id.casefold(),
        group.representative_paper_id,
    )


def _ordered_pair(left: str, right: str) -> tuple[str, str]:
    if left == right:
        raise ValueError("a profile pair requires two distinct paper IDs")
    return tuple(sorted((left, right)))  # type: ignore[return-value]


def _model_digest(model: StrictModel, *, exclude: set[str]) -> str:
    return _payload_digest(model.model_dump(mode="json", exclude=exclude))


def _payload_digest(payload: object) -> str:
    return f"sha256:{_hex_digest(payload)}"


def _hex_digest(payload: object) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
        default=_json_default,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _json_default(value: object) -> object:
    if isinstance(value, StrictModel):
        return value.model_dump(mode="json")
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")
