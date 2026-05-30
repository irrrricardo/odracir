import json

from odracir.research_folder import ResearchFolderHarness


def test_research_folder_sync_creates_index(tmp_path) -> None:
    root = tmp_path / "field"
    papers = root / "papers"
    papers.mkdir(parents=True)
    (papers / "paper-a.pdf").write_bytes(b"%PDF-1.4\n")
    (papers / "paper-b.txt").write_text("hello", encoding="utf-8")

    result = ResearchFolderHarness(root).sync_index()

    assert result.total_papers == 2
    assert result.new_papers == 2
    assert result.updated_papers == 0
    assert result.missing_papers == 0

    data = json.loads((root / "odracir_index.json").read_text(encoding="utf-8"))
    assert data["schema_version"] == "0.2"
    assert [paper["source_file"] for paper in data["papers"]] == [
        "papers/paper-a.pdf",
        "papers/paper-b.txt",
    ]


def test_research_folder_sync_preserves_existing_summary(tmp_path) -> None:
    root = tmp_path / "field"
    papers = root / "papers"
    papers.mkdir(parents=True)
    (papers / "paper-a.pdf").write_bytes(b"%PDF-1.4\n")

    harness = ResearchFolderHarness(root)
    harness.sync_index()

    index_path = root / "odracir_index.json"
    data = json.loads(index_path.read_text(encoding="utf-8"))
    data["papers"][0]["summary_short"] = "Important result."
    index_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    result = harness.sync_index()
    updated = json.loads(index_path.read_text(encoding="utf-8"))

    assert result.new_papers == 0
    assert updated["papers"][0]["summary_short"] == "Important result."


def test_research_folder_sync_supports_custom_papers_dir(tmp_path) -> None:
    root = tmp_path / "medical-world-model"
    storage = root / "Paper Storage"
    storage.mkdir(parents=True)
    (storage / "clinical-agent.pdf").write_bytes(b"%PDF-1.4\n")

    result = ResearchFolderHarness(root, papers_dir="Paper Storage").sync_index()
    data = json.loads((root / "odracir_index.json").read_text(encoding="utf-8"))

    assert result.total_papers == 1
    assert data["papers"][0]["source_file"] == "Paper Storage/clinical-agent.pdf"


def test_research_folder_sync_invalidates_generated_fields_when_source_changes(tmp_path) -> None:
    root = tmp_path / "field"
    papers = root / "papers"
    papers.mkdir(parents=True)
    pdf_path = papers / "paper-a.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\noriginal")

    harness = ResearchFolderHarness(root)
    harness.sync_index()
    index = harness.load_index()
    paper = index["papers"][0]
    paper.update(
        {
            "text_extraction_status": "extracted",
            "text_artifact": ".odracir/texts/paper-a.json",
            "text_extraction_sha256": paper["sha256"],
            "chunking_status": "chunked",
            "chunk_artifact": ".odracir/chunks/paper-a.json",
            "chunking_sha256": "old-text-artifact-hash",
            "summary_status": "completed",
            "translation_status": "completed",
        }
    )
    harness.write_index(index)

    pdf_path.write_bytes(b"%PDF-1.4\nchanged")
    harness.sync_index()
    updated = harness.load_index()["papers"][0]

    assert updated["text_extraction_status"] == "not_started"
    assert updated["chunking_status"] == "not_started"
    assert updated["summary_status"] == "not_started"
    assert updated["translation_status"] == "not_started"
    assert "text_artifact" not in updated
    assert "chunk_artifact" not in updated


def test_research_folder_sync_marks_removed_paper_as_missing(tmp_path) -> None:
    root = tmp_path / "field"
    papers = root / "papers"
    papers.mkdir(parents=True)
    pdf_path = papers / "paper-a.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")

    harness = ResearchFolderHarness(root)
    harness.sync_index()
    pdf_path.unlink()
    result = harness.sync_index()
    paper = harness.load_index()["papers"][0]

    assert result.missing_papers == 1
    assert paper["status"] == "missing"


def test_research_folder_sync_assigns_unique_ids_to_duplicate_stems(tmp_path) -> None:
    root = tmp_path / "field"
    papers = root / "papers"
    (papers / "one").mkdir(parents=True)
    (papers / "two").mkdir(parents=True)
    (papers / "one" / "paper.pdf").write_bytes(b"%PDF-1.4\none")
    (papers / "two" / "paper.pdf").write_bytes(b"%PDF-1.4\ntwo")

    ResearchFolderHarness(root).sync_index()
    paper_ids = [
        paper["id"]
        for paper in json.loads(
            (root / "odracir_index.json").read_text(encoding="utf-8")
        )["papers"]
    ]

    assert len(paper_ids) == 2
    assert len(set(paper_ids)) == 2
