"""Tools that the Odracir agent can call."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


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
        "current_stage": "minimal single-agent prototype",
        "recommended_next_milestone": "replace example tools with one real business API",
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
]

TOOL_REGISTRY = {tool.name: tool for tool in TOOL_SPECS}
OPENAI_TOOLS = [tool.as_openai_tool() for tool in TOOL_SPECS]


def execute_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    tool = TOOL_REGISTRY.get(name)
    if tool is None:
        raise ValueError(f"Unknown tool: {name}")

    return tool.handler(**arguments)
