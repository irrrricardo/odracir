from odracir.parser_routing import ParserRoutingAdvisor, format_parser_routing
from odracir.parsers import ParserRegistration, ParserRegistry
from odracir.pdf_artifacts import build_pdf_text_artifact
from odracir.research_folder import ResearchFolderHarness


def _index_pdfs(root, *names: str) -> bytes:
    papers = root / "papers"
    papers.mkdir(parents=True)
    for name in names:
        (papers / f"{name}.pdf").write_bytes(f"%PDF-1.4\n{name}".encode())
    ResearchFolderHarness(root).sync_index()
    return (root / "odracir_index.json").read_bytes()


def _registry(calls, *, candidate_fails: bool = False) -> ParserRegistry:
    registry = ParserRegistry()

    def baseline(path):
        calls.append(("pymupdf", path.stem))
        text = "" if path.stem == "scanned" else "b" * 10000
        return build_pdf_text_artifact(
            parser="pymupdf",
            parser_version="1",
            pages=[{"page_number": 1, "text": text}],
        )

    def candidate(path):
        calls.append(("pymupdf4llm", path.stem))
        if candidate_fails:
            raise RuntimeError("candidate unavailable")
        text = {
            "keep": "c" * 10500,
            "review": "c" * 14000,
            "scanned": "c" * 5000,
        }[path.stem]
        return build_pdf_text_artifact(
            parser="pymupdf4llm",
            parser_version="2",
            pages=[{"page_number": 1, "text": text}],
        )

    registry.register(ParserRegistration("pymupdf", ("pdf",), baseline))
    registry.register(ParserRegistration("pymupdf4llm", ("pdf",), candidate))
    return registry


def test_parser_routing_writes_cached_advisory_artifact_without_mutating_index(
    tmp_path,
) -> None:
    root = tmp_path / "field"
    index_before = _index_pdfs(root, "keep", "review")
    calls = []
    advisor = ParserRoutingAdvisor(root, parser_registry=_registry(calls))

    first = advisor.recommend()
    calls_after_first = list(calls)
    second = advisor.recommend()

    recommendations = {item.paper_id: item for item in first.recommendations}
    assert first.cached is False
    assert second.cached is True
    assert calls == calls_after_first
    assert first.action_counts == {"keep_baseline": 1, "review_candidate": 1}
    assert recommendations["keep"].action == "keep_baseline"
    assert recommendations["keep"].selected_parser == "pymupdf"
    assert recommendations["keep"].review_required is False
    assert recommendations["review"].action == "review_candidate"
    assert recommendations["review"].recommended_parser == "pymupdf4llm"
    assert recommendations["review"].selected_parser == "pymupdf"
    assert recommendations["review"].review_required is True
    assert (root / first.artifact_path).is_file()
    assert (root / "odracir_index.json").read_bytes() == index_before
    assert not (root / ".odracir" / "texts").exists()
    assert "advisory" in format_parser_routing(first)


def test_parser_routing_prefers_explicit_ocr_route_for_scanned_pdf(tmp_path) -> None:
    root = tmp_path / "field"
    _index_pdfs(root, "scanned")

    report = ParserRoutingAdvisor(
        root,
        parser_registry=_registry([]),
    ).recommend()

    recommendation = report.recommendations[0]
    assert recommendation.action == "run_ocr_preprocessing"
    assert recommendation.recommended_parser == "pymupdf"
    assert recommendation.review_required is True
    assert "OCRmyPDF" in recommendation.reasons[1]


def test_parser_routing_keeps_baseline_when_candidate_fails(tmp_path) -> None:
    root = tmp_path / "field"
    _index_pdfs(root, "keep")

    report = ParserRoutingAdvisor(
        root,
        parser_registry=_registry([], candidate_fails=True),
    ).recommend()

    recommendation = report.recommendations[0]
    assert recommendation.action == "keep_baseline"
    assert recommendation.recommended_parser == "pymupdf"
    assert "candidate unavailable" in recommendation.reasons[0]


def test_parser_routing_force_regenerates_cached_recommendations(tmp_path) -> None:
    root = tmp_path / "field"
    _index_pdfs(root, "review")
    calls = []
    advisor = ParserRoutingAdvisor(root, parser_registry=_registry(calls))

    advisor.recommend()
    advisor.recommend(force=True)

    assert calls == [
        ("pymupdf", "review"),
        ("pymupdf4llm", "review"),
        ("pymupdf", "review"),
        ("pymupdf4llm", "review"),
    ]
