"""Deterministic canonicalization for paper-study packets.

Semantic keys remain independent of an entity's source ID and provenance.
Application is deliberately plan-bound: a stale or modified plan is rejected,
then entities are rebuilt in StudyUnit -> Result -> Claim order so every
reference rewrite and merge can be audited.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from decimal import Decimal
from itertools import combinations
from typing import Callable, Generic, Iterable, Literal, Sequence, TypeVar

from pydantic import ConfigDict, Field, model_validator

from odracir.paper_study.models import (
    Claim,
    MergeDecision,
    PaperStudyPacketV2,
    Provenance,
    ResultObservation,
    StrictModel,
    StudyUnit,
)


CANONICALIZATION_NAMESPACE = "odracir.paper-study.canonicalization/v1"
NORMALIZATION_VERSION = "1.0"

EntityType = Literal["study_unit", "result", "claim"]
ProtectedConditionKind = Literal[
    "negation",
    "direction",
    "modality",
    "causal_rung",
    "development_stage",
    "time",
    "dose",
    "dataset_split",
    "study_arm",
    "perturbation",
]


class CanonicalizationInputError(ValueError):
    """Raised when a packet cannot be canonicalized unambiguously."""


class CanonicalizationPlanError(ValueError):
    """Raised when a canonicalization plan is stale or internally invalid."""


class CanonicalizationPolicy(StrictModel):
    """Frozen, versioned policy controlling deterministic key generation."""

    model_config = ConfigDict(frozen=True)

    algorithm_version: Literal["1.0"] = "1.0"
    namespace: Literal["odracir.paper-study.canonicalization/v1"] = (
        CANONICALIZATION_NAMESPACE
    )
    normalization_version: Literal["1.0"] = NORMALIZATION_VERSION
    id_digest_length: int = Field(default=24, ge=16, le=64)
    exact_match_score_ppm: int = Field(default=1_000_000, ge=0, le=1_000_000)


DEFAULT_POLICY = CanonicalizationPolicy()


class ProtectedCondition(StrictModel):
    """A high-precision condition whose conflict must block a future merge."""

    model_config = ConfigDict(frozen=True)

    kind: ProtectedConditionKind
    value: str = Field(min_length=1)


class ScientificTextSignature(StrictModel):
    """Normalized scientific text plus identity-sensitive condition atoms."""

    model_config = ConfigDict(frozen=True)

    normalized_text: str
    tokens: tuple[str, ...] = Field(default_factory=tuple)
    protected_conditions: tuple[ProtectedCondition, ...] = Field(default_factory=tuple)


class ProvenancePointer(StrictModel):
    """Evidence alignment pointer kept outside semantic identity keys."""

    model_config = ConfigDict(frozen=True)

    chunk_id: str = Field(min_length=1)
    page_start: int = Field(ge=1)
    page_end: int = Field(ge=1)
    excerpt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    paraphrased: bool


class CanonicalComponent(StrictModel):
    """One sorted, set-like component of a canonical semantic key."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1)
    values: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_canonical_order(self) -> CanonicalComponent:
        expected = tuple(sorted(set(self.values)))
        if self.values != expected:
            raise ValueError("CanonicalComponent values must be sorted and unique")
        return self


class CanonicalKey(StrictModel):
    """Content-addressed scientific entity identity."""

    model_config = ConfigDict(frozen=True)

    namespace: Literal["odracir.paper-study.canonicalization/v1"]
    normalization_version: Literal["1.0"]
    entity_type: EntityType
    paper_id: str = Field(min_length=1)
    scope_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    components: tuple[CanonicalComponent, ...] = Field(min_length=1)
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    canonical_id: str = Field(min_length=1)
    id_digest_length: int = Field(ge=16, le=64)

    @model_validator(mode="after")
    def validate_digest_and_id(self) -> CanonicalKey:
        if tuple(sorted(self.components, key=lambda item: item.name)) != self.components:
            raise ValueError("CanonicalKey components must be sorted by name")
        expected_digest = _canonical_key_digest(
            namespace=self.namespace,
            normalization_version=self.normalization_version,
            entity_type=self.entity_type,
            paper_id=self.paper_id,
            scope_digest=self.scope_digest,
            components=self.components,
        )
        if self.digest != expected_digest:
            raise ValueError("CanonicalKey digest does not match its identity payload")
        expected_id = (
            f"{_ENTITY_ID_PREFIX[self.entity_type]}_"
            f"{expected_digest[: self.id_digest_length]}"
        )
        if self.canonical_id != expected_id:
            raise ValueError("canonical_id does not match the CanonicalKey digest")
        return self


class EntityRef(StrictModel):
    """Stable, scoped reference to an input entity."""

    model_config = ConfigDict(frozen=True)

    entity_type: EntityType
    question_id: str = Field(min_length=1)
    source_unit_id: str = Field(min_length=1)
    source_entity_id: str = Field(min_length=1)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class KeyedEntity(StrictModel):
    """Input entity reference paired with its semantic canonical key."""

    model_config = ConfigDict(frozen=True)

    ref: EntityRef
    key: CanonicalKey


class CanonicalClusterPlan(StrictModel):
    """One exact-key cluster discovered during the key-planning phase."""

    model_config = ConfigDict(frozen=True)

    entity_type: EntityType
    members: tuple[EntityRef, ...] = Field(min_length=1)
    canonical_key: CanonicalKey
    canonical_id: str = Field(min_length=1)
    match_rule: Literal["exact_canonical_key_v1"] = "exact_canonical_key_v1"
    score_ppm: int = Field(ge=0, le=1_000_000)


class IdRewrite(StrictModel):
    """Planned source-ID to content-addressed-ID rewrite."""

    model_config = ConfigDict(frozen=True)

    source: EntityRef
    canonical_id: str = Field(min_length=1)


class CanonicalizationPlan(StrictModel):
    """Declarative, source-bound plan produced without mutating the packet."""

    model_config = ConfigDict(frozen=True)

    policy: CanonicalizationPolicy
    paper_id: str = Field(min_length=1)
    source_packet_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    keyed_entities: tuple[KeyedEntity, ...] = Field(default_factory=tuple)
    clusters: tuple[CanonicalClusterPlan, ...] = Field(default_factory=tuple)
    id_rewrites: tuple[IdRewrite, ...] = Field(default_factory=tuple)
    merge_cluster_count: int = Field(ge=0)


