"""Tools that the Odracir agent can call."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from odracir.reading_queue import ReadingQueueBuilder
from odracir.research_memory import ResearchCatalogBuilder
from odracir.retrieval import search_chunks
from odracir.skills import get_builtin_skill_registry
from odracir.summary_evaluation import SummaryEvaluationHarness


ToolHandler = Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler

    def as_openai_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def get_project_context() -> dict[str, Any]:
    return {
        "project_name": "odracir",
        "provider": "DeepSeek API",
        "current_stage": (
            "local-first research prototype with traceable extraction, retrieval, "
            "summaries, translations, evidence-backed questions, and versioned "
            "research skills"
        ),
        "recommended_next_milestone": (
            "run one supervised biomedical summary and audit its evidence quality"
        ),
    }


def draft_agent_steps(goal: str) -> dict[str, Any]:
    return {
        "goal": goal,
        "steps": [
            "Define the agent's responsibility and refusal boundaries.",
            "Add one real tool with a narrow schema.",
            "Run the agent against 10 representative user requests.",
            "Log tool calls, errors, latency, and final answers.",
            "Only then split responsibilities into multiple agents if needed.",
        ],
    }


def search_research_chunks(folder: str, query: str, limit: int = 5) -> dict[str, Any]:
    """Search local paper chunks and return inspectable evidence references."""
    return search_chunks(folder, query, limit=limit).as_dict()


def list_research_skills() -> dict[str, Any]:
    """Return inspectable built-in research-skill manifests."""
    registry = get_builtin_skill_registry()
    return {"skills": [manifest.as_dict() for manifest in registry.list()]}


def evaluate_research_summaries(
    folder: str,
    skill: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Audit local summary artifacts without writing files or calling an LLM."""
    registry = get_builtin_skill_registry()
    expected_skill = registry.get(skill) if skill else None
    return SummaryEvaluationHarness(
        folder,
        skill_registry=registry,
    ).evaluate(
        limit=limit,
        expected_skill=expected_skill,
        write_artifact=False,
    ).as_dict()


def get_research_memory(folder: str) -> dict[str, Any]:
    """Build an ephemeral audited folder catalog without writing files or calling an LLM."""
    return ResearchCatalogBuilder(folder).build(write_artifact=False).as_dict()


def plan_research_reading(
    folder: str,
    query: str | None = None,
    skill: str = "generic",
    limit: int = 5,
) -> dict[str, Any]:
    """Build an ephemeral reading queue without writing files or calling an LLM."""
    return ReadingQueueBuilder(folder).build(
        query=query,
        skill_name=skill,
        limit=limit,
        write_artifact=False,
    ).as_dict()


TOOL_SPECS = [
    ToolSpec(
        name="get_project_context",
        description="Get basic context about the current Odracir agent project.",
        parameters={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        handler=get_project_context,
    ),
    ToolSpec(
        name="draft_agent_steps",
        description="Draft a practical implementation sequence for a requested agent goal.",
        parameters={
            "type": "object",
            "properties": {
                "goal": {
                    "type": "string",
                    "description": "The agent or workflow goal to plan for.",
                }
            },
            "required": ["goal"],
            "additionalProperties": False,
        },
        handler=draft_agent_steps,
    ),
    ToolSpec(
        name="list_research_skills",
        description=(
            "List built-in research-skill manifests with domain schemas and evaluation rules."
        ),
        parameters={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        handler=list_research_skills,
    ),
    ToolSpec(
        name="evaluate_research_summaries",
        description=(
            "Audit local paper-summary artifacts for missing summaries, stale evidence, "
            "citation errors, and review warnings without calling an LLM."
        ),
        parameters={
            "type": "object",
            "properties": {
                "folder": {
                    "type": "string",
                    "description": "Absolute or relative research-folder path.",
                },
                "skill": {
                    "type": "string",
                    "description": "Optional required research-skill manifest name.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Optional maximum number of PDFs to audit.",
                    "minimum": 1,
                },
            },
            "required": ["folder"],
            "additionalProperties": False,
        },
        handler=evaluate_research_summaries,
    ),
    ToolSpec(
        name="get_research_memory",
        description=(
            "Read the folder-level research catalog assembled from audited local artifacts. "
            "Missing or invalid summaries remain explicit and are not treated as knowledge."
        ),
        parameters={
            "type": "object",
            "properties": {
                "folder": {
                    "type": "string",
                    "description": "Absolute or relative research-folder path.",
                },
            },
            "required": ["folder"],
            "additionalProperties": False,
        },
        handler=get_research_memory,
    ),
    ToolSpec(
        name="plan_research_reading",
        description=(
            "Build a read-only, explainable local reading-priority queue for a research "
            "folder. It can prioritize papers for a focus query and proposes supervised "
            "next commands without calling an LLM."
        ),
        parameters={
            "type": "object",
            "properties": {
                "folder": {
                    "type": "string",
                    "description": "Absolute or relative research-folder path.",
                },
                "query": {
                    "type": "string",
                    "description": "Optional research focus used for local prioritization.",
                },
                "skill": {
                    "type": "string",
                    "description": "Research skill for supervised summary commands.",
                    "default": "generic",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum reading-queue entries.",
                    "minimum": 1,
                    "default": 5,
                },
            },
            "required": ["folder"],
            "additionalProperties": False,
        },
        handler=plan_research_reading,
    ),
    ToolSpec(
        name="search_research_chunks",
        description=(
            "Search local research-paper chunks and return ranked excerpts with paper, "
            "page, and chunk citations."
        ),
        parameters={
            "type": "object",
            "properties": {
                "folder": {
                    "type": "string",
                    "description": "Absolute or relative research-folder path.",
                },
                "query": {
                    "type": "string",
                    "description": "Terms or phrase to find in extracted paper chunks.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of ranked hits to return.",
                    "minimum": 1,
                    "default": 5,
                },
            },
            "required": ["folder", "query"],
            "additionalProperties": False,
        },
        handler=search_research_chunks,
    ),
]

TOOL_REGISTRY = {tool.name: tool for tool in TOOL_SPECS}
OPENAI_TOOLS = [tool.as_openai_tool() for tool in TOOL_SPECS]


def execute_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    tool = TOOL_REGISTRY.get(name)
    if tool is None:
        raise ValueError(f"Unknown tool: {name}")

    return tool.handler(**arguments)
