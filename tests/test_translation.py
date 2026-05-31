import json

from odracir.processing_state import invalidate_chunking, invalidate_summary
from odracir.providers import JsonCompletionResult
from odracir.research_folder import ResearchFolderHarness
from odracir.translation import SelectiveTranslator, _select_chunks, build_translation_plan


class StubProvider:
    provider_name = "stub"
    model = "stub-model"

    def __init__(
        self,
        *,
        preserve_citation: bool = True,
        terminology=None,
    ) -> None:
        self.calls = []
        self.preserve_citation = preserve_citation
        self.terminology = terminology

    def complete_json(self, *, system_prompt: str, user_prompt: str, max_tokens: int):
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "max_tokens": max_tokens,
            }
        )
        citation = user_prompt.split("Citation: ", 1)[1].splitlines()[0]
        if not self.preserve_citation:
            citation = "[paper pp.99 chunk:invented]"
        return JsonCompletionResult(
            payload={
                "citation": citation,
                "translated_text": "忠实译文。",
                "terminology": self.terminology
                if self.terminology is not None
                else [{"source": "world model", "target": "世界模型", "note": ""}],
                "translator_notes": [],
            },
            usage={"total_tokens": 10},
        )


def _write_translation_fixture(root) -> None:
    papers = root / "papers"
    papers.mkdir(parents=True)
    (papers / "paper.pdf").write_bytes(b"%PDF-1.4\n")
    harness = ResearchFolderHarness(root)
    harness.sync_index()
    index = harness.load_index()
    paper = index["papers"][0]
    paper["chunking_status"] = "chunked"
    paper["chunk_artifact"] = ".odracir/chunks/paper.json"
    harness.write_index(index)

    chunks_dir = root / ".odracir" / "chunks"
    chunks_dir.mkdir(parents=True)
    chunks = [
        {
            "id": "abstract",
            "page_start": 1,
            "page_end": 1,
            "section_hint": "",
            "content_sha256": "a" * 64,
            "text": "Abstract\nA world model supports clinical reasoning.",
        },
        {
            "id": "methods",
            "page_start": 2,
            "page_end": 3,
            "section_hint": "2 Methods",
            "content_sha256": "b" * 64,
            "text": "2 Methods\nThe model predicts longitudinal state transitions.",
        },
        {
            "id": "results",
            "page_start": 4,
            "page_end": 4,
            "section_hint": "3 Results",
            "content_sha256": "c" * 64,
            "text": "3 Results\nThe benchmark improves.",
        },
        {
            "id": "conclusion",
            "page_start": 5,
            "page_end": 5,
            "section_hint": "5 Conclusion",
            "content_sha256": "d" * 64,
            "text": "5 Conclusion\nThe approach has limitations.",
        },
    ]
    (chunks_dir / "paper.json").write_text(
        json.dumps({"chunks": chunks}),
        encoding="utf-8",
    )


def test_selective_translation_writes_artifact_and_skips_unchanged_selection(tmp_path) -> None:
    root = tmp_path / "field"
    _write_translation_fixture(root)
    provider = StubProvider()
    translator = SelectiveTranslator(root, provider)

    first = translator.translate_index()
    index = translator.harness.load_index()
    paper = index["papers"][0]
    artifact = json.loads(
        (root / paper["translation_artifact"]).read_text(encoding="utf-8")
    )
    second = translator.translate_index()

    assert first.translated == 1
    assert second.skipped == 1
    assert len(provider.calls) == 3
    assert paper["translation_status"] == "translated"
    assert paper["translated_chunk_count"] == 3
    assert artifact["selection"]["selected_chunk_ids"] == [
        "abstract",
        "methods",
        "conclusion",
    ]
    assert artifact["target_language"] == "zh-CN"
    assert artifact["usage"]["total_tokens"] == 30
    assert artifact["translations"][0]["citation"] == "[paper pp.1 chunk:abstract]"


