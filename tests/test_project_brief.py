from odracir.project_brief import ProjectBriefBuilder, render_project_brief
from odracir.research_memory import ResearchCatalogBuildResult


def test_render_project_brief_includes_human_readable_summary() -> None:
    catalog = ResearchCatalogBuildResult(
        root="C:/Research/field",
        index_path="C:/Research/field/odracir_index.json",
        catalog_path="C:/Research/field/research_catalog.json",
        cached=False,
        generated_at="2026-06-02T00:00:00+08:00",
        input_sha256="abc",
        total_papers=1,
        quality_counts={"passed": 1},
        records=[
            {
                "paper_id": "paper-a",
                "title": "Paper A",
                "source_file": "papers/paper-a.pdf",
                "memory_quality": {"status": "passed", "errors": []},
                "summary": {
                    "summary_short": "Short project-relevant summary.",
                    "summary_detailed": "Detailed project-relevant summary.",
                    "research_question": "What does this paper test?",
                    "methods": ["Method one", "Method two"],
                    "findings": [{"claim": "The method works on the fixture."}],
                    "limitations": ["Small fixture."],
                },
            }
        ],
    )

    markdown = render_project_brief(catalog)

    assert "# Research Brief: field" in markdown
    assert "### 1. Paper A" in markdown
    assert "Short project-relevant summary." in markdown
    assert "Research question: What does this paper test?" in markdown
    assert "- The method works on the fixture." in markdown


def test_project_brief_builder_writes_markdown_for_empty_catalog(tmp_path) -> None:
    result = ProjectBriefBuilder(tmp_path / "field").build()

    assert result.brief_path == str(tmp_path / "field" / "project_summary.md")
    assert result.total_papers == 0
    assert "# Research Brief: field" in result.markdown
    assert "No papers are currently recorded." in result.markdown
    assert (tmp_path / "field" / "project_summary.md").read_text(
        encoding="utf-8"
    ) == result.markdown
