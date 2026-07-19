"""Strongly typed core data contract for Odracir paper studies."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from collections import Counter
from collections.abc import Mapping
from difflib import SequenceMatcher
from types import MappingProxyType
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    ValidationInfo,
    field_serializer,
    field_validator,
    model_validator,
)


CoverageStatus = Literal["extracted", "irrelevant", "failed", "not_selected"]
ClaimPolarity = Literal["positive", "negative", "neutral"]
PacketStatus = Literal["accepted", "provisional"]
LedgerEntityType = Literal["study_unit", "result", "claim"]
AssertionStatus = Literal["supported", "contested", "superseded", "unresolved"]
AssertionRelationType = Literal[
    "same_as",
    "broader_than",
    "narrower_than",
    "supports",
    "contradicts",
    "conditioned_on",
    "qualifies",
    "supersedes",
]
AlignmentRelationType = Literal[
    "exact",
    "equivalent",
    "narrower",
    "broader",
    "supports",
    "contradicts",
    "new_assertion",
]
LedgerEventType = Literal[
    "assertion_added",
    "assertion_evidence_added",
    "assertion_revised",
    "relation_added",
    "batch_committed",
]
PROVENANCE_SIMILARITY_THRESHOLD = 0.95
PROVENANCE_SOURCE_TEXT_CONTEXT_KEY = "provenance_source_texts"
_SHA256_PATTERN = r"^sha256:[0-9a-f]{64}$"


def _freeze_json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze_json_value(item) for key, item in value.items()}
        )
    if isinstance(value, list | tuple):
        return tuple(_freeze_json_value(item) for item in value)
    return value


def _thaw_json_value(value: object) -> JsonValue:
    if isinstance(value, Mapping):
        return {str(key): _thaw_json_value(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_thaw_json_value(item) for item in value]
    return value  # type: ignore[return-value]


def _canonical_json_digest(value: Mapping[str, object]) -> str:
    payload = json.dumps(
        _thaw_json_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def provenance_text_similarity_ratio(text_excerpt: str, source_text: str) -> float:
    """Return the best local SequenceMatcher ratio inside a longer source chunk."""

    excerpt = _normalize_similarity_text(text_excerpt)
    source = _normalize_similarity_text(source_text)
    if not excerpt or not source:
        return 0.0
    if excerpt in source:
        return 1.0
    if len(excerpt) > len(source):
        return SequenceMatcher(None, excerpt, source, autojunk=False).ratio()

    # SequenceMatcher's whole-string ratio unfairly penalizes an excerpt merely
    # because its source chunk is longer. Score equal-length local windows. A
    # sliding character-multiset overlap supplies a safe upper bound for each
    # window's possible SequenceMatcher ratio, so low-potential windows can be
    # skipped without turning the search into a heuristic.
    excerpt_length = len(excerpt)
    excerpt_counts = Counter(excerpt)
    window_counts = Counter(source[:excerpt_length])
    overlap_count = sum((excerpt_counts & window_counts).values())
    candidates = [(overlap_count, 0)]
    for start in range(1, len(source) - excerpt_length + 1):
        removed = source[start - 1]
        before = min(excerpt_counts[removed], window_counts[removed])
        window_counts[removed] -= 1
        after = min(excerpt_counts[removed], window_counts[removed])
        overlap_count += after - before

        added = source[start + excerpt_length - 1]
        before = min(excerpt_counts[added], window_counts[added])
        window_counts[added] += 1
        after = min(excerpt_counts[added], window_counts[added])
        overlap_count += after - before
        candidates.append((overlap_count, start))

    candidates.sort(key=lambda item: (-item[0], item[1]))
    best_ratio = 0.0
    for upper_match_count, start in candidates:
        if upper_match_count / excerpt_length <= best_ratio:
            break
        candidate = source[start : start + excerpt_length]
        ratio = SequenceMatcher(None, excerpt, candidate, autojunk=False).ratio()
        best_ratio = max(best_ratio, ratio)
        if best_ratio == 1.0:
            break
    return best_ratio


def _normalize_similarity_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split())


class StrictModel(BaseModel):
    """Base class for closed, strictly validated Odracir contracts."""

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        strict=True,
        validate_assignment=True,
        allow_inf_nan=False,
    )


class Provenance(StrictModel):
    """Location and source text supporting a scientific object."""

    chunk_id: str = Field(min_length=1, description="Identifier of the source text chunk.")
    page_start: int = Field(ge=1, description="One-based first page containing the evidence.")
    page_end: int = Field(ge=1, description="One-based last page containing the evidence.")
    text_excerpt: str = Field(
        min_length=1,
        description="Exact source excerpt, or a paraphrase when paraphrased is true.",
    )
    paraphrased: bool = Field(
        ...,
        description="Whether text_excerpt is a paraphrase rather than an exact quotation.",
    )

    @model_validator(mode="after")
    def validate_page_range(self) -> Provenance:
        """Reject inverted source page ranges."""

        if self.page_end < self.page_start:
            raise ValueError("page_end must be greater than or equal to page_start")
        return self

    @model_validator(mode="after")
    def validate_source_alignment(self, info: ValidationInfo) -> Provenance:
        """Enforce source similarity when the caller supplies chunk text context."""

        context = info.context
        if not isinstance(context, Mapping):
            return self
        source_texts = context.get(PROVENANCE_SOURCE_TEXT_CONTEXT_KEY)
        if source_texts is None:
            return self
        if not isinstance(source_texts, Mapping):
            raise ValueError(
                f"{PROVENANCE_SOURCE_TEXT_CONTEXT_KEY} context must be a mapping"
            )
        source_text = source_texts.get(self.chunk_id)
        if not isinstance(source_text, str):
            raise ValueError(f"No source text context exists for chunk {self.chunk_id}")
        self.enforce_source_alignment(source_text)
        return self

    def enforce_source_alignment(self, source_text: str) -> float | None:
        """Classify a close quotation or reject an unmarked paraphrase."""

        if self.paraphrased:
            return None
        ratio = provenance_text_similarity_ratio(self.text_excerpt, source_text)
        if ratio < PROVENANCE_SIMILARITY_THRESHOLD:
            raise ValueError(
                f"text_excerpt similarity ratio {ratio:.4f} is below "
                f"{PROVENANCE_SIMILARITY_THRESHOLD:.2f}; it must be marked "
                "paraphrased=True"
            )
        return ratio


class Dataset(StrictModel):
    """Dataset or data split used by a study unit."""

    dataset_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    version_or_split: str | None = None
    description: str | None = None


class Method(StrictModel):
    """Method and the protocol by which it was applied."""

    method_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    protocol_description: str = Field(min_length=1)


class ResultObservation(StrictModel):
    """A scientific result represented as a typed metric observation."""

    result_id: str = Field(min_length=1)
    metric_name: str = Field(
        min_length=1,
        description="Name of the measured metric, such as Accuracy or Expression Level.",
    )
    value_raw_text: str = Field(
        min_length=1,
        description="Original textual expression of the reported result.",
    )
    quantitative_value: float | None = None
    unit: str | None = None
    p_value: float | None = Field(default=None, ge=0.0, le=1.0)
    n_sample_size: int | None = Field(default=None, ge=1)
    provenance: Provenance
    additional_provenance: list[Provenance] = Field(default_factory=list)


class Claim(StrictModel):
    """An author claim grounded in one or more result observations."""

    claim_id: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    polarity: ClaimPolarity
    inference_basis_ids: list[str] = Field(
        default_factory=list,
        description="Identifiers of results supporting this claim.",
    )
    provenance: Provenance
    additional_provenance: list[Provenance] = Field(default_factory=list)


class EvidenceSpan(StrictModel):
    """A normalized evidence span retained within a study unit."""

    span_id: str = Field(min_length=1)
    content: str = Field(min_length=1)
    provenance: Provenance


class StudyUnit(StrictModel):
    """All context belonging to one experiment, task, or study action."""

    unit_id: str = Field(min_length=1)
    name: str = Field(
        min_length=1,
        description="Short name of the experiment or study step.",
    )
    experiments_or_tasks: list[str] = Field(
        default_factory=list,
        description="Descriptions of experiments or tasks performed in this unit.",
    )
    datasets: list[Dataset] = Field(default_factory=list)
    methods: list[Method] = Field(default_factory=list)
    results: list[ResultObservation] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    evidence_spans: list[EvidenceSpan] = Field(default_factory=list)


class ResearchQuestion(StrictModel):
    """A research question and the study units designed to answer it."""

    question_id: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    study_units: list[StudyUnit] = Field(
        default_factory=list,
        description="Study units designed to answer this research question.",
    )


class MergeDecision(StrictModel):
    """Audit record for entities merged during canonicalization."""

    surviving_id: str = Field(min_length=1)
    merged_ids: list[str] = Field(min_length=1)
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_merged_ids(self) -> MergeDecision:
        """Require a non-redundant list of identifiers absorbed by the survivor."""

        if self.surviving_id in self.merged_ids:
            raise ValueError("surviving_id must not appear in merged_ids")
        if len(self.merged_ids) != len(set(self.merged_ids)):
            raise ValueError("merged_ids must not contain duplicates")
        return self


class PacketValidationWarning(StrictModel):
    """A non-fatal, auditable packet repair or validation observation."""

    model_config = ConfigDict(frozen=True)

    code: str = Field(
        min_length=1,
        description="Stable machine-readable warning code.",
    )
    message: str = Field(
        min_length=1,
        description="Human-readable explanation of the non-fatal issue.",
    )
    json_path: str | None = Field(
        default=None,
        min_length=1,
        description="Optional JSON Pointer-like location of the affected value.",
    )
    repair: str | None = Field(
        default=None,
        min_length=1,
        description="Optional deterministic repair that was applied.",
    )

    def stable_key(self) -> tuple[str, str, str, str]:
        """Return the canonical warning identity and ordering key."""

        return (
            self.code,
            self.json_path or "",
            self.message,
            self.repair or "",
        )


class SemanticQualityIssue(StrictModel):
    """One judge-audited extraction error or source omission."""

    item_id: str | None = None
    description: str = Field(min_length=1)
    source_chunk_id: str | None = None
    source_excerpt: str | None = None
    source_excerpt_verified: bool | None = None


class ExtractionQualityAssessment(StrictModel):
    """Agents-K1-style semantic precision/recall audit for one paper packet."""

    protocol: Literal["semantic-prf-v1"] = "semantic-prf-v1"
    judge_provider: str = Field(min_length=1)
    judge_model: str = Field(min_length=1)
    extracted_item_count: int = Field(ge=0)
    correct_item_count: int = Field(ge=0)
    incorrect_item_count: int = Field(ge=0)
    missed_core_item_count: int = Field(ge=0)
    precision: float = Field(ge=0.0, le=1.0)
    recall: float = Field(ge=0.0, le=1.0)
    f1: float = Field(ge=0.0, le=1.0)
    deterministic_rule_score: float = Field(ge=0.0, le=1.0)
    incorrect_items: list[SemanticQualityIssue] = Field(default_factory=list)
    missed_core_items: list[SemanticQualityIssue] = Field(default_factory=list)
    evidence_strength_observability: dict[str, float | None] = Field(
        default_factory=dict,
        description=(
            "EvidenceNet-inspired availability signals; these are not extraction "
            "quality and are not folded into semantic F1."
        ),
    )

    @model_validator(mode="after")
    def validate_counts_and_scores(self) -> ExtractionQualityAssessment:
        if self.correct_item_count + self.incorrect_item_count != self.extracted_item_count:
            raise ValueError("correct plus incorrect must equal extracted item count")
        if len(self.incorrect_items) != self.incorrect_item_count:
            raise ValueError("incorrect item details must match incorrect_item_count")
        if len(self.missed_core_items) != self.missed_core_item_count:
            raise ValueError("missed item details must match missed_core_item_count")
        # Empty extractions are valid for non-study documents such as author
        # corrections.  Use the standard empty-set convention: precision is
        # perfect when nothing unsupported was emitted, while recall is perfect
        # only when the source audit also finds no missed core scientific item.
        precision = (
            self.correct_item_count / self.extracted_item_count
            if self.extracted_item_count
            else 1.0
        )
        recall_denominator = self.correct_item_count + self.missed_core_item_count
        recall = (
            self.correct_item_count / recall_denominator
            if recall_denominator
            else 1.0
        )
        f1 = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
        if self.precision != round(precision, 4):
            raise ValueError("precision does not match audited counts")
        if self.recall != round(recall, 4):
            raise ValueError("recall does not match audited counts")
        if self.f1 != round(f1, 4):
            raise ValueError("f1 does not match audited counts")
        return self


class PaperStudyPacketV2(StrictModel):
    """Canonical, single-artifact representation of an Odracir v2 paper study."""

    # Older packets remain readable for downstream migration.
    schema_version: Literal["2.0", "2.1", "2.2"] = "2.2"
    paper_id: str = Field(min_length=1)
    status: PacketStatus = "accepted"
    requires_reconciliation: bool = False
    validation_warnings: list[PacketValidationWarning] = Field(default_factory=list)
    metadata: dict[str, str] = Field(default_factory=dict)
    research_questions: list[ResearchQuestion] = Field(default_factory=list)
    limitations_and_boundaries: list[str] = Field(default_factory=list)
    quality_score: float = Field(default=0.0, ge=0.0, le=1.0)
    quality_assessment: ExtractionQualityAssessment | None = None
    coverage_ledger: dict[str, CoverageStatus] = Field(
        default_factory=dict,
        description="Per-chunk extraction status.",
    )
    merge_decisions: list[MergeDecision] = Field(default_factory=list)

    @field_validator("validation_warnings", mode="after")
    @classmethod
    def canonicalize_validation_warnings(
        cls,
        value: list[PacketValidationWarning],
    ) -> list[PacketValidationWarning]:
        """Sort warnings and collapse exact repeats for idempotent repair passes."""

        by_key = {warning.stable_key(): warning for warning in value}
        return [by_key[key] for key in sorted(by_key)]

    @model_validator(mode="after")
    def validate_admission_status(self) -> PaperStudyPacketV2:
        """Keep provisional admission and reconciliation requirements equivalent."""

        is_provisional = self.status == "provisional"
        if is_provisional != self.requires_reconciliation:
            raise ValueError(
                "status='provisional' if and only if "
                "requires_reconciliation=True"
            )
        return self


class LedgerEntityRef(StrictModel):
    """Paper-scoped reference used by corpus-level knowledge artifacts."""

    model_config = ConfigDict(frozen=True)

    paper_id: str = Field(min_length=1)
    entity_type: LedgerEntityType
    canonical_id: str = Field(min_length=1)
    packet_digest: str = Field(pattern=_SHA256_PATTERN)


class AssertionEvidenceRef(StrictModel):
    """Traceable paper evidence contributing to one global assertion."""

    model_config = ConfigDict(frozen=True)

    claim: LedgerEntityRef
    result_ids: tuple[str, ...] = Field(default_factory=tuple)
    source_chunk_ids: tuple[str, ...] = Field(min_length=1)
    admission_status: PacketStatus = "accepted"
    weight_ppm: int = Field(default=1_000_000, ge=1, le=1_000_000)

    @model_validator(mode="after")
    def validate_reference(self) -> AssertionEvidenceRef:
        if self.claim.entity_type != "claim":
            raise ValueError("AssertionEvidenceRef.claim must reference a claim")
        if self.result_ids != tuple(sorted(set(self.result_ids))):
            raise ValueError("result_ids must be sorted and unique")
        if self.source_chunk_ids != tuple(sorted(set(self.source_chunk_ids))):
            raise ValueError("source_chunk_ids must be sorted and unique")
        if self.admission_status == "accepted" and self.weight_ppm != 1_000_000:
            raise ValueError("accepted evidence must have weight_ppm=1000000")
        if self.admission_status == "provisional" and self.weight_ppm > 500_000:
            raise ValueError(
                "provisional evidence weight_ppm must be between 1 and 500000"
            )
        return self

    def stable_key(self) -> tuple[object, ...]:
        """Return the deterministic ordering key used by ledger snapshots."""

        return (
            self.claim.paper_id,
            self.claim.canonical_id,
            self.result_ids,
            self.source_chunk_ids,
            self.claim.packet_digest,
            self.admission_status,
            self.weight_ppm,
        )


class GlobalAssertion(StrictModel):
    """Corpus-level proposition without replacing its paper-local evidence."""

    model_config = ConfigDict(frozen=True)

    assertion_id: str = Field(min_length=1)
    proposition_key: str = Field(min_length=1)
    preferred_statement: str = Field(min_length=1)
    polarity: ClaimPolarity
    status: AssertionStatus
    conditions: tuple[str, ...] = Field(default_factory=tuple)
    evidence: tuple[AssertionEvidenceRef, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_stable_members(self) -> GlobalAssertion:
        if self.conditions != tuple(sorted(set(self.conditions))):
            raise ValueError("conditions must be sorted and unique")
        evidence_keys = tuple(item.stable_key() for item in self.evidence)
        if evidence_keys != tuple(sorted(set(evidence_keys))):
            raise ValueError("evidence must be stably sorted and unique")
        return self


class AssertionRelation(StrictModel):
    """Typed, auditable edge between two corpus-level assertions."""

    model_config = ConfigDict(frozen=True)

    relation_id: str = Field(min_length=1)
    source_assertion_id: str = Field(min_length=1)
    target_assertion_id: str = Field(min_length=1)
    relation_type: AssertionRelationType
    score_ppm: int = Field(ge=0, le=1_000_000)
    policy_version: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_endpoints(self) -> AssertionRelation:
        if self.source_assertion_id == self.target_assertion_id:
            raise ValueError("a relation must connect two different assertions")
        if self.relation_type in {"same_as", "contradicts"} and (
            self.source_assertion_id > self.target_assertion_id
        ):
            raise ValueError(
                "symmetric relation endpoints must use ascending assertion IDs"
            )
        return self

    def stable_key(self) -> tuple[str, str, str, str]:
        return (
            self.source_assertion_id,
            self.target_assertion_id,
            self.relation_type,
            self.relation_id,
        )


class LedgerEvent(StrictModel):
    """One immutable event in the cumulative global-ledger audit log."""

    model_config = ConfigDict(frozen=True)

    event_id: str = Field(min_length=1)
    sequence: int = Field(ge=1)
    revision: int = Field(ge=1)
    event_type: LedgerEventType
    subject_id: str = Field(min_length=1)
    payload: Mapping[str, JsonValue]
    payload_digest: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("payload", mode="after")
    @classmethod
    def freeze_payload(cls, value: Mapping[str, JsonValue]) -> Mapping[str, JsonValue]:
        return _freeze_json_value(value)  # type: ignore[return-value]

    @field_serializer("payload")
    def serialize_payload(self, value: Mapping[str, JsonValue]) -> JsonValue:
        return _thaw_json_value(value)

    @model_validator(mode="after")
    def validate_payload_digest(self) -> LedgerEvent:
        if self.payload_digest != _canonical_json_digest(self.payload):
            raise ValueError("payload_digest does not match canonical payload content")
        return self


class GlobalStateLedger(StrictModel):
    """Content-addressable, append-only materialization of corpus knowledge."""

    model_config = ConfigDict(frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    corpus_id: str = Field(min_length=1)
    revision: int = Field(default=0, ge=0)
    through_batch: int = Field(default=0, ge=0)
    parent_digest: str | None = Field(default=None, pattern=_SHA256_PATTERN)
    reducer_policy_version: str = Field(min_length=1)
    alignment_policy_version: str = Field(min_length=1)
    assertions: tuple[GlobalAssertion, ...] = Field(default_factory=tuple)
    relations: tuple[AssertionRelation, ...] = Field(default_factory=tuple)
    events: tuple[LedgerEvent, ...] = Field(default_factory=tuple)

    def _validate_evidence_event_cardinality(self) -> None:
        """Require a one-to-one audit event for every post-creation evidence ref."""

        evidence_event_counts = Counter(
            event.subject_id
            for event in self.events
            if event.event_type == "assertion_evidence_added"
        )
        for assertion in self.assertions:
            expected_evidence_count = 1 + evidence_event_counts[assertion.assertion_id]
            if len(assertion.evidence) != expected_evidence_count:
                raise ValueError(
                    "each assertion evidence after its initial evidence requires an "
                    "audit event; exactly one assertion_evidence_added event is required"
                )

    @model_validator(mode="after")
    def validate_append_only_snapshot(self) -> GlobalStateLedger:
        if self.revision != self.through_batch:
            raise ValueError("revision must equal through_batch")
        if self.revision == 0:
            if self.parent_digest is not None:
                raise ValueError("a genesis ledger must not have a parent_digest")
            if self.assertions or self.relations or self.events:
                raise ValueError("a genesis ledger must be empty")
            return self
        if self.parent_digest is None:
            raise ValueError("a non-genesis ledger requires parent_digest")

        assertion_ids = tuple(item.assertion_id for item in self.assertions)
        if assertion_ids != tuple(sorted(set(assertion_ids))):
            raise ValueError("assertions must be sorted by unique assertion_id")

        relation_keys = tuple(item.stable_key() for item in self.relations)
        if relation_keys != tuple(sorted(set(relation_keys))):
            raise ValueError("relations must be stably sorted and unique")
        relation_ids = [item.relation_id for item in self.relations]
        if len(relation_ids) != len(set(relation_ids)):
            raise ValueError("relation_id values must be unique")
        assertion_id_set = set(assertion_ids)
        for relation in self.relations:
            if {
                relation.source_assertion_id,
                relation.target_assertion_id,
            } - assertion_id_set:
                raise ValueError("every relation endpoint must exist in assertions")

        sequences = tuple(event.sequence for event in self.events)
        if sequences != tuple(range(1, len(self.events) + 1)):
            raise ValueError("event sequences must be contiguous and start at one")
        event_revisions = tuple(event.revision for event in self.events)
        if event_revisions != tuple(sorted(event_revisions)):
            raise ValueError("events must be ordered by non-decreasing revision")
        event_ids = [event.event_id for event in self.events]
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("event_id values must be unique")
        observed_revisions = {event.revision for event in self.events}
        if observed_revisions != set(range(1, self.revision + 1)):
            raise ValueError("events must cover every ledger revision")

        relation_id_set = set(relation_ids)
        for revision in range(1, self.revision + 1):
            revision_events = [
                event for event in self.events if event.revision == revision
            ]
            commit_events = [
                event
                for event in revision_events
                if event.event_type == "batch_committed"
            ]
            if len(commit_events) != 1 or revision_events[-1] != commit_events[0]:
                raise ValueError(
                    "each revision must end with exactly one batch_committed event"
                )
            if commit_events[0].subject_id != f"batch:{revision}":
                raise ValueError("batch_committed subject_id must identify its revision")

        for event in self.events:
            if event.event_type.startswith("assertion_"):
                if event.subject_id not in assertion_id_set:
                    raise ValueError("assertion event subject must exist in assertions")
            elif event.event_type == "relation_added":
                if event.subject_id not in relation_id_set:
                    raise ValueError("relation event subject must exist in relations")
        added_assertion_ids = {
            event.subject_id
            for event in self.events
            if event.event_type == "assertion_added"
        }
        if added_assertion_ids != assertion_id_set:
            raise ValueError("every assertion requires exactly one assertion_added subject")
        if sum(
            event.event_type == "assertion_added" for event in self.events
        ) != len(assertion_id_set):
            raise ValueError("each assertion must have exactly one assertion_added event")
        self._validate_evidence_event_cardinality()
        added_relation_ids = {
            event.subject_id
            for event in self.events
            if event.event_type == "relation_added"
        }
        if added_relation_ids != relation_id_set:
            raise ValueError("every relation requires exactly one relation_added subject")
        if sum(event.event_type == "relation_added" for event in self.events) != len(
            relation_id_set
        ):
            raise ValueError("each relation must have exactly one relation_added event")
        return self

    def validate_successor_of(self, previous: GlobalStateLedger) -> GlobalStateLedger:
        """Verify this snapshot is one append-only transition after ``previous``."""

        if self.corpus_id != previous.corpus_id:
            raise ValueError("successor corpus_id must match its parent")
        if self.reducer_policy_version != previous.reducer_policy_version:
            raise ValueError("reducer_policy_version cannot change within a ledger chain")
        if self.alignment_policy_version != previous.alignment_policy_version:
            raise ValueError("alignment_policy_version cannot change within a ledger chain")
        if self.revision != previous.revision + 1:
            raise ValueError("a successor must advance exactly one revision")
        if self.parent_digest != previous.digest():
            raise ValueError("parent_digest does not match the previous ledger")
        if self.events[: len(previous.events)] != previous.events:
            raise ValueError("a successor must preserve the complete prior event prefix")

        previous_assertions = {
            assertion.assertion_id: assertion for assertion in previous.assertions
        }
        current_assertions = {
            assertion.assertion_id: assertion for assertion in self.assertions
        }
        if previous_assertions.keys() - current_assertions.keys():
            raise ValueError("a successor must not remove assertions")
        current_revision_events = self.events[len(previous.events) :]
        revised_assertion_ids = {
            event.subject_id
            for event in current_revision_events
            if event.event_type == "assertion_revised"
        }
        evidence_event_counts = Counter(
            event.subject_id
            for event in current_revision_events
            if event.event_type == "assertion_evidence_added"
        )
        self._validate_evidence_event_cardinality()
        for assertion_id, old in previous_assertions.items():
            new = current_assertions[assertion_id]
            if (
                old.proposition_key,
                old.polarity,
                old.conditions,
            ) != (
                new.proposition_key,
                new.polarity,
                new.conditions,
            ):
                raise ValueError("assertion semantic identity cannot change")
            old_evidence = {item.stable_key() for item in old.evidence}
            new_evidence = {item.stable_key() for item in new.evidence}
            if old_evidence - new_evidence:
                raise ValueError("a successor must not remove assertion evidence")
            evidence_delta = len(new_evidence) - len(old_evidence)
            if evidence_delta != evidence_event_counts[assertion_id]:
                raise ValueError(
                    "each new assertion evidence requires exactly one audit event"
                )
            if (
                (old.preferred_statement, old.status)
                != (new.preferred_statement, new.status)
                and assertion_id not in revised_assertion_ids
            ):
                raise ValueError("assertion revision requires an audit event")

        previous_relations = {
            relation.relation_id: relation for relation in previous.relations
        }
        current_relations = {
            relation.relation_id: relation for relation in self.relations
        }
        if previous_relations.keys() - current_relations.keys():
            raise ValueError("a successor must not remove relations")
        for relation_id, old in previous_relations.items():
            if current_relations[relation_id] != old:
                raise ValueError("existing relations are immutable")
        return self

    def digest(self) -> str:
        """Return a stable digest for receipts and the next snapshot's parent."""

        payload = json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        return f"sha256:{hashlib.sha256(payload).hexdigest()}"


