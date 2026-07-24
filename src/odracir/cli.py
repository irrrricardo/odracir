"""Command-line entry point for independent Odracir 2.2 extraction."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence, TextIO

from odracir.paper_study.ablation_evidence import (
    AblationEvidenceExportSummary,
    export_ablation_evidence_bundle,
)
from odracir.paper_study.extraction import DeepSeekJsonProvider, JsonCompletionProvider
from odracir.paper_study.independent import IndependentRunSummary, run_independent_extractions
from odracir.paper_study.ingestion import ensure_pdf_chunk_artifacts
from odracir.paper_study.inputs import discover_paper_entries
from odracir.paper_study.run_reporting import PricingSnapshot


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments or arguments[0] in {"-h", "--help"}:
        _print_root_help()
        return 0
    if arguments[0] not in {"extract-paper-study", "export-ablation-evidence"}:
        print(f"Unknown command: {arguments[0]}\n", file=sys.stderr)
        _print_root_help(file=sys.stderr)
        return 2
    try:
        if arguments[0] == "extract-paper-study":
            summary = run_extract_paper_study(arguments[1:])
        else:
            summary = run_export_ablation_evidence(arguments[1:])
    except (OSError, RuntimeError, ValueError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}), file=sys.stderr)
        return 1
    print(json.dumps(summary.model_dump(mode="json"), ensure_ascii=False))
    return 0 if not isinstance(summary, IndependentRunSummary) or summary.failed == 0 else 1


def run_export_ablation_evidence(
    argv: Sequence[str],
) -> AblationEvidenceExportSummary:
    """Run the deterministic, API-free Ablation Lab evidence exporter."""

    args = _ablation_evidence_parser().parse_args(list(argv))
    return export_ablation_evidence_bundle(
        args.corpus_root,
        args.packets_root,
        args.output_folder,
        horizon=args.horizon,
        group=args.group,
        paper_id=args.paper_id,
    )


def run_extract_paper_study(
    argv: Sequence[str],
    *,
    provider: JsonCompletionProvider | None = None,
) -> IndependentRunSummary:
    args = _parser().parse_args(list(argv))
    paper_folder = Path(args.paper_folder).expanduser().resolve()
    ensure_pdf_chunk_artifacts(paper_folder)
    entries = discover_paper_entries(paper_folder, index_path=args.index)
    completion_provider = provider or DeepSeekJsonProvider.from_environment(
        env_file=args.env_file
    )
    output_folder = (
        Path(args.output_folder).expanduser().resolve()
        if args.output_folder
        else paper_folder / ".odracir" / "paper-study-2.2"
    )
    report_folder = (
        Path(args.report_folder).expanduser().resolve()
        if args.report_folder
        else output_folder.with_name(f"{output_folder.name}-report")
    )
    pricing = PricingSnapshot(
        input_usd_per_million_tokens=args.input_usd_per_million_tokens,
        output_usd_per_million_tokens=args.output_usd_per_million_tokens,
        pricing_as_of=args.pricing_as_of,
    )
    return run_independent_extractions(
        entries,
        completion_provider,
        input_folder=paper_folder,
        output_folder=output_folder,
        report_folder=report_folder,
        max_chunks=args.max_chunks,
        max_tokens=args.max_tokens,
        validation_retries=args.validation_retries,
        minimum_quality_score=args.minimum_quality_score,
        pricing=pricing,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="odracir extract-paper-study",
        description="Independently convert every PDF to one Odracir 2.2 JSON file.",
    )
    parser.add_argument("--paper-folder", required=True)
    parser.add_argument("--index")
    parser.add_argument("--output-folder")
    parser.add_argument("--report-folder")
    parser.add_argument("--max-chunks", type=_positive_int, default=4)
    parser.add_argument("--max-tokens", type=_positive_int, default=16_000)
    parser.add_argument("--validation-retries", type=_nonnegative_int, default=1)
    parser.add_argument("--minimum-quality-score", type=_unit_float, default=0.6)
    parser.add_argument("--input-usd-per-million-tokens", type=_nonnegative_float)
    parser.add_argument("--output-usd-per-million-tokens", type=_nonnegative_float)
    parser.add_argument("--pricing-as-of")
    parser.add_argument("--env-file")
    return parser


def _ablation_evidence_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="odracir export-ablation-evidence",
        description=(
            "Create namespaced packet/chunk/locator-crosswalk bundles for "
            "SciEngram Ablation Lab without calling a model."
        ),
    )
    parser.add_argument("--corpus-root", required=True)
    parser.add_argument("--packets-root", required=True)
    parser.add_argument("--output-folder", required=True)
    parser.add_argument("--horizon", choices=("long", "short"))
    parser.add_argument("--group")
    parser.add_argument("--paper-id")
    return parser


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def _nonnegative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must not be negative")
    return parsed


def _unit_float(value: str) -> float:
    parsed = float(value)
    if not 0 <= parsed <= 1:
        raise argparse.ArgumentTypeError("must be between 0 and 1")
    return parsed


def _nonnegative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must not be negative")
    return parsed


def _print_root_help(*, file: TextIO = sys.stdout) -> None:
    print(
        "usage: odracir <command> [options]\n\n"
        "commands:\n"
        "  extract-paper-study        Convert each PDF independently to one JSON\n"
        "  export-ablation-evidence  Export API-free SciEngram evidence bundles\n",
        file=file,
    )


if __name__ == "__main__":
    raise SystemExit(main())
