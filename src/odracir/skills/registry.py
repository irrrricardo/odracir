"""Versioned research-skill manifests for discipline-aware processing."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Iterable


DOMAIN_EVIDENCE_ITEM = {
    "value": "string",
    "citations": ["[paper pp.1 chunk:id]"],
    "inference": False,
}


@dataclass(frozen=True)
class ResearchSkillManifest:
    """A reusable domain contract layered above generic research tools."""

    name: str
    version: str
    description: str
    instructions: tuple[str, ...]
    tool_bindings: tuple[str, ...]
    evaluation_rules: tuple[str, ...]
    domain_namespace: str | None = None
    schema_extension: dict[str, str] | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def summary_prompt_guidance(self, *, include_schema: bool) -> str:
        lines = [
            f"Active research skill: {self.name}@{self.version}.",
            self.description,
            "Skill instructions:",
            *(f"- {instruction}" for instruction in self.instructions),
        ]
        if include_schema and self.domain_namespace and self.schema_extension:
            shape = {
                "domain_extensions": {
                    self.domain_namespace: {
                        field: [DOMAIN_EVIDENCE_ITEM]
                        for field in self.schema_extension
                    }
                }
            }
            lines.extend(
                [
                    "Also include the following domain extension shape:",
                    json.dumps(shape, ensure_ascii=False, indent=2),
                    (
                        "Every domain extension item must preserve supplied citations or "
                        "set inference=true. Use an empty list when evidence is absent."
                    ),
                ]
            )
        return "\n".join(lines)


class ResearchSkillRegistry:
    """Resolve named skill manifests while keeping the generic core independent."""

    def __init__(self, manifests: Iterable[ResearchSkillManifest]) -> None:
        self._skills: dict[str, ResearchSkillManifest] = {}
        for manifest in manifests:
            if manifest.name in self._skills:
                raise ValueError(f"Duplicate research skill: {manifest.name}")
            self._skills[manifest.name] = manifest

    def get(self, name: str) -> ResearchSkillManifest:
        normalized = name.strip()
        if not normalized:
            raise ValueError("Research skill name must not be empty.")
        try:
            return self._skills[normalized]
        except KeyError as exc:
            choices = ", ".join(self.names())
            raise ValueError(
                f"Unknown research skill: {normalized}. Available skills: {choices}."
            ) from exc

    def list(self) -> list[ResearchSkillManifest]:
        return [self._skills[name] for name in self.names()]

    def names(self) -> list[str]:
        return sorted(self._skills)


DEFAULT_RESEARCH_SKILL = ResearchSkillManifest(
    name="generic",
    version="0.1",
    description="Cross-disciplinary evidence-aware paper reading.",
    instructions=(
        "Preserve the paper's stated research question, methods, findings, and limitations.",
        "Do not invent discipline-specific fields when the evidence does not support them.",
        "Keep source-backed claims distinct from inference.",
    ),
    tool_bindings=("summarize", "search_research_chunks"),
    evaluation_rules=(
        "Every finding has source citations or inference=true.",
        "Limitations remain visible in the final summary.",
        "Missing evidence is not silently filled with assumptions.",
    ),
)

BIOMEDICAL_PAPER_SKILL = ResearchSkillManifest(
    name="biomedical-paper",
    version="0.1",
    description="Evidence-aware reading for biomedical and clinical research papers.",
    instructions=(
        "Extract study population and clinical context when present.",
        "Separate intervention or exposure, comparator, and outcomes when present.",
        "Capture biological mechanisms, assays, and measurements without overstating causality.",
        "Record clinical relevance, safety, ethics, and uncertainty when supported.",
        "Use empty lists for unsupported biomedical fields instead of guessing.",
    ),
    tool_bindings=("summarize", "search_research_chunks", "translate"),
    evaluation_rules=(
        "Every biomedical field item has source citations or inference=true.",
        "Population, intervention or exposure, comparator, and outcomes remain distinct.",
        "Mechanistic claims do not imply clinical efficacy without supporting evidence.",
        "Safety, ethics, and missing evidence remain visible.",
    ),
    domain_namespace="biomedical",
    schema_extension={
        "population": "Study population, cohort, organism, or specimen context.",
        "intervention_or_exposure": "Treatment, procedure, exposure, or modeled action.",
        "comparator": "Control, baseline, reference group, or alternative treatment.",
        "outcomes": "Clinical, biological, or predictive outcomes.",
        "biological_mechanisms": "Mechanisms or mechanistic hypotheses.",
        "assays_or_measurements": "Assays, measurements, biomarkers, and endpoints.",
        "clinical_relevance": "Potential clinical relevance and deployment context.",
        "safety_or_ethics": "Safety, ethical, privacy, and bias considerations.",
    },
)


def get_builtin_skill_registry() -> ResearchSkillRegistry:
    return ResearchSkillRegistry((DEFAULT_RESEARCH_SKILL, BIOMEDICAL_PAPER_SKILL))


def format_research_skills(registry: ResearchSkillRegistry) -> str:
    lines = ["Available research skills:"]
    for manifest in registry.list():
        namespace = manifest.domain_namespace or "none"
        lines.append(
            f"- {manifest.name}@{manifest.version}: {manifest.description} "
            f"(domain_namespace={namespace})"
        )
    return "\n".join(lines)


def format_research_skill(manifest: ResearchSkillManifest) -> str:
    lines = [
        f"Research skill: {manifest.name}@{manifest.version}",
        f"Description: {manifest.description}",
        f"Domain namespace: {manifest.domain_namespace or 'none'}",
        f"Tool bindings: {', '.join(manifest.tool_bindings) or 'none'}",
        "Instructions:",
        *(f"- {item}" for item in manifest.instructions),
        "Evaluation rules:",
        *(f"- {item}" for item in manifest.evaluation_rules),
    ]
    if manifest.schema_extension:
        lines.append("Schema extension:")
        lines.extend(
            f"- {field}: {description}"
            for field, description in manifest.schema_extension.items()
        )
    return "\n".join(lines)
