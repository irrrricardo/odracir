import pytest

from odracir.parsers import ParserRegistration, ParserRegistry
from odracir.pdf_artifacts import build_pdf_text_artifact
from odracir.preparation import LocalPreparationHarness
from odracir.retrieval import search_chunks


def _parser_registry(*, empty: bool = False, fail_name: str | None = None) -> ParserRegistry:
    def parse(source_path):
        if source_path.name == fail_name:
            raise ValueError("fixture parser rejected PDF")
        text = (
            ""
            if empty
            else (
                f"Searchable local evidence from {source_path.stem}. "
                "This fixture includes enough text for deterministic chunk preparation."
            )
        )
        return build_pdf_text_artifact(
            parser="fixture",
            parser_version="test",
            pages=[{"page_number": 1, "text": text}],
        )

    registry = ParserRegistry()
    registry.register(ParserRegistration("fixture", ("pdf",), parse))
    return registry


def _write_pdf(path) -> None:
    path.write_bytes(b"%PDF-1.4\n")


def test_prepare_builds_searchable_local_artifacts_and_catalog(tmp_path) -> None:
    root = tmp_path / "field"
    papers = root / "papers"
    papers.mkdir(parents=True)
    _write_pdf(papers / "paper.pdf")

    result = LocalPreparationHarness(
        root,
        parser_name="fixture",
        parser_registry=_parser_registry(),
    ).prepare()
    search = search_chunks(root, "Searchable")

    assert result.scan.new_papers == 1
    assert result.extraction.extracted == 1
    assert result.chunking.chunked == 1
    assert result.memory.quality_counts == {"missing_summary": 1}
    assert result.status.extraction_statuses == {"extracted": 1}
    assert result.status.chunking_statuses == {"chunked": 1}
    assert result.status.failures == []
    assert (root / "research_catalog.json").is_file()
    assert search.hits[0].citation.startswith("[paper pp.1 chunk:")


def test_prepare_reuses_current_extraction_and_chunks(tmp_path) -> None:
    root = tmp_path / "field"
    papers = root / "papers"
    papers.mkdir(parents=True)
    _write_pdf(papers / "paper.pdf")
    harness = LocalPreparationHarness(
        root,
        parser_name="fixture",
        parser_registry=_parser_registry(),
    )

    harness.prepare()
    second = harness.prepare()

    assert second.extraction.extracted == 0
    assert second.extraction.skipped == 1
    assert second.chunking.chunked == 0
    assert second.chunking.skipped == 1
    assert second.memory.cached is True


def test_prepare_supports_custom_papers_directory(tmp_path) -> None:
    root = tmp_path / "field"
    papers = root / "Paper Storage"
    papers.mkdir(parents=True)
    _write_pdf(papers / "paper.pdf")

    result = LocalPreparationHarness(
        root,
        papers_dir="Paper Storage",
        parser_name="fixture",
        parser_registry=_parser_registry(),
    ).prepare()

    assert result.scan.total_papers == 1
    assert result.extraction.extracted == 1
    assert result.chunking.chunked == 1


def test_prepare_routes_empty_pdf_text_to_explicit_ocr_queue(tmp_path) -> None:
    root = tmp_path / "field"
    papers = root / "papers"
    papers.mkdir(parents=True)
    _write_pdf(papers / "scanned.pdf")

    result = LocalPreparationHarness(
        root,
        parser_name="fixture",
        parser_registry=_parser_registry(empty=True),
    ).prepare()

    assert result.extraction.extracted == 1
    assert result.chunking.blocked == 1
    assert result.status.extraction_statuses == {"needs_ocr": 1}
    assert result.status.needs_ocr[0]["id"] == "scanned"


def test_prepare_isolates_invalid_pdf_and_keeps_batch_progress(tmp_path) -> None:
    root = tmp_path / "field"
    papers = root / "papers"
    papers.mkdir(parents=True)
    _write_pdf(papers / "good.pdf")
    _write_pdf(papers / "invalid.pdf")

    result = LocalPreparationHarness(
        root,
        parser_name="fixture",
        parser_registry=_parser_registry(fail_name="invalid.pdf"),
    ).prepare()

    assert result.extraction.extracted == 1
    assert result.extraction.failed == 1
    assert result.chunking.chunked == 1
    assert result.chunking.blocked == 1
    assert result.status.failures[0]["id"] == "invalid"
    assert result.status.failures[0]["stage"] == "extract"


def test_prepare_rejects_non_positive_limit(tmp_path) -> None:
    with pytest.raises(ValueError, match="at least 1"):
        LocalPreparationHarness(tmp_path / "field").prepare(limit=0)
