import json

from odracir.research_folder import ResearchFolderHarness
from odracir.retrieval import format_search_report, search_chunks


def _write_chunk_fixture(root) -> None:
    papers = root / "papers"
    papers.mkdir(parents=True)
    (papers / "medical-world-model.pdf").write_bytes(b"%PDF-1.4\n")
    harness = ResearchFolderHarness(root)
    harness.sync_index()
    index = harness.load_index()
    paper = index["papers"][0]
    paper["chunking_status"] = "chunked"
    paper["chunk_artifact"] = ".odracir/chunks/medical-world-model.json"
    harness.write_index(index)

    chunks_dir = root / ".odracir" / "chunks"
    chunks_dir.mkdir(parents=True)
    (chunks_dir / "medical-world-model.json").write_text(
        json.dumps(
            {
                "chunks": [
                    {
                        "id": "background",
                        "page_start": 1,
                        "page_end": 2,
                        "section_hint": "1 Introduction",
                        "text": "Medical world models support clinical representation learning.",
                    },
                    {
                        "id": "method",
                        "page_start": 4,
                        "page_end": 4,
                        "section_hint": "2 Method",
                        "text": (
                            "The medical world model learns a clinical world model. "
                            "The world model predicts longitudinal patient states."
                        ),
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_search_chunks_returns_ranked_citations(tmp_path) -> None:
    root = tmp_path / "field"
    _write_chunk_fixture(root)

    report = search_chunks(root, "world model", limit=2)

    assert report.searched_papers == 1
    assert report.searched_chunks == 2
    assert [hit.chunk_id for hit in report.hits] == ["method", "background"]
    assert report.hits[0].citation == "[medical-world-model pp.4 chunk:method]"
    assert "longitudinal patient states" in report.hits[0].snippet
    assert "Hits: 2" in format_search_report(report)


def test_search_chunks_returns_empty_hits_for_missing_term(tmp_path) -> None:
    root = tmp_path / "field"
    _write_chunk_fixture(root)

    report = search_chunks(root, "unfindable")

    assert report.hits == []
