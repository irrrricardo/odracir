"""Command-line entry point for Odracir."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys

from odracir.agent import OdracirAgent
from odracir.capabilities import build_capability_report, format_capability_report
from odracir.chunking import TextChunker
from odracir.config import load_config
from odracir.docs_sync import sync_project_docs
from odracir.ocr import OcrmyPdfPreprocessor
from odracir.parser_benchmark import ParserBenchmarkHarness, format_parser_benchmark
from odracir.parser_routing import ParserRoutingAdvisor, format_parser_routing
from odracir.pdf_extraction import PdfTextExtractor
from odracir.preparation import LocalPreparationHarness, format_local_preparation
from odracir.providers import DeepSeekProvider
from odracir.question_answering import (
    EvidenceQuestionAnswerer,
    build_ask_plan,
    format_answer_result,
    format_ask_plan,
)
from odracir.reading_queue import ReadingQueueBuilder, format_reading_queue
from odracir.research_memory import ResearchCatalogBuilder, format_research_catalog
from odracir.research_folder import ResearchFolderHarness
from odracir.retrieval import format_search_report, search_chunks
from odracir.status import build_research_status, format_research_status
from odracir.summarization import (
    EvidenceSummaryGenerator,
    build_summary_plan,
    format_summary_plan,
)
from odracir.summary_evaluation import (
    SummaryEvaluationHarness,
    format_summary_evaluation,
)
from odracir.skills import (
    format_research_skill,
    format_research_skills,
    get_builtin_skill_registry,
)
from odracir.translation import (
    DEFAULT_SECTIONS,
    SelectiveTranslator,
    build_translation_plan,
    format_translation_plan,
)


def main() -> None:
    argv = sys.argv[1:]
    if argv and argv[0] == "scan":
        _scan(argv[1:])
        return
    if argv and argv[0] == "prepare":
        _prepare(argv[1:])
        return
    if argv and argv[0] == "extract":
        _extract(argv[1:])
        return
    if argv and argv[0] == "ocr":
        _ocr(argv[1:])
        return
    if argv and argv[0] == "capabilities":
        _capabilities(argv[1:])
        return
    if argv and argv[0] == "benchmark-parsers":
        _benchmark_parsers(argv[1:])
        return
    if argv and argv[0] == "recommend-parsers":
        _recommend_parsers(argv[1:])
        return
    if argv and argv[0] == "status":
        _status(argv[1:])
        return
    if argv and argv[0] == "chunk":
        _chunk(argv[1:])
        return
    if argv and argv[0] == "search":
        _search(argv[1:])
        return
    if argv and argv[0] == "ask":
        _ask(argv[1:])
        return
    if argv and argv[0] == "summarize":
        _summarize(argv[1:])
        return
    if argv and argv[0] == "skills":
        _skills(argv[1:])
        return
    if argv and argv[0] == "evaluate-summaries":
        _evaluate_summaries(argv[1:])
        return
    if argv and argv[0] == "build-memory":
        _build_memory(argv[1:])
        return
    if argv and argv[0] == "plan-reading":
        _plan_reading(argv[1:])
        return
    if argv and argv[0] == "translate":
        _translate(argv[1:])
        return
    if argv and argv[0] == "sync-docs":
        _sync_docs(argv[1:])
        return
    if argv and argv[0] == "install-hooks":
        _install_hooks()
        return

    _chat(argv)


def _chat(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(description="Run the Odracir agent.")
    parser.add_argument("message", nargs="*", help="Message to send to the agent.")
    args = parser.parse_args(argv)

    user_message = " ".join(args.message).strip()
    if not user_message:
        user_message = input("You: ").strip()

    agent = OdracirAgent()
    print(agent.run(user_message))


def _scan(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(description="Scan a research folder.")
    parser.add_argument("folder", nargs="?", default=".", help="Research folder path.")
    parser.add_argument(
        "--papers-dir",
        default=None,
        help="Paper storage directory. Relative paths are resolved inside the research folder.",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args(argv)

    result = ResearchFolderHarness(args.folder, papers_dir=args.papers_dir).sync_index()
    if args.json:
        print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
        return

    print(f"Research folder: {result.root}")
    print(f"Index: {result.index_path}")
    print(
        "Papers: "
        f"{result.total_papers} total, "
        f"{result.new_papers} new, "
        f"{result.updated_papers} updated, "
        f"{result.missing_papers} missing"
    )


def _prepare(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare searchable local research artifacts without calling an LLM or OCR."
        )
    )
    parser.add_argument("folder", nargs="?", default=".", help="Research folder path.")
    parser.add_argument(
        "--papers-dir",
        default=None,
        help="Paper storage directory. Relative paths are resolved inside the research folder.",
    )
    parser.add_argument("--paper", default=None, help="Only prepare one paper id.")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of PDFs.")
    parser.add_argument("--parser", default="pymupdf", help="Registered PDF parser name.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate extraction and chunk artifacts even when current.",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args(argv)

    try:
        result = LocalPreparationHarness(
            args.folder,
            papers_dir=args.papers_dir,
            parser_name=args.parser,
        ).prepare(
            force=args.force,
            limit=args.limit,
            paper_id=args.paper,
        )
    except ValueError as exc:
        parser.error(str(exc))

    if args.json:
        print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
        return
    print(format_local_preparation(result))


def _extract(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(description="Extract PDF text for a research folder.")
    parser.add_argument("folder", nargs="?", default=".", help="Research folder path.")
    parser.add_argument(
        "--papers-dir",
        default=None,
        help="Paper storage directory. Relative paths are resolved inside the research folder.",
    )
    parser.add_argument("--paper", default=None, help="Only extract one paper id.")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of PDFs to extract.")
    parser.add_argument("--parser", default="pymupdf", help="Registered PDF parser name.")
    parser.add_argument("--force", action="store_true", help="Re-extract even if artifacts exist.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args(argv)

    result = PdfTextExtractor(
        args.folder,
        papers_dir=args.papers_dir,
        parser_name=args.parser,
    ).extract_index(
        force=args.force,
        limit=args.limit,
        paper_id=args.paper,
    )
    if args.json:
        print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
        return

    print(f"Research folder: {result.root}")
    print(f"Index: {result.index_path}")
    print(
        "PDF text extraction: "
        f"{result.total_pdf_papers} total, "
        f"{result.extracted} extracted, "
        f"{result.skipped} skipped, "
        f"{result.failed} failed"
    )


def _ocr(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(
        description="Create OCR-enhanced PDF derivatives with OCRmyPDF."
    )
    parser.add_argument("folder", nargs="?", default=".", help="Research folder path.")
    parser.add_argument(
        "--papers-dir",
        default=None,
        help="Paper storage directory. Relative paths are resolved inside the research folder.",
    )
    parser.add_argument("--paper", default=None, help="Only preprocess one paper id.")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of PDFs.")
    parser.add_argument(
        "--language",
        action="append",
        default=None,
        help="OCR language code. Repeat for multiple languages. Defaults to eng.",
    )
    parser.add_argument("--deskew", action="store_true", help="Ask OCRmyPDF to deskew pages.")
    parser.add_argument(
        "--all-pdfs",
        action="store_true",
        help="Process PDFs even when extraction did not mark them as needs_ocr.",
    )
    parser.add_argument("--force", action="store_true", help="Regenerate current OCR PDFs.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args(argv)

    try:
        result = OcrmyPdfPreprocessor(
            args.folder,
            papers_dir=args.papers_dir,
        ).preprocess_index(
            force=args.force,
            limit=args.limit,
            paper_id=args.paper,
            languages=args.language or ("eng",),
            deskew=args.deskew,
            all_pdfs=args.all_pdfs,
        )
    except RuntimeError as exc:
        parser.error(str(exc))

    if args.json:
        print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
        return

    print(f"Research folder: {result.root}")
    print(f"Index: {result.index_path}")
    print(
        "OCR preprocessing: "
        f"{result.eligible_papers} eligible, "
        f"{result.processed} processed, "
        f"{result.skipped} skipped, "
        f"{result.failed} failed"
    )


def _capabilities(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(description="Inspect optional document capabilities.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args(argv)

    report = build_capability_report()
    if args.json:
        print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
        return
    print(format_capability_report(report))


def _benchmark_parsers(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(
        description="Compare registered PDF parsers without writing extraction artifacts."
    )
    parser.add_argument("folder", help="Research folder path.")
    parser.add_argument(
        "--papers-dir",
        default=None,
        help="Paper storage directory. Relative paths are resolved inside the research folder.",
    )
    parser.add_argument(
        "--parser",
        action="append",
        default=None,
        help="Registered parser name. Repeat to compare parsers. Defaults to pymupdf and pymupdf4llm.",
    )
    parser.add_argument("--paper", default=None, help="Only benchmark one paper id.")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of PDFs.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args(argv)

    try:
        report = ParserBenchmarkHarness(
            args.folder,
            papers_dir=args.papers_dir,
        ).run(
            parser_names=tuple(args.parser) if args.parser else ("pymupdf", "pymupdf4llm"),
            paper_id=args.paper,
            limit=args.limit,
        )
    except ValueError as exc:
        parser.error(str(exc))

    if args.json:
        print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
        return
    print(format_parser_benchmark(report))


def _recommend_parsers(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(
        description="Generate cached, advisory parser recommendations from benchmarks."
    )
    parser.add_argument("folder", help="Research folder path.")
    parser.add_argument(
        "--papers-dir",
        default=None,
        help="Paper storage directory. Relative paths are resolved inside the research folder.",
    )
    parser.add_argument("--paper", default=None, help="Only recommend for one paper id.")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of PDFs.")
    parser.add_argument("--force", action="store_true", help="Regenerate cached recommendations.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args(argv)

    try:
        report = ParserRoutingAdvisor(
            args.folder,
            papers_dir=args.papers_dir,
        ).recommend(
            paper_id=args.paper,
            limit=args.limit,
            force=args.force,
        )
    except ValueError as exc:
        parser.error(str(exc))

    if args.json:
        print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
        return
    print(format_parser_routing(report))


def _sync_docs(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(description="Synchronize generated docs sections.")
    parser.add_argument("--root", default=None, help="Project root. Defaults to cwd lookup.")
    args = parser.parse_args(argv)

    changed = sync_project_docs(args.root)
    if changed:
        print("Updated docs:")
        for path in changed:
            print(f"- {path}")
    else:
        print("Docs already up to date.")


def _status(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(description="Report research-folder processing status.")
    parser.add_argument("folder", nargs="?", default=".", help="Research folder path.")
    parser.add_argument(
        "--papers-dir",
        default=None,
        help="Paper storage directory. Relative paths are resolved inside the research folder.",
    )
    parser.add_argument("--no-refresh", action="store_true", help="Read status without rescanning.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args(argv)

    report = build_research_status(
        args.folder,
        papers_dir=args.papers_dir,
        refresh=not args.no_refresh,
    )
    if args.json:
        print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
        return
    print(format_research_status(report))


def _chunk(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(description="Chunk extracted PDF text for a research folder.")
    parser.add_argument("folder", nargs="?", default=".", help="Research folder path.")
    parser.add_argument(
        "--papers-dir",
        default=None,
        help="Paper storage directory. Relative paths are resolved inside the research folder.",
    )
    parser.add_argument("--paper", default=None, help="Only chunk one paper id.")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of PDFs to chunk.")
    parser.add_argument("--force", action="store_true", help="Re-chunk even if artifacts exist.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args(argv)

    result = TextChunker(args.folder, papers_dir=args.papers_dir).chunk_index(
        force=args.force,
        limit=args.limit,
        paper_id=args.paper,
    )
    if args.json:
        print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
        return

    print(f"Research folder: {result.root}")
    print(f"Index: {result.index_path}")
    print(
        "Text chunking: "
        f"{result.eligible_papers} eligible, "
        f"{result.chunked} chunked, "
        f"{result.skipped} skipped, "
        f"{result.blocked} blocked, "
        f"{result.failed} failed"
    )


def _install_hooks() -> None:
    subprocess.run(["git", "config", "core.hooksPath", ".githooks"], check=True)
    print("Configured git to use hooks from .githooks.")


def _search(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(description="Search traceable research chunks.")
    parser.add_argument("folder", help="Research folder path.")
    parser.add_argument("query", nargs="+", help="Search query.")
    parser.add_argument("--limit", type=int, default=5, help="Maximum number of hits.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args(argv)

    report = search_chunks(args.folder, " ".join(args.query), limit=args.limit)
    if args.json:
        print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
        return
    print(format_search_report(report))


def _ask(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(
        description="Answer a research question from retrieved local evidence."
    )
    parser.add_argument("folder", help="Research folder path.")
    parser.add_argument("question", nargs="+", help="Research question.")
    parser.add_argument(
        "--query",
        default=None,
        help="Optional lexical retrieval query. Defaults to the full question.",
    )
    parser.add_argument("--limit", type=int, default=6, help="Maximum evidence chunks.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview retrieved evidence without loading API configuration or calling DeepSeek.",
    )
    parser.add_argument("--force", action="store_true", help="Regenerate a cached answer.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args(argv)

    question = " ".join(args.question)
    try:
        if args.dry_run:
            plan = build_ask_plan(
                args.folder,
                question,
                retrieval_query=args.query,
                limit=args.limit,
            )
            if args.json:
                print(json.dumps(plan.as_dict(), ensure_ascii=False, indent=2))
                return
            print(format_ask_plan(plan))
            return

        result = EvidenceQuestionAnswerer(
            args.folder,
            provider_factory=lambda: DeepSeekProvider(load_config()),
        ).answer(
            question,
            retrieval_query=args.query,
            limit=args.limit,
            force=args.force,
        )
    except ValueError as exc:
        parser.error(str(exc))

    if args.json:
        print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
        return
    print(format_answer_result(result))


def _summarize(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(description="Generate evidence-aware paper summaries.")
    parser.add_argument("folder", nargs="?", default=".", help="Research folder path.")
    parser.add_argument(
        "--papers-dir",
        default=None,
        help="Paper storage directory. Relative paths are resolved inside the research folder.",
    )
    parser.add_argument("--paper", default=None, help="Only summarize one paper id.")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of PDFs.")
    parser.add_argument(
        "--skill",
        default="generic",
        help="Research skill manifest. Defaults to generic.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview summary scope without loading API configuration or calling DeepSeek.",
    )
    parser.add_argument("--force", action="store_true", help="Regenerate current summaries.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args(argv)

    try:
        skill = get_builtin_skill_registry().get(args.skill)
        if args.dry_run:
            plan = build_summary_plan(
                args.folder,
                papers_dir=args.papers_dir,
                limit=args.limit,
                paper_id=args.paper,
                skill=skill,
            )
            if args.json:
                print(json.dumps(plan.as_dict(), ensure_ascii=False, indent=2))
                return
            print(format_summary_plan(plan))
            return

        provider = DeepSeekProvider(load_config())
        result = EvidenceSummaryGenerator(
            args.folder,
            provider,
            papers_dir=args.papers_dir,
            skill=skill,
        ).summarize_index(
            force=args.force,
            limit=args.limit,
            paper_id=args.paper,
        )
    except ValueError as exc:
        parser.error(str(exc))
    if args.json:
        print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
        return

    print(f"Research folder: {result.root}")
    print(f"Index: {result.index_path}")
    print(
        "Paper summaries: "
        f"{result.eligible_papers} eligible, "
        f"{result.summarized} summarized, "
        f"{result.skipped} skipped, "
        f"{result.blocked} blocked, "
        f"{result.failed} failed"
    )


def _skills(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(description="Inspect built-in research skills.")
    parser.add_argument("name", nargs="?", default=None, help="Optional skill name.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args(argv)

    registry = get_builtin_skill_registry()
    try:
        if args.name:
            manifest = registry.get(args.name)
            if args.json:
                print(json.dumps(manifest.as_dict(), ensure_ascii=False, indent=2))
                return
            print(format_research_skill(manifest))
            return
    except ValueError as exc:
        parser.error(str(exc))

    manifests = registry.list()
    if args.json:
        print(
            json.dumps(
                {"skills": [manifest.as_dict() for manifest in manifests]},
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    print(format_research_skills(registry))


def _evaluate_summaries(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(
        description="Audit persisted summary artifacts without calling an LLM."
    )
    parser.add_argument("folder", nargs="?", default=".", help="Research folder path.")
    parser.add_argument(
        "--papers-dir",
        default=None,
        help="Paper storage directory. Relative paths are resolved inside the research folder.",
    )
    parser.add_argument("--paper", default=None, help="Only evaluate one paper id.")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of PDFs.")
    parser.add_argument(
        "--skill",
        default=None,
        help="Require summaries to use this research skill manifest.",
    )
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="Print the report without writing a local evaluation artifact.",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args(argv)

    registry = get_builtin_skill_registry()
    try:
        expected_skill = registry.get(args.skill) if args.skill else None
        report = SummaryEvaluationHarness(
            args.folder,
            papers_dir=args.papers_dir,
            skill_registry=registry,
        ).evaluate(
            paper_id=args.paper,
            limit=args.limit,
            expected_skill=expected_skill,
            write_artifact=not args.no_write,
        )
    except ValueError as exc:
        parser.error(str(exc))

    if args.json:
        print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
        return
    print(format_summary_evaluation(report))


def _build_memory(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(
        description="Build a visible folder-level catalog from audited local artifacts."
    )
    parser.add_argument("folder", nargs="?", default=".", help="Research folder path.")
    parser.add_argument(
        "--papers-dir",
        default=None,
        help="Paper storage directory. Relative paths are resolved inside the research folder.",
    )
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="Print an ephemeral catalog report without writing research_catalog.json.",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args(argv)

    result = ResearchCatalogBuilder(
        args.folder,
        papers_dir=args.papers_dir,
    ).build(write_artifact=not args.no_write)
    if args.json:
        print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
        return
    print(format_research_catalog(result))


def _plan_reading(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(
        description="Build a cached, explainable local reading-priority queue."
    )
    parser.add_argument("folder", nargs="?", default=".", help="Research folder path.")
    parser.add_argument(
        "--papers-dir",
        default=None,
        help="Paper storage directory. Relative paths are resolved inside the research folder.",
    )
    parser.add_argument(
        "--query",
        default=None,
        help="Optional research focus used to prioritize locally relevant papers.",
    )
    parser.add_argument(
        "--skill",
        default="generic",
        help="Research skill for generated supervised-summary commands. Defaults to generic.",
    )
    parser.add_argument("--limit", type=int, default=5, help="Maximum queue entries.")
    parser.add_argument("--force", action="store_true", help="Regenerate a cached queue.")
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="Print an ephemeral queue without writing a local planning artifact.",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args(argv)

    try:
        report = ReadingQueueBuilder(
            args.folder,
            papers_dir=args.papers_dir,
        ).build(
            query=args.query,
            skill_name=args.skill,
            limit=args.limit,
            force=args.force,
            write_artifact=not args.no_write,
        )
    except ValueError as exc:
        parser.error(str(exc))

    if args.json:
        print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
        return
    print(format_reading_queue(report))


def _translate(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(
        description="Translate selected traceable paper chunks through DeepSeek."
    )
    parser.add_argument("folder", nargs="?", default=".", help="Research folder path.")
    parser.add_argument(
        "--papers-dir",
        default=None,
        help="Paper storage directory. Relative paths are resolved inside the research folder.",
    )
    parser.add_argument("--paper", default=None, help="Only translate one paper id.")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of PDFs.")
    parser.add_argument(
        "--target-language",
        default="zh-CN",
        help="Translation target language. Defaults to zh-CN.",
    )
    parser.add_argument(
        "--section",
        action="append",
        default=None,
        help="Preferred section name. Repeat to select multiple sections.",
    )
    parser.add_argument(
        "--chunk",
        action="append",
        default=None,
        help="Explicit chunk id. Repeat to select multiple passages.",
    )
    parser.add_argument(
        "--all-chunks",
        action="store_true",
        help="Translate every chunk. This can consume substantial API usage.",
    )
    parser.add_argument(
        "--max-chunks",
        type=int,
        default=8,
        help="Maximum chunks for selective translation. Defaults to 8.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview selected chunks without loading API configuration or calling DeepSeek.",
    )
    parser.add_argument("--force", action="store_true", help="Regenerate current translations.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args(argv)

    chunk_ids = args.chunk or ()
    sections = args.section if args.section is not None else (() if chunk_ids else DEFAULT_SECTIONS)
    try:
        if args.dry_run:
            plan = build_translation_plan(
                args.folder,
                papers_dir=args.papers_dir,
                limit=args.limit,
                paper_id=args.paper,
                target_language=args.target_language,
                sections=sections,
                chunk_ids=chunk_ids,
                all_chunks=args.all_chunks,
                max_selected_chunks=args.max_chunks,
            )
            if args.json:
                print(json.dumps(plan.as_dict(), ensure_ascii=False, indent=2))
                return
            print(format_translation_plan(plan))
            return

        provider = DeepSeekProvider(load_config())
        result = SelectiveTranslator(
            args.folder,
            provider,
            papers_dir=args.papers_dir,
        ).translate_index(
            force=args.force,
            limit=args.limit,
            paper_id=args.paper,
            target_language=args.target_language,
            sections=sections,
            chunk_ids=chunk_ids,
            all_chunks=args.all_chunks,
            max_selected_chunks=args.max_chunks,
        )
    except ValueError as exc:
        parser.error(str(exc))

    if args.json:
        print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
        return

    print(f"Research folder: {result.root}")
    print(f"Index: {result.index_path}")
    print(
        "Paper translations: "
        f"{result.eligible_papers} eligible, "
        f"{result.translated} translated, "
        f"{result.skipped} skipped, "
        f"{result.blocked} blocked, "
        f"{result.failed} failed"
    )


if __name__ == "__main__":
    main()
