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


def test_list_research_skills_agent_tool() -> None:
    result = execute_tool("list_research_skills", {})

    assert [skill["name"] for skill in result["skills"]] == [
        "biomedical-paper",
        "generic",
    ]


def test_evaluate_research_summaries_agent_tool(tmp_path) -> None:
    root = tmp_path / "field"
    papers = root / "papers"
    papers.mkdir(parents=True)
    (papers / "paper.pdf").write_bytes(b"%PDF-1.4\n")
    from odracir.research_folder import ResearchFolderHarness

    ResearchFolderHarness(root).sync_index()

    result = execute_tool(
        "evaluate_research_summaries",
        {"folder": str(root), "skill": "biomedical-paper"},
    )

    assert result["status_counts"] == {"missing_summary": 1}
    assert result["artifact_path"] is None
    assert not (root / ".odracir" / "evaluations").exists()


def test_get_research_memory_agent_tool_is_read_only(tmp_path) -> None:
    root = tmp_path / "field"
    papers = root / "papers"
    papers.mkdir(parents=True)
    (papers / "paper.pdf").write_bytes(b"%PDF-1.4\n")
    from odracir.research_folder import ResearchFolderHarness

    ResearchFolderHarness(root).sync_index()

    result = execute_tool("get_research_memory", {"folder": str(root)})

    assert result["quality_counts"] == {"missing_summary": 1}
    assert result["catalog_path"] is None
    assert not (root / "research_catalog.json").exists()