def test_translation_can_target_explicit_chunk_without_default_sections(tmp_path) -> None:
    root = tmp_path / "field"
    _write_translation_fixture(root)
    provider = StubProvider()

    result = SelectiveTranslator(root, provider).translate_index(
        sections=(),
        chunk_ids=("results",),
    )
    paper = ResearchFolderHarness(root).load_index()["papers"][0]
    artifact = json.loads(
        (root / paper["translation_artifact"]).read_text(encoding="utf-8")
    )

    assert result.translated == 1
    assert len(provider.calls) == 1
    assert artifact["selection"]["selected_chunk_ids"] == ["results"]


def test_translation_dry_run_previews_selection_without_provider(tmp_path) -> None:
    root = tmp_path / "field"
    _write_translation_fixture(root)

    plan = build_translation_plan(root)

    assert plan.ready == 1
    assert plan.total_selected_chunks == 3
    assert [chunk["chunk_id"] for chunk in plan.papers[0].selected_chunks] == [
        "abstract",
        "methods",
        "conclusion",
    ]


def test_section_selection_rejects_table_column_but_keeps_numbered_heading() -> None:
    chunks = [
        {"id": "abstract", "text": "Abstract\nOverview.", "section_hint": ""},
        {
            "id": "table",
            "text": "Table 1. Results\nModel\nMethods\nScore",
            "section_hint": "",
        },
        {
            "id": "conclusion",
            "text": "Prior paragraph.\n5. Conclusion\nFinal result.",
            "section_hint": "",
        },
    ]

    selected = _select_chunks(
        chunks,
        sections=("abstract", "methods", "conclusion"),
        chunk_ids=(),
        all_chunks=False,
        max_selected_chunks=8,
    )

    assert [chunk["id"] for chunk in selected] == ["abstract", "conclusion"]


def test_translation_all_chunks_is_explicit_and_ignores_selective_cap(tmp_path) -> None:
    root = tmp_path / "field"
    _write_translation_fixture(root)
    provider = StubProvider()

    result = SelectiveTranslator(root, provider).translate_index(
        all_chunks=True,
        max_selected_chunks=1,
    )

    assert result.translated == 1
    assert len(provider.calls) == 4


def test_translation_rejects_changed_citation(tmp_path) -> None:
    root = tmp_path / "field"
    _write_translation_fixture(root)

    result = SelectiveTranslator(
        root,
        StubProvider(preserve_citation=False),
    ).translate_index()
    paper = ResearchFolderHarness(root).load_index()["papers"][0]

    assert result.failed == 1
    assert paper["translation_status"] == "failed"
    assert "preserve the supplied citation" in paper["translation_error"]
    assert "translation_artifact" not in paper


def test_translation_rejects_malformed_terminology(tmp_path) -> None:
    root = tmp_path / "field"
    _write_translation_fixture(root)

    result = SelectiveTranslator(
        root,
        StubProvider(terminology=["not an object"]),
    ).translate_index()
    paper = ResearchFolderHarness(root).load_index()["papers"][0]

    assert result.failed == 1
    assert paper["translation_status"] == "failed"
    assert "terminology item must be an object" in paper["translation_error"]


def test_translation_blocks_unchunked_paper(tmp_path) -> None:
    root = tmp_path / "field"
    papers = root / "papers"
    papers.mkdir(parents=True)
    (papers / "paper.pdf").write_bytes(b"%PDF-1.4\n")

    result = SelectiveTranslator(root, StubProvider()).translate_index()
    paper = ResearchFolderHarness(root).load_index()["papers"][0]

    assert result.blocked == 1
    assert paper["translation_status"] == "blocked"


def test_summary_and_translation_invalidation_are_independent(tmp_path) -> None:
    paper = {
        "summary_status": "summarized",
        "summary_artifact": ".odracir/summaries/paper.json",
        "translation_status": "translated",
        "translation_artifact": ".odracir/translations/paper.zh-CN.json",
    }

    invalidate_summary(paper)

    assert paper["summary_status"] == "not_started"
    assert paper["translation_status"] == "translated"
    assert paper["translation_artifact"] == ".odracir/translations/paper.zh-CN.json"

    invalidate_chunking(paper)

    assert paper["translation_status"] == "not_started"
    assert "translation_artifact" not in paper
