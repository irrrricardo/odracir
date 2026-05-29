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
    assert data["schema_version"] == "0.1"
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
