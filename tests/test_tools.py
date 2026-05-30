from odracir.tools import execute_tool


def test_get_project_context() -> None:
    result = execute_tool("get_project_context", {})

    assert result["project_name"] == "odracir"
    assert result["provider"] == "DeepSeek API"


def test_draft_agent_steps() -> None:
    result = execute_tool("draft_agent_steps", {"goal": "build a customer support agent"})

    assert result["goal"] == "build a customer support agent"
    assert len(result["steps"]) >= 3


def test_search_research_chunks_agent_tool(tmp_path) -> None:
    root = tmp_path / "field"
    papers = root / "papers"
    papers.mkdir(parents=True)
    (papers / "paper.pdf").write_bytes(b"%PDF-1.4\n")

    from odracir.research_folder import ResearchFolderHarness

    harness = ResearchFolderHarness(root)
    harness.sync_index()
    index = harness.load_index()
    paper = index["papers"][0]
    paper["chunking_status"] = "chunked"
    paper["chunk_artifact"] = ".odracir/chunks/paper.json"
    harness.write_index(index)
    chunks_dir = root / ".odracir" / "chunks"
    chunks_dir.mkdir(parents=True)
    (chunks_dir / "paper.json").write_text(
        '{"chunks": [{"id": "one", "page_start": 1, "page_end": 1, '
        '"text": "retrieval evidence"}]}',
        encoding="utf-8",
    )

    result = execute_tool(
        "search_research_chunks",
        {"folder": str(root), "query": "retrieval", "limit": 1},
    )

    assert result["hits"][0]["citation"] == "[paper pp.1 chunk:one]"
