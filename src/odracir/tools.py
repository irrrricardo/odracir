"""Tools that the Odracir agent can call."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from odracir.retrieval import search_chunks


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
            "summaries, translations, and evidence-backed questions"
        ),
        "recommended_next_milestone": (
            "review parser recommendations and add discipline-specific skill manifests"
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