T = TypeVar("T")


class CompleteLinkCluster(Generic[T]):
    """Small immutable container returned by complete-link clustering."""

    __slots__ = ("members",)

    def __init__(self, members: Iterable[T]) -> None:
        self.members = tuple(members)


def normalize_scientific_text(text: str) -> str:
    """Normalize orthography without erasing scientific direction or quantities."""

    normalized = unicodedata.normalize("NFKC", text).casefold()
    normalized = normalized.translate(
        str.maketrans(
            {
                "‐": "-",
                "‑": "-",
                "‒": "-",
                "–": "-",
                "—": "-",
                "−": "-",
                "μ": "u",
            }
        )
    )
    normalized = re.sub(r"[^\w.%<>=!+\-/]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def scientific_text_signature(text: str) -> ScientificTextSignature:
    """Build a normalized text signature used by keys and future aligners."""

    normalized = normalize_scientific_text(text)
    tokens = tuple(_TOKEN_RE.findall(normalized))
    return ScientificTextSignature(
        normalized_text=normalized,
        tokens=tokens,
        protected_conditions=extract_protected_conditions(normalized),
    )


def extract_protected_conditions(text: str) -> tuple[ProtectedCondition, ...]:
    """Extract conservative, high-precision conflict atoms from scientific text."""

    normalized = normalize_scientific_text(text)
    atoms: set[tuple[ProtectedConditionKind, str]] = set()
    _collect_lexicon_atoms(normalized, atoms)
    for value in _STAGE_RE.findall(normalized):
        atoms.add(("development_stage", value))
    for match in _TIME_RE.finditer(normalized):
        atoms.add(("time", _normalize_quantity(match.group("value"), match.group("unit"))))
    for match in _DOSE_RE.finditer(normalized):
        atoms.add(("dose", _normalize_quantity(match.group("value"), match.group("unit"))))
    for value in _GENOTYPE_RE.findall(normalized):
        atoms.add(("perturbation", value))
    return tuple(
        ProtectedCondition(kind=kind, value=value)
        for kind, value in sorted(atoms)
    )


def provenance_pointer(provenance: Provenance) -> ProvenancePointer:
    """Build an auditable evidence pointer that is excluded from semantic keys."""

    excerpt = normalize_scientific_text(provenance.text_excerpt)
    return ProvenancePointer(
        chunk_id=provenance.chunk_id,
        page_start=provenance.page_start,
        page_end=provenance.page_end,
        excerpt_sha256=_sha256_text(excerpt),
        paraphrased=provenance.paraphrased,
    )


def study_unit_canonical_key(
    unit: StudyUnit,
    *,
    paper_id: str,
    research_question_id: str,
    research_question: str,
    policy: CanonicalizationPolicy = DEFAULT_POLICY,
) -> CanonicalKey:
    """Generate the semantic identity key for one StudyUnit."""

    rq_scope = _sha256_json(
        {
            "question_id": research_question_id,
            "statement": normalize_scientific_text(research_question),
        }
    )
    combined_text = " ".join(
        (
            unit.name,
            *unit.experiments_or_tasks,
            *(method.name for method in unit.methods),
            *(method.protocol_description for method in unit.methods),
            *(dataset.name for dataset in unit.datasets),
            *(dataset.version_or_split or "" for dataset in unit.datasets),
        )
    )
    conditions = _condition_strings(extract_protected_conditions(combined_text))
    components = _components(
        {
            "dataset": (
                _join_nonempty(
                    normalize_scientific_text(dataset.name),
                    normalize_scientific_text(dataset.version_or_split or ""),
                )
                for dataset in unit.datasets
            ),
            "method": (
                _join_nonempty(
                    normalize_scientific_text(method.name),
                    normalize_scientific_text(method.protocol_description),
                )
                for method in unit.methods
            ),
            "name": (normalize_scientific_text(unit.name),),
            "protected_condition": conditions,
            "result_metric": (
                normalize_scientific_text(result.metric_name) for result in unit.results
            ),
            "task": (
                normalize_scientific_text(task) for task in unit.experiments_or_tasks
            ),
        }
    )
    return _build_key(
        entity_type="study_unit",
        paper_id=paper_id,
        scope_digest=rq_scope,
        components=components,
        policy=policy,
    )


def result_canonical_key(
    result: ResultObservation,
    *,
    paper_id: str,
    unit_key: CanonicalKey,
    policy: CanonicalizationPolicy = DEFAULT_POLICY,
) -> CanonicalKey:
    """Generate a Result key scoped to a canonical StudyUnit identity."""

    signature = scientific_text_signature(
        f"{result.metric_name} {result.value_raw_text} {result.unit or ''}"
    )
    components = _components(
        {
            "metric": (normalize_scientific_text(result.metric_name),),
            "observation": (normalize_scientific_text(result.value_raw_text),),
            "p_value": (
                _normalize_decimal(result.p_value)
                if result.p_value is not None
                else "not_reported",
            ),
            "protected_condition": _condition_strings(
                signature.protected_conditions
            ),
            "quantitative_value": (
                _normalize_decimal(result.quantitative_value)
                if result.quantitative_value is not None
                else "not_reported",
            ),
            "sample_size": (
                str(result.n_sample_size)
                if result.n_sample_size is not None
                else "not_reported",
            ),
            "unit": (_normalize_unit(result.unit),),
        }
    )
    return _build_key(
        entity_type="result",
        paper_id=paper_id,
        scope_digest=unit_key.digest,
        components=components,
        policy=policy,
    )


def claim_canonical_key(
    claim: Claim,
    *,
    paper_id: str,
    unit_key: CanonicalKey,
    canonical_basis_ids: Sequence[str],
    policy: CanonicalizationPolicy = DEFAULT_POLICY,
) -> CanonicalKey:
    """Generate a Claim key after Result IDs have canonical identities."""

    signature = scientific_text_signature(claim.statement)
    components = _components(
        {
            "basis": canonical_basis_ids or ("no_result_basis",),
            "polarity": (claim.polarity,),
            "proposition": (signature.normalized_text,),
            "protected_condition": _condition_strings(
                signature.protected_conditions
            ),
        }
    )
    return _build_key(
        entity_type="claim",
        paper_id=paper_id,
        scope_digest=unit_key.digest,
        components=components,
        policy=policy,
    )


def complete_link_clusters(
    items: Sequence[T],
    *,
    score: Callable[[T, T], int],
    threshold_ppm: int,
    stable_key: Callable[[T], str],
) -> tuple[CompleteLinkCluster[T], ...]:
    """Deterministic agglomerative complete-link clustering.

    Two clusters may merge only when every cross-cluster pair reaches the
    threshold. Candidate ties are resolved by the sorted member fingerprints,
    never by input order.
    """

    if not 0 <= threshold_ppm <= 1_000_000:
        raise ValueError("threshold_ppm must be between 0 and 1_000_000")
    ordered = tuple(sorted(items, key=stable_key))
    if len({stable_key(item) for item in ordered}) != len(ordered):
        raise ValueError("stable_key must be unique for every clustered item")
    pair_scores = {
        _ordered_pair(stable_key(left), stable_key(right)): score(left, right)
        for left, right in combinations(ordered, 2)
    }
    clusters = [CompleteLinkCluster((item,)) for item in ordered]

    while True:
        proposals: list[
            tuple[int, tuple[str, ...], CompleteLinkCluster[T], CompleteLinkCluster[T]]
        ] = []
        for left, right in combinations(clusters, 2):
            cross_scores = [
                pair_scores[
                    _ordered_pair(stable_key(left_item), stable_key(right_item))
                ]
                for left_item in left.members
                for right_item in right.members
            ]
            cluster_score = min(cross_scores)
            if cluster_score < threshold_ppm:
                continue
            members = tuple(
                sorted(
                    (*left.members, *right.members),
                    key=stable_key,
                )
            )
            proposals.append(
                (
                    cluster_score,
                    tuple(stable_key(item) for item in members),
                    left,
                    right,
                )
            )
        if not proposals:
            break
        _, _, left, right = min(
            proposals,
            key=lambda item: (-item[0], item[1]),
        )
        merged = CompleteLinkCluster(
            sorted((*left.members, *right.members), key=stable_key)
        )
        clusters = [cluster for cluster in clusters if cluster not in (left, right)]
        clusters.append(merged)
        clusters.sort(
            key=lambda cluster: tuple(stable_key(item) for item in cluster.members)
        )

    return tuple(clusters)


def plan_canonicalization(
    packet: PaperStudyPacketV2,
    *,
    policy: CanonicalizationPolicy = DEFAULT_POLICY,
) -> CanonicalizationPlan:
    """Generate exact semantic keys, clusters, and future ID rewrites."""

    _validate_canonicalization_input(packet)
    records: list[KeyedEntity] = []
    source_values: dict[str, StrictModel] = {}
    result_keys_by_source_id: dict[str, CanonicalKey] = {}

    for question in packet.research_questions:
        for unit in question.study_units:
            unit_key = study_unit_canonical_key(
                unit,
                paper_id=packet.paper_id,
                research_question_id=question.question_id,
                research_question=question.statement,
                policy=policy,
            )
            unit_record = _keyed_entity(
                entity_type="study_unit",
                question_id=question.question_id,
                unit_id=unit.unit_id,
                source_entity_id=unit.unit_id,
                value=unit,
                key=unit_key,
            )
            records.append(unit_record)
            source_values[_entity_ref_sort_key(unit_record.ref)] = unit
            for result in unit.results:
                result_key = result_canonical_key(
                    result,
                    paper_id=packet.paper_id,
                    unit_key=unit_key,
                    policy=policy,
                )
                result_keys_by_source_id[result.result_id] = result_key
                result_record = _keyed_entity(
                    entity_type="result",
                    question_id=question.question_id,
                    unit_id=unit.unit_id,
                    source_entity_id=result.result_id,
                    value=result,
                    key=result_key,
                )
                records.append(result_record)
                source_values[_entity_ref_sort_key(result_record.ref)] = result
            for claim in unit.claims:
                basis_ids = tuple(
                    result_keys_by_source_id[result_id].canonical_id
                    for result_id in claim.inference_basis_ids
                )
                claim_key = claim_canonical_key(
                    claim,
                    paper_id=packet.paper_id,
                    unit_key=unit_key,
                    canonical_basis_ids=basis_ids,
                    policy=policy,
                )
                claim_record = _keyed_entity(
                    entity_type="claim",
                    question_id=question.question_id,
                    unit_id=unit.unit_id,
                    source_entity_id=claim.claim_id,
                    value=claim,
                    key=claim_key,
                )
                records.append(claim_record)
                source_values[_entity_ref_sort_key(claim_record.ref)] = claim

    ordered_records = tuple(sorted(records, key=_keyed_entity_sort_key))
    _validate_truncated_ids(ordered_records)
    planned_clusters: list[CanonicalClusterPlan] = []
    blocks: dict[tuple[str, str, str], list[KeyedEntity]] = defaultdict(list)
    for record in ordered_records:
        blocks[
            (
                record.ref.entity_type,
                record.ref.question_id,
                record.key.scope_digest,
            )
        ].append(record)

    for block_key in sorted(blocks):
        block = blocks[block_key]
        clusters = complete_link_clusters(
            block,
            score=lambda left, right: _planned_pair_score(
                left,
                right,
                source_values=source_values,
                policy=policy,
            ),
            threshold_ppm=policy.exact_match_score_ppm,
            stable_key=lambda item: _entity_ref_sort_key(item.ref),
        )
        for cluster in clusters:
            representative = min(cluster.members, key=_keyed_entity_sort_key)
            members = tuple(
                sorted((item.ref for item in cluster.members), key=_entity_ref_sort_key)
            )
            planned_clusters.append(
                CanonicalClusterPlan(
                    entity_type=representative.ref.entity_type,
                    members=members,
                    canonical_key=representative.key,
                    canonical_id=representative.key.canonical_id,
                    score_ppm=policy.exact_match_score_ppm,
                )
            )

    ordered_clusters = tuple(
        sorted(
            planned_clusters,
            key=lambda cluster: (
                cluster.entity_type,
                cluster.canonical_key.digest,
                tuple(_entity_ref_sort_key(member) for member in cluster.members),
            ),
        )
    )
    rewrites = tuple(
        IdRewrite(source=record.ref, canonical_id=record.key.canonical_id)
        for record in ordered_records
    )
    return CanonicalizationPlan(
        policy=policy,
        paper_id=packet.paper_id,
        source_packet_sha256=packet_sha256(packet),
        keyed_entities=ordered_records,
        clusters=ordered_clusters,
        id_rewrites=rewrites,
        merge_cluster_count=sum(len(cluster.members) > 1 for cluster in ordered_clusters),
    )


def apply_canonicalization_plan(
    packet: PaperStudyPacketV2,
    plan: CanonicalizationPlan,
) -> PaperStudyPacketV2:
    """Apply an exact-cluster plan and return a fully reference-safe packet."""

    if packet.paper_id != plan.paper_id:
        raise CanonicalizationPlanError("Plan paper_id does not match packet")
    if packet_sha256(packet) != plan.source_packet_sha256:
        raise CanonicalizationPlanError("Canonicalization plan is stale for this packet")
    fresh_plan = plan_canonicalization(packet, policy=plan.policy)
    if _canonical_json_bytes(plan.model_dump(mode="json")) != _canonical_json_bytes(
        fresh_plan.model_dump(mode="json")
    ):
        raise CanonicalizationPlanError(
            "Canonicalization plan does not match the deterministic plan for this packet"
        )

    source_values = _index_source_entities(packet)
    clusters_by_type: dict[EntityType, list[CanonicalClusterPlan]] = {
        "study_unit": [],
        "result": [],
        "claim": [],
    }
    for cluster in plan.clusters:
        clusters_by_type[cluster.entity_type].append(cluster)

    unit_rewrites: dict[str, str] = {}
    unit_owner: dict[str, str] = {}
    unit_shells: dict[str, StudyUnit] = {}
    new_decisions: list[MergeDecision] = []

    for cluster in clusters_by_type["study_unit"]:
        question_ids = {member.question_id for member in cluster.members}
        if len(question_ids) != 1:
            raise CanonicalizationPlanError(
                "A StudyUnit cluster cannot cross ResearchQuestion boundaries"
            )
        member_values = [
            (member, _source_value(member, source_values, StudyUnit))
            for member in cluster.members
        ]
        representative_ref, representative = min(
            member_values,
            key=lambda item: _representative_sort_key(item[0], item[1]),
        )
        unit_owner[cluster.canonical_id] = representative_ref.question_id
        for member in cluster.members:
            unit_rewrites[member.source_unit_id] = cluster.canonical_id

        unit_shells[cluster.canonical_id] = _merge_unit_shell(
            cluster.canonical_id,
            representative,
            [value for _, value in member_values],
        )
        decision = _merge_decision(
            cluster,
            representative_ref=representative_ref,
            source_values=source_values,
            policy=plan.policy,
        )
        if decision is not None:
            new_decisions.append(decision)

    result_rewrites: dict[str, str] = {}
    results_by_unit: dict[str, list[ResultObservation]] = defaultdict(list)
    for cluster in clusters_by_type["result"]:
        canonical_units = {
            _required_rewrite(unit_rewrites, member.source_unit_id, "StudyUnit")
            for member in cluster.members
        }
        if len(canonical_units) != 1:
            raise CanonicalizationPlanError(
                "A Result cluster cannot cross canonical StudyUnit boundaries"
            )
        canonical_unit_id = next(iter(canonical_units))
        member_values = [
            (member, _source_value(member, source_values, ResultObservation))
            for member in cluster.members
        ]
        representative_ref, representative = min(
            member_values,
            key=lambda item: _representative_sort_key(item[0], item[1]),
        )
        merged_result = _merge_result(
            cluster.canonical_id,
            representative,
            [value for _, value in member_values],
        )
        results_by_unit[canonical_unit_id].append(merged_result)
        for member in cluster.members:
            result_rewrites[member.source_entity_id] = cluster.canonical_id
        decision = _merge_decision(
            cluster,
            representative_ref=representative_ref,
            source_values=source_values,
            policy=plan.policy,
        )
        if decision is not None:
            new_decisions.append(decision)

    claims_by_unit: dict[str, list[Claim]] = defaultdict(list)
    for cluster in clusters_by_type["claim"]:
        canonical_units = {
            _required_rewrite(unit_rewrites, member.source_unit_id, "StudyUnit")
            for member in cluster.members
        }
        if len(canonical_units) != 1:
            raise CanonicalizationPlanError(
                "A Claim cluster cannot cross canonical StudyUnit boundaries"
            )
        canonical_unit_id = next(iter(canonical_units))
        member_values = [
            (member, _source_value(member, source_values, Claim))
            for member in cluster.members
        ]
        rewritten_bases = {
            tuple(
                sorted(
                    {
                        _required_rewrite(result_rewrites, result_id, "Result")
                        for result_id in claim.inference_basis_ids
                    }
                )
            )
            for _, claim in member_values
        }
        if len(rewritten_bases) != 1:
            raise CanonicalizationPlanError(
                f"Claim cluster {cluster.canonical_id} has inconsistent rewritten bases"
            )
        representative_ref, representative = min(
            member_values,
            key=lambda item: _representative_sort_key(item[0], item[1]),
        )
        merged_claim = _merge_claim(
            cluster.canonical_id,
            representative,
            [value for _, value in member_values],
            basis_ids=next(iter(rewritten_bases)),
        )
        claims_by_unit[canonical_unit_id].append(merged_claim)
        decision = _merge_decision(
            cluster,
            representative_ref=representative_ref,
            source_values=source_values,
            policy=plan.policy,
        )
        if decision is not None:
            new_decisions.append(decision)

    completed_units: dict[str, StudyUnit] = {}
    for canonical_unit_id, shell in unit_shells.items():
        results = sorted(
            results_by_unit.get(canonical_unit_id, []),
            key=lambda result: result.result_id,
        )
        claims = sorted(
            claims_by_unit.get(canonical_unit_id, []),
            key=lambda claim: claim.claim_id,
        )
        local_result_ids = {result.result_id for result in results}
        for claim in claims:
            missing = set(claim.inference_basis_ids) - local_result_ids
            if missing:
                raise CanonicalizationPlanError(
                    f"Claim {claim.claim_id} has missing canonical Result refs: "
                    f"{sorted(missing)}"
                )
        completed_units[canonical_unit_id] = StudyUnit.model_validate(
            {
                **shell.model_dump(mode="python"),
                "results": [result.model_dump(mode="python") for result in results],
                "claims": [claim.model_dump(mode="python") for claim in claims],
            }
        )

    questions = []
    for question in packet.research_questions:
        owned_units = sorted(
            (
                completed_units[unit_id]
                for unit_id, owner_id in unit_owner.items()
                if owner_id == question.question_id
            ),
            key=lambda unit: unit.unit_id,
        )
        questions.append(
            question.__class__.model_validate(
                {
                    **question.model_dump(mode="python"),
                    "study_units": [unit.model_dump(mode="python") for unit in owned_units],
                }
            )
        )
    questions.sort(key=lambda question: (question.question_id, question.statement))

    decisions = _merge_audit_decisions(packet.merge_decisions, new_decisions)
    canonical = PaperStudyPacketV2.model_validate(
        {
            **packet.model_dump(mode="python"),
            "research_questions": [
                question.model_dump(mode="python") for question in questions
            ],
            "merge_decisions": [
                decision.model_dump(mode="python") for decision in decisions
            ],
        }
    )
    _validate_canonicalization_input(canonical)
    _validate_canonical_output(canonical)
    return canonical


def packet_sha256(packet: PaperStudyPacketV2) -> str:
    """Hash the complete packet, including prior audit state, for stale-plan checks."""

    return hashlib.sha256(_canonical_json_bytes(packet.model_dump(mode="json"))).hexdigest()


def _planned_pair_score(
    left: KeyedEntity,
    right: KeyedEntity,
    *,
    source_values: dict[str, StrictModel],
    policy: CanonicalizationPolicy,
) -> int:
    """Score an exact-key pair, applying hard statistical conflict gates."""

    if left.key.digest != right.key.digest:
        return 0
    if left.ref.entity_type != "result":
        return policy.exact_match_score_ppm
    left_value = source_values[_entity_ref_sort_key(left.ref)]
    right_value = source_values[_entity_ref_sort_key(right.ref)]
    if not isinstance(left_value, ResultObservation) or not isinstance(
        right_value, ResultObservation
    ):
        raise CanonicalizationPlanError("Result plan record has a non-Result value")
    if _optional_values_conflict(left_value.p_value, right_value.p_value):
        return 0
    if _optional_values_conflict(
        left_value.n_sample_size,
        right_value.n_sample_size,
    ):
        return 0
    return policy.exact_match_score_ppm


def _optional_values_conflict(left: object | None, right: object | None) -> bool:
    return left is not None and right is not None and left != right


def _index_source_entities(
    packet: PaperStudyPacketV2,
) -> dict[tuple[EntityType, str, str, str], StrictModel]:
    """Index every source entity by its fully scoped identity."""

    values: dict[tuple[EntityType, str, str, str], StrictModel] = {}
    for question in packet.research_questions:
        for unit in question.study_units:
            values[("study_unit", question.question_id, unit.unit_id, unit.unit_id)] = unit
            for result in unit.results:
                values[
                    ("result", question.question_id, unit.unit_id, result.result_id)
                ] = result
            for claim in unit.claims:
                values[("claim", question.question_id, unit.unit_id, claim.claim_id)] = claim
    return values


def _source_value(
    ref: EntityRef,
    values: dict[tuple[EntityType, str, str, str], StrictModel],
    expected_type: type[T],
) -> T:
    identity = (
        ref.entity_type,
        ref.question_id,
        ref.source_unit_id,
        ref.source_entity_id,
    )
    try:
        value = values[identity]
    except KeyError as error:
        raise CanonicalizationPlanError(f"Plan references a missing entity: {identity}") from error
    if not isinstance(value, expected_type):
        raise CanonicalizationPlanError(
            f"Plan entity {identity} is not a {expected_type.__name__}"
        )
    content_sha256 = _sha256_json(value.model_dump(mode="json"))
    if content_sha256 != ref.content_sha256:
        raise CanonicalizationPlanError(f"Plan content hash mismatch for entity: {identity}")
    return value


def _required_rewrite(
    rewrites: dict[str, str],
    source_id: str,
    entity_label: str,
) -> str:
    try:
        return rewrites[source_id]
    except KeyError as error:
        raise CanonicalizationPlanError(
            f"No canonical {entity_label} rewrite exists for {source_id}"
        ) from error


def _representative_sort_key(
    ref: EntityRef,
    value: StrictModel,
) -> tuple[int, int, int, bytes, str]:
    """Prefer exact, information-rich records with a deterministic tie-break."""

    provenances: list[Provenance] = []
    if isinstance(value, (ResultObservation, Claim)):
        provenances = [value.provenance, *value.additional_provenance]
    lacks_exact_provenance = int(bool(provenances) and all(p.paraphrased for p in provenances))

    if isinstance(value, ResultObservation):
        structured = sum(
            item is not None
            for item in (
                value.quantitative_value,
                value.unit,
                value.p_value,
                value.n_sample_size,
            )
        )
        information_length = len(normalize_scientific_text(value.value_raw_text))
    elif isinstance(value, Claim):
        structured = len(set(value.inference_basis_ids))
        information_length = len(normalize_scientific_text(value.statement))
    elif isinstance(value, StudyUnit):
        structured = sum(
            len(items)
            for items in (
                value.experiments_or_tasks,
                value.datasets,
                value.methods,
                value.results,
                value.claims,
                value.evidence_spans,
            )
        )
        information_length = len(normalize_scientific_text(value.name))
    else:
        structured = 0
        information_length = 0

    payload = value.model_dump(mode="json")
    for identity_field in ("unit_id", "result_id", "claim_id"):
        payload.pop(identity_field, None)
    payload.pop("provenance", None)
    payload.pop("additional_provenance", None)
    return (
        lacks_exact_provenance,
        -structured,
        -information_length,
        _canonical_json_bytes(payload),
        _entity_ref_sort_key(ref),
    )


def _merge_unit_shell(
    canonical_id: str,
    representative: StudyUnit,
    members: Sequence[StudyUnit],
) -> StudyUnit:
    tasks = sorted(
        {task for member in members for task in member.experiments_or_tasks},
        key=lambda task: (normalize_scientific_text(task), task),
    )
    datasets = _model_union(member.datasets for member in members)
    methods = _model_union(member.methods for member in members)
    evidence_spans = _model_union(member.evidence_spans for member in members)
    # Dataset/Method/EvidenceSpan do not yet have their own canonical rewrite
    # contract. Retain distinct records losslessly even when a source-local ID
    # is reused; silently selecting one would discard extracted information.
    return StudyUnit.model_validate(
        {
            **representative.model_dump(mode="python"),
            "unit_id": canonical_id,
            "experiments_or_tasks": tasks,
            "datasets": [value.model_dump(mode="python") for value in datasets],
            "methods": [value.model_dump(mode="python") for value in methods],
            "evidence_spans": [
                value.model_dump(mode="python") for value in evidence_spans
            ],
            "results": [],
            "claims": [],
        }
    )


def _model_union(groups: Iterable[Sequence[T]]) -> list[T]:
    unique: dict[bytes, T] = {}
    for group in groups:
        for value in group:
            if not isinstance(value, StrictModel):
                raise CanonicalizationPlanError("Nested union requires StrictModel values")
            encoded = _canonical_json_bytes(value.model_dump(mode="json"))
            unique.setdefault(encoded, value)
    return [unique[key] for key in sorted(unique)]


def _merge_result(
    canonical_id: str,
    representative: ResultObservation,
    members: Sequence[ResultObservation],
) -> ResultObservation:
    provenance, additional = _provenance_union(members)
    p_value = _merge_optional_field(
        (member.p_value for member in members),
        field_name="p_value",
        canonical_id=canonical_id,
    )
    n_sample_size = _merge_optional_field(
        (member.n_sample_size for member in members),
        field_name="n_sample_size",
        canonical_id=canonical_id,
    )
    return ResultObservation.model_validate(
        {
            **representative.model_dump(mode="python"),
            "result_id": canonical_id,
            "p_value": p_value,
            "n_sample_size": n_sample_size,
            "provenance": provenance.model_dump(mode="python"),
            "additional_provenance": [
                item.model_dump(mode="python") for item in additional
            ],
        }
    )


def _merge_claim(
    canonical_id: str,
    representative: Claim,
    members: Sequence[Claim],
    *,
    basis_ids: Sequence[str],
) -> Claim:
    provenance, additional = _provenance_union(members)
    return Claim.model_validate(
        {
            **representative.model_dump(mode="python"),
            "claim_id": canonical_id,
            "inference_basis_ids": list(basis_ids),
            "provenance": provenance.model_dump(mode="python"),
            "additional_provenance": [
                item.model_dump(mode="python") for item in additional
            ],
        }
    )


def _merge_optional_field(
    values: Iterable[T | None],
    *,
    field_name: str,
    canonical_id: str,
) -> T | None:
    reported = {value for value in values if value is not None}
    if len(reported) > 1:
        raise CanonicalizationPlanError(
            f"Conflicting {field_name} values in cluster {canonical_id}: "
            f"{sorted(reported)}"
        )
    return next(iter(reported), None)


def _provenance_union(
    members: Sequence[ResultObservation | Claim],
) -> tuple[Provenance, list[Provenance]]:
    unique: dict[bytes, Provenance] = {}
    for member in members:
        for provenance in (member.provenance, *member.additional_provenance):
            encoded = _canonical_json_bytes(provenance.model_dump(mode="json"))
            unique.setdefault(encoded, provenance)
    if not unique:
        raise CanonicalizationPlanError("A Result or Claim merge has no provenance")
    ordered = sorted(unique.values(), key=_provenance_sort_key)
    return ordered[0], ordered[1:]


def _provenance_sort_key(provenance: Provenance) -> tuple[bool, str, int, int, str]:
    encoded = _canonical_json_bytes(provenance.model_dump(mode="json"))
    return (
        provenance.paraphrased,
        provenance.chunk_id,
        provenance.page_start,
        provenance.page_end,
        hashlib.sha256(encoded).hexdigest(),
    )


def _merge_decision(
    cluster: CanonicalClusterPlan,
    *,
    representative_ref: EntityRef,
    source_values: dict[tuple[EntityType, str, str, str], StrictModel],
    policy: CanonicalizationPolicy,
) -> MergeDecision | None:
    if len(cluster.members) == 1:
        return None
    source_entities = []
    for ref in cluster.members:
        value = _source_value(ref, source_values, StrictModel)
        occurrences = []
        if isinstance(value, (ResultObservation, Claim)):
            for index, provenance in enumerate(
                (value.provenance, *value.additional_provenance)
            ):
                encoded = _canonical_json_bytes(provenance.model_dump(mode="json"))
                occurrences.append(
                    {
                        "index": index if index > 0 else 0,
                        "pointer": provenance_pointer(provenance).model_dump(mode="json"),
                        "record": provenance.model_dump(mode="json"),
                        "record_sha256": hashlib.sha256(encoded).hexdigest(),
                        "role": "primary" if index == 0 else "additional",
                    }
                )
        elif isinstance(value, StudyUnit):
            for index, evidence_span in enumerate(value.evidence_spans):
                provenance = evidence_span.provenance
                encoded = _canonical_json_bytes(provenance.model_dump(mode="json"))
                occurrences.append(
                    {
                        "evidence_span_id": evidence_span.span_id,
                        "index": index,
                        "pointer": provenance_pointer(provenance).model_dump(mode="json"),
                        "record": provenance.model_dump(mode="json"),
                        "record_sha256": hashlib.sha256(encoded).hexdigest(),
                        "role": "evidence_span",
                    }
                )
        source_entities.append(
            {
                "provenance_occurrences": occurrences,
                "ref": ref.model_dump(mode="json"),
            }
        )
    reason = {
        "algorithm_version": policy.algorithm_version,
        "audit_schema": "odracir.paper-study.merge-decision/v1",
        "canonical_key_digest": cluster.canonical_key.digest,
        "canonical_scope_digest": cluster.canonical_key.scope_digest,
        "entity_type": cluster.entity_type,
        "match_rule": cluster.match_rule,
        "namespace": policy.namespace,
        "normalization_version": policy.normalization_version,
        "representative_source": representative_ref.model_dump(mode="json"),
        "score_ppm": cluster.score_ppm,
        "source_entities": source_entities,
    }
    merged_ids = sorted(
        {
            member.source_entity_id
            for member in cluster.members
            if member.source_entity_id != cluster.canonical_id
        }
    )
    if not merged_ids:
        raise CanonicalizationPlanError(
            f"Merge cluster {cluster.canonical_id} has no absorbed source IDs"
        )
    return MergeDecision(
        surviving_id=cluster.canonical_id,
        merged_ids=merged_ids,
        reason=_canonical_json_bytes(reason).decode("utf-8"),
    )


def _merge_audit_decisions(
    existing: Sequence[MergeDecision],
    created: Sequence[MergeDecision],
) -> list[MergeDecision]:
    unique: dict[tuple[str, tuple[str, ...], str], MergeDecision] = {}
    for decision in (*existing, *created):
        reason = _canonicalize_reason(decision.reason)
        normalized = MergeDecision(
            surviving_id=decision.surviving_id,
            merged_ids=sorted(decision.merged_ids),
            reason=reason,
        )
        key = (
            normalized.surviving_id,
            tuple(normalized.merged_ids),
            normalized.reason,
        )
        unique.setdefault(key, normalized)
    return [unique[key] for key in sorted(unique)]


def _canonicalize_reason(reason: str) -> str:
    try:
        parsed = json.loads(reason)
    except (json.JSONDecodeError, TypeError):
        return reason
    return _canonical_json_bytes(parsed).decode("utf-8")


def _validate_canonical_output(packet: PaperStudyPacketV2) -> None:
    """Validate global ID uniqueness and every local Claim -> Result edge."""

    unit_ids: set[str] = set()
    result_ids: set[str] = set()
    claim_ids: set[str] = set()
    for question in packet.research_questions:
        for unit in question.study_units:
            if not unit.unit_id.startswith("su_") or unit.unit_id in unit_ids:
                raise CanonicalizationPlanError(
                    f"Invalid or duplicate canonical StudyUnit ID: {unit.unit_id}"
                )
            unit_ids.add(unit.unit_id)
            local_results = {result.result_id for result in unit.results}
            for result in unit.results:
                if not result.result_id.startswith("res_") or result.result_id in result_ids:
                    raise CanonicalizationPlanError(
                        f"Invalid or duplicate canonical Result ID: {result.result_id}"
                    )
                result_ids.add(result.result_id)
            for claim in unit.claims:
                if not claim.claim_id.startswith("clm_") or claim.claim_id in claim_ids:
                    raise CanonicalizationPlanError(
                        f"Invalid or duplicate canonical Claim ID: {claim.claim_id}"
                    )
                claim_ids.add(claim.claim_id)
                if not set(claim.inference_basis_ids) <= local_results:
                    raise CanonicalizationPlanError(
                        f"Claim {claim.claim_id} references a Result outside its StudyUnit"
                    )


_ENTITY_ID_PREFIX: dict[EntityType, str] = {
    "study_unit": "su",
    "result": "res",
    "claim": "clm",
}

_TOKEN_RE = re.compile(
    r"(?:e|p)\d+(?:\.\d+)?|[a-z][a-z0-9]*(?:-[a-z0-9]+)*|"
    r"\d+(?:\.\d+)?|[%<>]=?|[=!+\-/]"
)
_STAGE_RE = re.compile(r"\b(?:e|p)\d+(?:\.\d+)?\b")
_TIME_RE = re.compile(
    r"\b(?P<value>\d+(?:\.\d+)?)\s*"
    r"(?P<unit>min|mins|minute|minutes|h|hr|hrs|hour|hours|"
    r"d|day|days|wk|week|weeks|month|months|yr|year|years)\b"
)
_DOSE_RE = re.compile(
    r"\b(?P<value>\d+(?:\.\d+)?)\s*"
    r"(?P<unit>pm|nm|um|mm|m|pg|ng|ug|mg|g|ul|ml|l|"
    r"pmol|nmol|umol|mmol|mol|percent|%)\b"
)
_GENOTYPE_RE = re.compile(
    r"\b([a-z][a-z0-9]*(?:-dko|-eko|-ko)|[a-z][a-z0-9]* knockout)\b"
)

_LEXICON: dict[ProtectedConditionKind, dict[str, str]] = {
    "negation": {
        "no": "no",
        "not": "not",
        "without": "without",
        "failed to": "failed",
        "lack of": "absent",
    },
    "direction": {
        "increase": "increase",
        "increased": "increase",
        "higher": "increase",
        "upregulated": "increase",
        "decrease": "decrease",
        "decreased": "decrease",
        "lower": "decrease",
        "downregulated": "decrease",
        "unchanged": "no_change",
        "no change": "no_change",
    },
    "modality": {
        "associated with": "association",
        "correlated with": "association",
        "necessary": "necessary",
        "required for": "necessary",
        "sufficient": "sufficient",
        "causes": "causal",
        "causal": "causal",
    },
    "causal_rung": {
        "correlation": "association",
        "association": "association",
        "perturbation": "perturbation",
        "rescue": "rescue",
        "reconstitution": "rescue",
        "reversal": "rescue",
        "mechanism": "mechanism",
        "mechanistic": "mechanism",
    },
    "dataset_split": {
        "training set": "train",
        "train set": "train",
        "validation set": "validation",
        "test set": "test",
        "holdout": "holdout",
        "held-out": "holdout",
    },
    "study_arm": {
        "control group": "control",
        "control arm": "control",
        "placebo": "placebo",
        "baseline": "baseline",
        "primary endpoint": "primary_endpoint",
        "secondary endpoint": "secondary_endpoint",
    },
    "perturbation": {
        "knockout": "knockout",
        "knockdown": "knockdown",
        "deletion": "deletion",
        "inhibition": "inhibition",
        "inhibitor": "inhibition",
        "overexpression": "overexpression",
        "laser ablation": "laser_ablation",
        "compression": "compression",
        "treatment": "treatment",
    },
}

_UNIT_ALIASES = {
    "": "not_reported",
    "%": "%",
    "percent": "%",
    "percentage": "%",
    "μm": "um",
    "um": "um",
    "micrometer": "um",
    "micrometers": "um",
    "hr": "h",
    "hrs": "h",
    "hour": "h",
    "hours": "h",
}


def _collect_lexicon_atoms(
    normalized: str,
    atoms: set[tuple[ProtectedConditionKind, str]],
) -> None:
    padded = f" {normalized} "
    for kind, terms in _LEXICON.items():
        for term, canonical in terms.items():
            normalized_term = normalize_scientific_text(term)
            if f" {normalized_term} " in padded:
                atoms.add((kind, canonical))


def _normalize_quantity(value: str, unit: str) -> str:
    return f"{_normalize_decimal_string(value)} {_normalize_unit(unit)}"


def _normalize_decimal(value: float) -> str:
    return _normalize_decimal_string(str(value))


def _normalize_decimal_string(value: str) -> str:
    decimal = Decimal(value)
    if decimal == 0:
        return "0"
    return format(decimal.normalize(), "f")


def _normalize_unit(unit: str | None) -> str:
    normalized = normalize_scientific_text(unit or "")
    return _UNIT_ALIASES.get(normalized, normalized or "not_reported")


def _condition_strings(
    conditions: Sequence[ProtectedCondition],
) -> tuple[str, ...]:
    return tuple(f"{condition.kind}:{condition.value}" for condition in conditions)


def _join_nonempty(*values: str) -> str:
    return " | ".join(value for value in values if value)


def _components(
    raw: dict[str, Iterable[str]],
) -> tuple[CanonicalComponent, ...]:
    components: list[CanonicalComponent] = []
    for name in sorted(raw):
        values = tuple(sorted({value for value in raw[name] if value}))
        if values:
            components.append(CanonicalComponent(name=name, values=values))
    if not components:
        raise ValueError("Canonical keys require at least one non-empty component")
    return tuple(components)


def _build_key(
    *,
    entity_type: EntityType,
    paper_id: str,
    scope_digest: str,
    components: tuple[CanonicalComponent, ...],
    policy: CanonicalizationPolicy,
) -> CanonicalKey:
    digest = _canonical_key_digest(
        namespace=policy.namespace,
        normalization_version=policy.normalization_version,
        entity_type=entity_type,
        paper_id=paper_id,
        scope_digest=scope_digest,
        components=components,
    )
    canonical_id = f"{_ENTITY_ID_PREFIX[entity_type]}_{digest[: policy.id_digest_length]}"
    return CanonicalKey(
        namespace=policy.namespace,
        normalization_version=policy.normalization_version,
        entity_type=entity_type,
        paper_id=paper_id,
        scope_digest=scope_digest,
        components=components,
        digest=digest,
        canonical_id=canonical_id,
        id_digest_length=policy.id_digest_length,
    )


def _canonical_key_digest(
    *,
    namespace: str,
    normalization_version: str,
    entity_type: EntityType,
    paper_id: str,
    scope_digest: str,
    components: Sequence[CanonicalComponent],
) -> str:
    payload = {
        "components": [
            {"name": component.name, "values": list(component.values)}
            for component in components
        ],
        "entity_type": entity_type,
        "namespace": namespace,
        "normalization_version": normalization_version,
        "paper_id": paper_id,
        "scope_digest": scope_digest,
    }
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def _keyed_entity(
    *,
    entity_type: EntityType,
    question_id: str,
    unit_id: str,
    source_entity_id: str,
    value: StrictModel,
    key: CanonicalKey,
) -> KeyedEntity:
    content_sha256 = hashlib.sha256(
        _canonical_json_bytes(value.model_dump(mode="json"))
    ).hexdigest()
    return KeyedEntity(
        ref=EntityRef(
            entity_type=entity_type,
            question_id=question_id,
            source_unit_id=unit_id,
            source_entity_id=source_entity_id,
            content_sha256=content_sha256,
        ),
        key=key,
    )


def _validate_canonicalization_input(packet: PaperStudyPacketV2) -> None:
    seen: dict[EntityType, set[str]] = {
        "study_unit": set(),
        "result": set(),
        "claim": set(),
    }
    question_ids: set[str] = set()
    for question in packet.research_questions:
        if question.question_id in question_ids:
            raise CanonicalizationInputError(
                f"Duplicate ResearchQuestion source ID: {question.question_id}"
            )
        question_ids.add(question.question_id)
        for unit in question.study_units:
            _require_source_id_unique("study_unit", unit.unit_id, seen)
            result_ids = {result.result_id for result in unit.results}
            if len(result_ids) != len(unit.results):
                raise CanonicalizationInputError(
                    f"Duplicate result_id inside StudyUnit {unit.unit_id}"
                )
            for result in unit.results:
                _require_source_id_unique("result", result.result_id, seen)
            for claim in unit.claims:
                _require_source_id_unique("claim", claim.claim_id, seen)
                missing = set(claim.inference_basis_ids) - result_ids
                if missing:
                    raise CanonicalizationInputError(
                        f"Claim {claim.claim_id} has cross-unit or missing Result refs: "
                        f"{sorted(missing)}"
                    )


def _require_source_id_unique(
    entity_type: EntityType,
    source_id: str,
    seen: dict[EntityType, set[str]],
) -> None:
    if source_id in seen[entity_type]:
        raise CanonicalizationInputError(
            f"Duplicate global {entity_type} source ID: {source_id}"
        )
    seen[entity_type].add(source_id)


def _validate_truncated_ids(records: Sequence[KeyedEntity]) -> None:
    digests_by_id: dict[str, set[str]] = defaultdict(set)
    for record in records:
        digests_by_id[record.key.canonical_id].add(record.key.digest)
    collisions = {
        canonical_id: sorted(digests)
        for canonical_id, digests in digests_by_id.items()
        if len(digests) > 1
    }
    if collisions:
        raise CanonicalizationPlanError(
            f"Truncated canonical ID collision; increase id_digest_length: {collisions}"
        )


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _ordered_pair(left: str, right: str) -> tuple[str, str]:
    return (left, right) if left < right else (right, left)


def _entity_ref_sort_key(ref: EntityRef) -> str:
    return "\0".join(
        (
            ref.entity_type,
            ref.question_id,
            ref.source_unit_id,
            ref.source_entity_id,
            ref.content_sha256,
        )
    )


def _keyed_entity_sort_key(entity: KeyedEntity) -> str:
    return "\0".join((entity.key.digest, _entity_ref_sort_key(entity.ref)))
