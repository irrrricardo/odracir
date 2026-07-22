#!/usr/bin/env python3
"""Retry failed independent Odracir 2.2 papers and merge validated packets."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from odracir.paper_study.extraction import DeepSeekJsonProvider  # noqa: E402
from odracir.paper_study.independent_recovery import (  # noqa: E402
    recover_independent_failures,
)
from odracir.paper_study.run_reporting import PricingSnapshot  # noqa: E402


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Retry failed records from one independent papers.jsonl report. "
            "Temporary packets remain in a fresh work folder; validated successes "
            "are atomically added to the normal delivery folder without overwriting."
        )
    )
    parser.add_argument("--source-report", required=True)
    parser.add_argument("--paper-folder", required=True)
    parser.add_argument("--delivery-folder", required=True)
    parser.add_argument("--work-folder", required=True)
    parser.add_argument("--report-folder", required=True)
    parser.add_argument("--paper-id", action="append", dest="paper_ids")
    parser.add_argument("--allow-source-change", action="store_true")
    parser.add_argument("--max-chunks", type=_positive_int, default=8)
    parser.add_argument("--max-tokens", type=_positive_int, default=16_000)
    parser.add_argument("--validation-retries", type=_nonnegative_int, default=3)
    parser.add_argument("--minimum-quality-score", type=_unit_float, default=0.6)
    parser.add_argument("--input-usd-per-million-tokens", type=_nonnegative_float)
    parser.add_argument("--output-usd-per-million-tokens", type=_nonnegative_float)
    parser.add_argument("--pricing-as-of")
    parser.add_argument("--env-file")
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        provider = DeepSeekJsonProvider.from_environment(env_file=args.env_file)
        summary = recover_independent_failures(
            args.source_report,
            provider,
            paper_folder=args.paper_folder,
            delivery_folder=args.delivery_folder,
            work_folder=args.work_folder,
            report_folder=args.report_folder,
            paper_ids=args.paper_ids,
            allow_source_change=args.allow_source_change,
            max_chunks=args.max_chunks,
            max_tokens=args.max_tokens,
            validation_retries=args.validation_retries,
            minimum_quality_score=args.minimum_quality_score,
            pricing=PricingSnapshot(
                input_usd_per_million_tokens=args.input_usd_per_million_tokens,
                output_usd_per_million_tokens=args.output_usd_per_million_tokens,
                pricing_as_of=args.pricing_as_of,
            ),
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(
            json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 1

    print(json.dumps(summary.model_dump(mode="json"), ensure_ascii=False))
    return 0 if summary.status in {"completed", "no-op"} else 1


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
    if not 0.0 <= parsed <= 1.0:
        raise argparse.ArgumentTypeError("must be between 0.0 and 1.0")
    return parsed


def _nonnegative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must not be negative")
    return parsed


if __name__ == "__main__":
    raise SystemExit(main())
