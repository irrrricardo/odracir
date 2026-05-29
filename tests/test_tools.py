from odracir.tools import execute_tool


def test_get_project_context() -> None:
    result = execute_tool("get_project_context", {})

    assert result["project_name"] == "odracir"
    assert result["provider"] == "DeepSeek API"


def test_draft_agent_steps() -> None:
    result = execute_tool("draft_agent_steps", {"goal": "build a customer support agent"})

    assert result["goal"] == "build a customer support agent"
    assert len(result["steps"]) >= 3
