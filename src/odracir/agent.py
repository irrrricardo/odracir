"""A small DeepSeek-backed agent loop with tool calling."""

from __future__ import annotations

import json
from typing import Any

from odracir.config import DeepSeekConfig, load_config
from odracir.providers import DeepSeekProvider
from odracir.tools import OPENAI_TOOLS, execute_tool


SYSTEM_PROMPT = """You are Odracir, a careful local-first research companion.

You help the user enter a research field, inspect papers, and turn evidence into
practical reading, experiment, and implementation plans. When a research folder
is available, use search_research_chunks before making paper-specific claims.
Use list_research_skills when a domain-specific reading workflow may help.
Use evaluate_research_summaries when the user asks about summary readiness or
quality.
Use get_research_memory when the user asks for a folder overview, its paper
catalog, or the current accumulated research memory.
Preserve paper, page, and chunk citations from tool results. Clearly distinguish
source-backed statements from inference, and say when local evidence is missing.
Keep final answers concise and actionable.
"""


class OdracirAgent:
    def __init__(
        self,
        config: DeepSeekConfig | None = None,
        *,
        provider: DeepSeekProvider | None = None,
    ) -> None:
        self.provider = provider or DeepSeekProvider(config or load_config())
        self.config = self.provider.config

    def run(self, user_message: str) -> str:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ]

        for _ in range(self.config.max_tool_turns):
            response = self.provider.chat_completion(
                messages=messages,
                tools=OPENAI_TOOLS,
                tool_choice="auto",
            )
            assistant_message = response.choices[0].message
            messages.append(assistant_message.model_dump(exclude_none=True))

            if not assistant_message.tool_calls:
                return assistant_message.content or ""

            for tool_call in assistant_message.tool_calls:
                arguments = self._parse_tool_arguments(tool_call.function.arguments)
                tool_result = execute_tool(tool_call.function.name, arguments)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(tool_result, ensure_ascii=False),
                    }
                )

        final_response = self.provider.chat_completion(
            messages=[
                *messages,
                {
                    "role": "system",
                    "content": "Use the available tool results and give the final answer now.",
                },
            ],
        )
        return final_response.choices[0].message.content or ""

    @staticmethod
    def _parse_tool_arguments(raw_arguments: str | None) -> dict[str, Any]:
        if not raw_arguments:
            return {}

        try:
            parsed = json.loads(raw_arguments)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Tool arguments were not valid JSON: {raw_arguments}") from exc

        if not isinstance(parsed, dict):
            raise ValueError("Tool arguments must decode to a JSON object.")

        return parsed
