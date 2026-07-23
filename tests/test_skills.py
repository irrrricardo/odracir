import pytest

from odracir.skills import (
    DEFAULT_RESEARCH_SKILL,
    ResearchSkillManifest,
    ResearchSkillRegistry,
    format_research_skill,
    get_builtin_skill_registry,
)


def test_builtin_skill_registry_exposes_generic_and_biomedical_manifests() -> None:
    registry = get_builtin_skill_registry()
    biomedical = registry.get("biomedical-paper")

    assert registry.names() == ["biomedical-paper", "generic"]
    assert DEFAULT_RESEARCH_SKILL.name == "generic"
    assert biomedical.domain_namespace == "biomedical"
    assert "population" in biomedical.schema_extension
    assert "citations" in biomedical.summary_prompt_guidance(include_schema=True)
    assert "Safety" in format_research_skill(biomedical)


def test_skill_registry_rejects_unknown_skill() -> None:
    with pytest.raises(ValueError, match="Available skills"):
        get_builtin_skill_registry().get("imaginary")


def test_skill_registry_rejects_duplicate_names() -> None:
    manifest = ResearchSkillManifest(
        name="duplicate",
        version="0.1",
        description="One.",
        instructions=(),
        tool_bindings=(),
        evaluation_rules=(),
    )

    with pytest.raises(ValueError, match="Duplicate research skill"):
        ResearchSkillRegistry((manifest, manifest))
