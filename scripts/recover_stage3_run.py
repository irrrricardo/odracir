#!/usr/bin/env python3
"""Recover failed papers from an existing Odracir Stage 3 run manifest."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from odracir.paper_study.extraction import DeepSeekJsonProvider  # noqa: E402
from odracir.paper_study.recovery import (  # noqa: E402
    Stage3RecoveryConfig,
    recover_stage3_run,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Retry all failed papers after an existing run's final context, then "
            "append one ledger revision and realign deliveries in a new output root "
            "only if every retry succeeds."
        )
    )
    parser.add_argument("--run-manifest", required=True)
    parser.add_argument(
        "--output-folder",
        required=True,
        help="A new, empty output root; the parent run directory is never modified.",
    )
    parser.add_argument("--env-file")
    parser.add_argument("--corpus-id")
    parser.add_argument(
        "--max-chunks",
        type=_positive_int,
        help=(
            "Override selection width; by default reuse the surviving failed-paper "
            "planning artifacts (falling back to 4)."
        ),
    )
    parser.add_argument("--max-tokens", type=_positive_int, default=16_000)
    parser.add_argument("--validation-retries", type=_nonnegative_int, default=1)
    parser.add_argument("--minimum-quality-score", type=_unit_float, default=0.6)
    parser.add_argument("--max-claims-per-paper", type=_nonnegative_int, default=3)
    parser.add_argument("--max-context-findings", type=_positive_int, default=100)
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        provider = DeepSeekJsonProvider.from_environment(env_file=args.env_file)
        result = recover_stage3_run(
            args.run_manifest,
            provider,
            output_root=args.output_folder,
            config=Stage3RecoveryConfig(
                max_chunks=args.max_chunks,
                max_tokens=args.max_tokens,
                validation_retries=args.validation_retries,
                minimum_quality_score=args.minimum_quality_score,
                max_claims_per_paper=args.max_claims_per_paper,
                max_context_findings=args.max_context_findings,
            ),
            corpus_id=args.corpus_id,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(
            json.dumps(
                {"error": str(exc), "status": "failed"},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1

    audit = result.recovery_manifest
    print(
        json.dumps(
            {
                "failed": list(audit.failed_paper_ids),
                "final_manifest": audit.final_run_manifest_path,
                "recovery_manifest": result.recovery_manifest_path,
                "status": audit.status,
                "succeeded": list(audit.succeeded_paper_ids),
            },
            ensure_ascii=False,
        )
    )
    return 0 if audit.status == "completed" else 1


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


if __name__ == "__main__":
    raise SystemExit(main())