class GenerationContextReceipt(StrictModel):
    """Typed proof of the ledger projection used to generate one packet."""

    model_config = ConfigDict(frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    ledger_digest: str = Field(pattern=_SHA256_PATTERN)
    ledger_revision: int = Field(ge=0)
    through_batch: int = Field(ge=0)
    projection_policy_version: str = Field(min_length=1)
    prompt_projection_digest: str = Field(pattern=_SHA256_PATTERN)
    included_assertion_ids: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def validate_context_version(self) -> GenerationContextReceipt:
        if self.ledger_revision != self.through_batch:
            raise ValueError("ledger_revision must equal through_batch")
        if self.included_assertion_ids != tuple(
            sorted(set(self.included_assertion_ids))
        ):
            raise ValueError("included_assertion_ids must be sorted and unique")
        return self


class AlignmentReceipt(StrictModel):
    """Auditable cross-paper alignment attached outside the scientific packet."""

    model_config = ConfigDict(frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    alignment_id: str = Field(min_length=1)
    source: LedgerEntityRef
    target_assertion_id: str = Field(min_length=1)
    relation_type: AlignmentRelationType
    score_ppm: int = Field(ge=0, le=1_000_000)
    alignment_policy_version: str = Field(min_length=1)
    output_ledger_digest: str = Field(pattern=_SHA256_PATTERN)

    def stable_key(self) -> tuple[str, str, str, str]:
        return (
            self.source.entity_type,
            self.source.canonical_id,
            self.target_assertion_id,
            self.alignment_id,
        )


class PaperStudyDeliveryV2(StrictModel):
    """Delivery envelope coupling an immutable packet to external state receipts."""

    schema_version: Literal["2.0-delivery.1"] = "2.0-delivery.1"
    packet: PaperStudyPacketV2
    packet_digest: str = Field(pattern=_SHA256_PATTERN)
    generation_context: GenerationContextReceipt
    alignments: tuple[AlignmentReceipt, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def validate_receipts(self) -> PaperStudyDeliveryV2:
        expected_digest = _stable_model_digest(self.packet)
        if self.packet_digest != expected_digest:
            raise ValueError("packet_digest does not match packet content")
        alignment_ids = [alignment.alignment_id for alignment in self.alignments]
        if len(alignment_ids) != len(set(alignment_ids)):
            raise ValueError("alignment_id values must be unique")
        alignment_keys = tuple(item.stable_key() for item in self.alignments)
        if alignment_keys != tuple(sorted(set(alignment_keys))):
            raise ValueError("alignments must be stably sorted and unique")

        entity_ids: dict[LedgerEntityType, set[str]] = {
            "study_unit": set(),
            "result": set(),
            "claim": set(),
        }
        for question in self.packet.research_questions:
            for unit in question.study_units:
                entity_ids["study_unit"].add(unit.unit_id)
                entity_ids["result"].update(result.result_id for result in unit.results)
                entity_ids["claim"].update(claim.claim_id for claim in unit.claims)
        for alignment in self.alignments:
            if alignment.source.paper_id != self.packet.paper_id:
                raise ValueError("alignment source paper_id must match packet.paper_id")
            if alignment.source.packet_digest != self.packet_digest:
                raise ValueError("alignment source packet_digest must match delivery")
            if alignment.source.canonical_id not in entity_ids[
                alignment.source.entity_type
            ]:
                raise ValueError("alignment source must exist in the delivered packet")
            if alignment.source.entity_type != "claim":
                raise ValueError("delivery alignments currently support claims only")

        output_ledger_digests = {
            alignment.output_ledger_digest for alignment in self.alignments
        }
        if len(output_ledger_digests) > 1:
            raise ValueError("all alignments must use one output_ledger_digest")
        alignment_policy_versions = {
            alignment.alignment_policy_version for alignment in self.alignments
        }
        if len(alignment_policy_versions) > 1:
            raise ValueError("all alignments must use one alignment_policy_version")
        aligned_claim_ids = [
            alignment.source.canonical_id for alignment in self.alignments
        ]
        if Counter(aligned_claim_ids) != Counter(entity_ids["claim"]):
            raise ValueError("every packet claim requires exactly one alignment")
        return self

    def validate_against_ledgers(
        self,
        generation_ledger: GlobalStateLedger,
        output_ledger: GlobalStateLedger,
    ) -> PaperStudyDeliveryV2:
        """Verify both receipts against the immutable ledgers they identify."""

        generation_context = self.generation_context
        if generation_context.ledger_digest != generation_ledger.digest():
            raise ValueError(
                "generation_context ledger_digest does not match generation_ledger"
            )
        if generation_context.ledger_revision != generation_ledger.revision:
            raise ValueError(
                "generation_context ledger_revision does not match generation_ledger"
            )
        if generation_context.through_batch != generation_ledger.through_batch:
            raise ValueError(
                "generation_context through_batch does not match generation_ledger"
            )
        generation_assertion_ids = {
            assertion.assertion_id for assertion in generation_ledger.assertions
        }
        if (
            set(generation_context.included_assertion_ids)
            - generation_assertion_ids
        ):
            raise ValueError(
                "generation_context included_assertion_ids must exist in "
                "generation_ledger"
            )

        output_digest = output_ledger.digest()
        output_assertion_ids = {
            assertion.assertion_id for assertion in output_ledger.assertions
        }
        for alignment in self.alignments:
            if alignment.target_assertion_id not in output_assertion_ids:
                raise ValueError(
                    "alignment target_assertion_id must exist in output_ledger"
                )
            if alignment.output_ledger_digest != output_digest:
                raise ValueError(
                    "alignment output_ledger_digest does not match output_ledger"
                )
            if (
                alignment.alignment_policy_version
                != output_ledger.alignment_policy_version
            ):
                raise ValueError(
                    "alignment_policy_version does not match output_ledger"
                )
        return self


def packet_content_digest(packet: PaperStudyPacketV2) -> str:
    """Return the canonical packet digest used by delivery and ledger references."""

    return _stable_model_digest(packet)


def _stable_model_digest(value: BaseModel) -> str:
    payload = json.dumps(
        value.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"
