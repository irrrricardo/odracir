import json
import re

from odracir.library_ingestion import PaperLibraryIngestionHarness
from odracir.parsers import ParserRegistration, ParserRegistry
from odracir.pdf_artifacts import build_pdf_text_artifact
from odracir.providers import JsonCompletionResult


class LibraryStubProvider:
    provider_name = "stub"
    model = "library-model"

    def __init__(self) -> None:
        self.calls = []

    def complete_json(self, *, system_prompt: str, user_prompt: str, max_tokens: int):
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "max_tokens": max_tokens,
            }
        )
        match = re.search(r'"citation": "([^"]+)"', user_prompt)
        assert match is not None
        citation = match.group(1)
        return JsonCompletionResult(
            payload={
                "summary_short": "Short library memory.",
                "summary_detailed": "Detailed library memory.",
                "research_question": "Can local evidence support a research workflow?",
                "methods": ["Structured paper reading."],
                "findings": [
                    {
                        "claim": "The paper contains traceable evidence.",
                        "citations": [citation],
                        "inference": False,
                    }
                ],
                "limitations": ["Fixture evidence is intentionally small."],
                "key_terms": ["evidence"],
                "implementation_notes": [],
                "inferences": [],
            },
            usage={"total_tokens": 25},
        )


def _parser_registry() -> ParserRegistry:
    def parse(source_path):
        return build_pdf_text_artifact(
            parser="fixture",
            parser_version="test",
            pages=[
                {
                    "page_number": 1,
                    "text": (
                        f"Traceable local evidence from {source_path.stem}. "
                        "This text is long enough for deterministic paper ingestion."
                    ),
                }
            ],
        )

    registry = ParserRegistry()
    registry.register(ParserRegistration("fixture", ("pdf",), parse))
    return registry


def _write_pdf(path) -> None:
    path.write_bytes(b"%PDF-1.4\n")


def test_ingest_library_prepares_reads_audits_and_updates_root_state(tmp_path) -> None:
    root = tmp_path / "field"
    papers = root / "papers"
    papers.mkdir(parents=True)
    _write_pdf(papers / "paper.pdf")
    provider = LibraryStubProvider()

    result = PaperLibraryIngestionHarness(
        root,
        provider,
        parser_name="fixture",
        parser_registry=_parser_registry(),
    ).ingest()
    catalog = json.loads((root / "research_catalog.json").read_text(encoding="utf-8"))
    record = catalog["records"][0]

    assert result.preparation.extraction.extracted == 1
    assert result.preparation.chunking.chunked == 1
    assert result.summaries is not None
    assert result.summaries.summarized == 1
    assert result.summaries.strategy_counts == {"single_pass": 1}
    assert result.evaluation.status_counts == {"passed": 1}
    assert result.memory.quality_counts == {"passed": 1}
    assert len(provider.calls) == 1
    assert record["summary"]["summary_short"] == "Short library memory."
    assert record["summary_provenance"]["summary_strategy"] == "single_pass"
    assert record["summary_provenance"]["request_count"] == 1


def test_ingest_library_reuses_current_summary_state(tmp_path) -> None:
    root = tmp_path / "field"
    papers = root / "papers"
    papers.mkdir(parents=True)
    _write_pdf(papers / "paper.pdf")
    provider = LibraryStubProvider()
    harness = PaperLibraryIngestionHarness(
        root,
        provider,
        parser_name="fixture",
        parser_registry=_parser_registry(),
    )

    harness.ingest()
    second = harness.ingest()

    assert second.summaries is not None
    assert second.summaries.summarized == 0
    assert second.summaries.skipped == 1
    assert len(provider.calls) == 1


def test_ingest_library_dry_run_prepares_without_provider_or_api_call(tmp_path) -> None:
    root = tmp_path / "field"
    papers = root / "papers"
    papers.mkdir(parents=True)
    _write_pdf(papers / "paper.pdf")

    result = PaperLibraryIngestionHarness(
        root,
        parser_name="fixture",
        parser_registry=_parser_registry(),
    ).ingest(dry_run=True)

    assert result.summaries is None
    assert result.summary_plan.ready == 1
    assert result.evaluation.status_counts == {"missing_summary": 1}
    assert result.memory.quality_counts == {"missing_summary": 1}


def test_ingest_library_rejects_missing_provider_for_paid_run(tmp_path) -> None:
    try:
        PaperLibraryIngestionHarness(tmp_path / "field").ingest()
    except ValueError as exc:
        assert "requires a provider" in str(exc)
    else:
        raise AssertionError("Expected a paid ingestion run without a provider to fail.")