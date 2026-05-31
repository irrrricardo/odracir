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
from odracir.pdf_extraction import PdfTextExtractor
from odracir.providers import DeepSeekProvider
from odracir.research_folder import ResearchFolderHarness
from odracir.retrieval import format_search_report, search_chunks
from odracir.status import build_research_status, format_research_status
from odracir.summarization import EvidenceSummaryGenerator
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
    if argv and argv[0] == "extract":
        _extract(argv[1:])
        return
    if argv and argv[0] == "ocr":
        _ocr(argv[1:])
        return
    if argv and argv[0] == "capabilities":
        _capabilities(argv[1:])
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
    if argv and argv[0] == "summarize":
        _summarize(argv[1:])
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
    parser.add_argument("--force", action="store_true", help="Regenerate current summaries.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args(argv)

    provider = DeepSeekProvider(load_config())
    result = EvidenceSummaryGenerator(
        args.folder,
        provider,
        papers_dir=args.papers_dir,
    ).summarize_index(
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
        "Paper summaries: "
        f"{result.eligible_papers} eligible, "
        f"{result.summarized} summarized, "
        f"{result.skipped} skipped, "
        f"{result.blocked} blocked, "
        f"{result.failed} failed"
    )


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
