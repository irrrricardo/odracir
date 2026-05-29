"""Command-line entry point for Odracir."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys

from odracir.agent import OdracirAgent
from odracir.docs_sync import sync_project_docs
from odracir.pdf_extraction import PdfTextExtractor
from odracir.research_folder import ResearchFolderHarness


def main() -> None:
    argv = sys.argv[1:]
    if argv and argv[0] == "scan":
        _scan(argv[1:])
        return
    if argv and argv[0] == "extract":
        _extract(argv[1:])
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
    parser.add_argument("--force", action="store_true", help="Re-extract even if artifacts exist.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args(argv)

    result = PdfTextExtractor(args.folder, papers_dir=args.papers_dir).extract_index(
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


def _install_hooks() -> None:
    subprocess.run(["git", "config", "core.hooksPath", ".githooks"], check=True)
    print("Configured git to use hooks from .githooks.")


if __name__ == "__main__":
    main()
