from odracir.parser_benchmark import ParserBenchmarkHarness, format_parser_benchmark
from odracir.parsers import ParserRegistration, ParserRegistry
from odracir.pdf_artifacts import build_pdf_text_artifact
from odracir.research_folder import ResearchFolderHarness


def _registry() -> ParserRegistry:
    registry = ParserRegistry()
    registry.register(
        ParserRegistration(
            "baseline",
            ("pdf",),
            lambda path: build_pdf_text_artifact(
                parser="baseline",
                parser_version="1",
                pages=[{"page_number": 1, "text": "Baseline parser text."}],
            ),
        )
    )
    registry.register(
        ParserRegistration(
            "layout",
            ("pdf",),
            lambda path: build_pdf_text_artifact(
                parser="layout",
                parser_version="2",
                pages=[{"page_number": 1, "text": "Layout parser text with a table."}],
            ),
        )
    )
    return registry


def _index_one_pdf(root) -> bytes:
    papers = root / "papers"
    papers.mkdir(parents=True)
    (papers / "paper.pdf").write_bytes(b"%PDF-1.4\n")
    ResearchFolderHarness(root).sync_index()
    return (root / "odracir_index.json").read_bytes()


def test_parser_benchmark_is_read_only_and_compares_text_counts(tmp_path) -> None:
    root = tmp_path / "field"
    index_before = _index_one_pdf(root)

    report = ParserBenchmarkHarness(root, parser_registry=_registry()).run(
        parser_names=("baseline", "layout"),
    )

    assert report.papers == 1
    assert len(report.records) == 2
    assert report.summaries[0].parser == "baseline"
    assert report.summaries[0].text_char_delta_vs_baseline == 0
    assert report.summaries[1].parser == "layout"
    assert report.summaries[1].text_char_delta_vs_baseline > 0
    assert "Read-only" in format_parser_benchmark(report)
    assert (root / "odracir_index.json").read_bytes() == index_before
    assert not (root / ".odracir").exists()


def test_parser_benchmark_keeps_other_results_when_one_backend_fails(tmp_path) -> None:
    root = tmp_path / "field"
    _index_one_pdf(root)
    registry = _registry()
    registry.register(
        ParserRegistration(
            "broken",
            ("pdf",),
            lambda path: (_ for _ in ()).throw(RuntimeError("backend unavailable")),
        )
    )

    report = ParserBenchmarkHarness(root, parser_registry=registry).run(
        parser_names=("baseline", "broken"),
    )

    assert report.summaries[0].succeeded == 1
    assert report.summaries[1].failed == 1
    assert report.records[1].error == "backend unavailable"
