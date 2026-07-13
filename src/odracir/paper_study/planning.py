"""Deterministic classification and extraction planning for paper-study v2."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, Sequence

from pydantic import Field, model_validator

from odracir.paper_study.domains import (
    DOMAIN_PROFILES,
    LOGIC_MODE_PROFILES,
    ExtractionTarget,
    PaperDomain,
    ScientificLogicMode,
    get_profile_for_domain,
)
from odracir.paper_study.models import StrictModel


class SourceChunk(StrictModel):
    """One traceable chunk from a legacy Odracir chunk artifact."""

    chunk_id: str = Field(validation_alias="id", min_length=1)
    ordinal: int = Field(ge=1)
    section_hint: str
    page_start: int = Field(ge=1)
    page_end: int = Field(ge=1)
    char_count: int = Field(ge=0)
    token_estimate: int = Field(ge=0)
    content_sha256: str = Field(min_length=1)
    text: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_source_chunk(self) -> SourceChunk:
        if self.page_end < self.page_start:
            raise ValueError("page_end must be greater than or equal to page_start")
        if self.char_count != len(self.text):
            raise ValueError("char_count must match the length of text")
        return self


class ChunkArtifact(StrictModel):
    """Validated input contract for existing Odracir v0.1 chunk JSON."""

    schema_version: str = Field(min_length=1)
    paper_id: str = Field(min_length=1)
    source_file: str = Field(min_length=1)
    source_sha256: str = Field(min_length=1)
    text_artifact: str = Field(min_length=1)
    text_artifact_sha256: str = Field(min_length=1)
    chunker: str = Field(min_length=1)
    chunker_version: str = Field(min_length=1)
    chunked_at: str = Field(min_length=1)
    chunk_count: int = Field(ge=1)
    chunks: list[SourceChunk] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_chunks(self) -> ChunkArtifact:
        if self.chunk_count != len(self.chunks):
            raise ValueError("chunk_count must match the number of chunks")
        chunk_ids = [chunk.chunk_id for chunk in self.chunks]
        if len(chunk_ids) != len(set(chunk_ids)):
            raise ValueError("chunk ids must be unique")
        ordinals = [chunk.ordinal for chunk in self.chunks]
        if len(ordinals) != len(set(ordinals)):
            raise ValueError("chunk ordinals must be unique")
        return self


class ClassificationDecision(StrictModel):
    """Auditable deterministic domain and scientific-logic classification."""

    domain: PaperDomain
    logic_mode: ScientificLogicMode
    domain_signal_matches: tuple[str, ...] = Field(default_factory=tuple)
    logic_mode_signal_matches: tuple[str, ...] = Field(default_factory=tuple)
    domain_scores: dict[str, int] = Field(default_factory=dict)
    logic_mode_scores: dict[str, int] = Field(default_factory=dict)
    rationale: str = Field(min_length=1)


class PaperExtractionPlan(StrictModel):
    """Serializable plan consumed by the model-backed extraction stage."""

    schema_version: Literal["1.0"] = "1.0"
    paper_id: str = Field(min_length=1)
    source_chunk_artifact: str = Field(min_length=1)
    classification: ClassificationDecision
    focus_prompt: str = Field(min_length=1)
    mandatory_fields: tuple[ExtractionTarget, ...] = Field(default_factory=tuple)
    selected_chunk_ids: tuple[str, ...] = Field(min_length=1)
    selected_chunk_ordinals: tuple[int, ...] = Field(min_length=1)

    @property
    def domain(self) -> PaperDomain:
        return self.classification.domain

    @property
    def logic_mode(self) -> ScientificLogicMode:
        return self.classification.logic_mode


def load_chunk_artifact(path: str | Path) -> ChunkArtifact:
    """Load and strictly validate an existing Odracir chunk artifact."""

    source_path = Path(path)
    return ChunkArtifact.model_validate_json(source_path.read_text(encoding="utf-8"))


def classify_paper(artifact: ChunkArtifact) -> ClassificationDecision:
    """Classify a paper from explicit profile signals across all source chunks."""

    text = _normalize_text("\n".join(chunk.text for chunk in artifact.chunks))
    domain_scores, domain_matches = _score_domain_profiles(text)
    logic_scores, logic_matches = _score_logic_profiles(text)

    specialist_domains = (
        PaperDomain.CLINICAL_TRIAL,
        PaperDomain.COMPUTATIONAL_BIO,
        PaperDomain.WET_LAB_MOLECULAR,
    )
    domain = max(
        specialist_domains,
        key=lambda candidate: (
            domain_scores[candidate.value],
            -specialist_domains.index(candidate),
        ),
    )
    specialist_score = domain_scores[domain.value]
    general_score = domain_scores[PaperDomain.GENERAL_METHOD.value]
    if specialist_score == 0 or general_score > 2 * specialist_score:
        domain = PaperDomain.GENERAL_METHOD

    logic_priority = (
        ScientificLogicMode.CAUSAL_VALIDATION,
        ScientificLogicMode.CONTRASTIVE,
        ScientificLogicMode.METHODOLOGICAL,
        ScientificLogicMode.PHENOMENOLOGICAL,
    )
    logic_mode = max(
        logic_priority,
        key=lambda candidate: (logic_scores[candidate.value], -logic_priority.index(candidate)),
    )
    if logic_scores[logic_mode.value] == 0:
        logic_mode = ScientificLogicMode.METHODOLOGICAL
    contrast_matches = set(logic_matches[ScientificLogicMode.CONTRASTIVE.value])
    causal_matches = set(logic_matches[ScientificLogicMode.CAUSAL_VALIDATION.value])
    explicit_alternative_mechanism = {
        "different mechanism",
        "opposite effect",
        "opposite conclusion",
        "distinct mechanism",
        "alternative mechanism",
        "does not rely on",
    }
    direct_intervention = {
        "knockout",
        "knockdown",
        "overexpression",
        "laser ablation",
        "reconstitution",
    }
    if contrast_matches & explicit_alternative_mechanism:
        logic_mode = ScientificLogicMode.CONTRASTIVE
    elif causal_matches & direct_intervention:
        logic_mode = ScientificLogicMode.CAUSAL_VALIDATION
    elif (
        domain is PaperDomain.GENERAL_METHOD
        and logic_scores[ScientificLogicMode.METHODOLOGICAL.value]
        >= logic_scores[logic_mode.value]
    ):
        logic_mode = ScientificLogicMode.METHODOLOGICAL

    matched_domain = domain_matches[domain.value]
    matched_logic = logic_matches[logic_mode.value]
    if domain is PaperDomain.GENERAL_METHOD:
        domain_reason = "the general-method signal threshold exceeded specialist evidence"
    else:
        domain_reason = (
            "specialist evidence remained at least half of the general-method fallback score"
        )
    if logic_mode is ScientificLogicMode.CONTRASTIVE and (
        contrast_matches & explicit_alternative_mechanism
    ):
        logic_reason = "explicit alternative-mechanism contrast signals were present"
    elif logic_mode is ScientificLogicMode.CAUSAL_VALIDATION and (
        causal_matches & direct_intervention
    ):
        logic_reason = "direct intervention signals were present"
    elif logic_mode is ScientificLogicMode.METHODOLOGICAL and (
        domain is PaperDomain.GENERAL_METHOD
    ):
        logic_reason = "methodological signals led within the general-method domain"
    else:
        logic_reason = "its profile had the strongest signal coverage"
    rationale = (
        f"Selected domain={domain.value} from {len(matched_domain)} matched signals because "
        f"{domain_reason}; selected logic_mode={logic_mode.value} from "
        f"{len(matched_logic)} matched signals because {logic_reason}."
    )
    return ClassificationDecision(
        domain=domain,
        logic_mode=logic_mode,
        domain_signal_matches=matched_domain,
        logic_mode_signal_matches=matched_logic,
        domain_scores=domain_scores,
        logic_mode_scores=logic_scores,
        rationale=rationale,
    )


def build_extraction_plan(
    artifact: ChunkArtifact,
    *,
    source_chunk_artifact: str | Path,
    max_chunks: int = 4,
    selected_ordinals: Sequence[int] | None = None,
) -> PaperExtractionPlan:
    """Build a focused extraction plan from a validated chunk artifact."""

    if max_chunks < 1:
        raise ValueError("max_chunks must be at least 1")
    classification = classify_paper(artifact)
    profile = get_profile_for_domain(
        classification.domain,
        classification.logic_mode,
    )
    selected = _select_chunks(
        artifact,
        classification=classification,
        max_chunks=max_chunks,
        selected_ordinals=selected_ordinals,
    )
    return PaperExtractionPlan(
        paper_id=artifact.paper_id,
        source_chunk_artifact=str(Path(source_chunk_artifact)),
        classification=classification,
        focus_prompt=profile.focus_prompt,
        mandatory_fields=profile.effective_mandatory_fields,
        selected_chunk_ids=tuple(chunk.chunk_id for chunk in selected),
        selected_chunk_ordinals=tuple(chunk.ordinal for chunk in selected),
    )


def selected_chunks_for_plan(
    artifact: ChunkArtifact,
    plan: PaperExtractionPlan,
) -> tuple[SourceChunk, ...]:
    """Resolve and verify the exact chunks selected by a plan."""

    if artifact.paper_id != plan.paper_id:
        raise ValueError("Plan paper_id does not match chunk artifact")
    by_id = {chunk.chunk_id: chunk for chunk in artifact.chunks}
    try:
        selected = tuple(by_id[chunk_id] for chunk_id in plan.selected_chunk_ids)
    except KeyError as exc:
        raise ValueError(f"Plan references unknown chunk id: {exc.args[0]}") from exc
    if tuple(chunk.ordinal for chunk in selected) != plan.selected_chunk_ordinals:
        raise ValueError("Plan chunk ids and ordinals do not agree")
    return selected


def write_extraction_plan(plan: PaperExtractionPlan, path: str | Path) -> Path:
    """Write a plan as stable, human-inspectable JSON."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp")
    temporary.write_text(
        json.dumps(plan.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)
    return target


def _score_domain_profiles(
    normalized_text: str,
) -> tuple[dict[str, int], dict[str, tuple[str, ...]]]:
    scores: dict[str, int] = {}
    matches: dict[str, tuple[str, ...]] = {}
    for domain, profile in DOMAIN_PROFILES.items():
        found = _matched_signals(normalized_text, profile.classification_signals)
        matches[domain.value] = found
        scores[domain.value] = len(found)
    return scores, matches


def _score_logic_profiles(
    normalized_text: str,
) -> tuple[dict[str, int], dict[str, tuple[str, ...]]]:
    scores: dict[str, int] = {}
    matches: dict[str, tuple[str, ...]] = {}
    for mode, profile in LOGIC_MODE_PROFILES.items():
        found = _matched_signals(normalized_text, profile.classification_signals)
        matches[mode.value] = found
        scores[mode.value] = len(found)
    return scores, matches


def _matched_signals(
    normalized_text: str,
    signals: Sequence[str],
) -> tuple[str, ...]:
    return tuple(
        signal for signal in signals if _normalize_text(signal) in normalized_text
    )


def _select_chunks(
    artifact: ChunkArtifact,
    *,
    classification: ClassificationDecision,
    max_chunks: int,
    selected_ordinals: Sequence[int] | None,
) -> tuple[SourceChunk, ...]:
    if selected_ordinals is not None:
        requested = tuple(dict.fromkeys(selected_ordinals))
        if not requested:
            raise ValueError("selected_ordinals must not be empty")
        by_ordinal = {chunk.ordinal: chunk for chunk in artifact.chunks}
        missing = [ordinal for ordinal in requested if ordinal not in by_ordinal]
        if missing:
            raise ValueError(f"Unknown chunk ordinals: {missing}")
        return tuple(by_ordinal[ordinal] for ordinal in requested)

    domain_signals = DOMAIN_PROFILES[
        classification.domain
    ].classification_signals
    logic_signals = LOGIC_MODE_PROFILES[
        classification.logic_mode
    ].classification_signals
    generic_signals = (
        "result",
        "experiment",
        "method",
        "limitation",
        "significant",
        "figure",
    )

    first = min(artifact.chunks, key=lambda chunk: chunk.ordinal)
    candidates = [chunk for chunk in artifact.chunks if chunk.chunk_id != first.chunk_id]
    ranked = sorted(
        candidates,
        key=lambda chunk: (
            _chunk_score(chunk, domain_signals, logic_signals, generic_signals),
            -chunk.ordinal,
        ),
        reverse=True,
    )
    selected = [first, *ranked[: max_chunks - 1]]
    return tuple(sorted(selected, key=lambda chunk: chunk.ordinal))


def _chunk_score(
    chunk: SourceChunk,
    domain_signals: Sequence[str],
    logic_signals: Sequence[str],
    generic_signals: Sequence[str],
) -> int:
    text = _normalize_text(chunk.text)
    if text.startswith("references "):
        return -1_000
    return (
        2 * sum(min(text.count(_normalize_text(signal)), 3) for signal in domain_signals)
        + 4 * sum(min(text.count(_normalize_text(signal)), 3) for signal in logic_signals)
        + sum(min(text.count(signal), 3) for signal in generic_signals)
    )


def _normalize_text(value: str) -> str:
    separators = str.maketrans({character: " " for character in "_-/;,|:()[]{}"})
    return " ".join(value.casefold().translate(separators).split())
