"""Command-line entry points for Odracir v2."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence, TextIO

from odracir.paper_study.assembly import (
    assemble_scheduler_result,
    write_corpus_assembly,
)
from odracir.paper_study.extraction import (
    DeepSeekJsonProvider,
    JsonCompletionProvider,
)
from odracir.paper_study.ingestion import ensure_pdf_chunk_artifacts
from odracir.paper_study.pipeline import (
    PaperStudyPipeline,
    PaperStudyPipelineConfig,
    PipelineRunManifest,
    build_run_manifest,
    discover_paper_entries,
    write_run_manifest,
)
from odracir.paper_study.recon import (
    DEFAULT_CLUSTER_DISTANCE_THRESHOLD,
    DEFAULT_MAX_FEATURE_TOKENS,
    build_corpus_manifest_from_entries,
    write_corpus_manifest,
)
from odracir.paper_study.scheduler import MedoidBatcher, run_paper_study_scheduler


def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch the Odracir CLI without adding a Click/Typer dependency."""

    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments or arguments[0] in {"-h", "--help"}:
        _print_root_help()
        return 0
    command, command_arguments = arguments[0], arguments[1:]
    if command != "extract-paper-study":
        print(f"Unknown command: {command}\n", file=sys.stderr)
        _print_root_help(file=sys.stderr)
        return 2

    try:
        manifest, manifest_path = run_extract_paper_study(command_arguments)
    except (OSError, RuntimeError, ValueError) as exc:
        print(
            json.dumps(
                {"command": command, "error": str(exc), "status": "failed"},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1

    print(
        json.dumps(
            {
                "failed": manifest.failed,
                "manifest": str(manifest_path),
                "status": "completed" if manifest.failed == 0 else "partial",
                "succeeded": manifest.succeeded,
                "undated": len(manifest.undated_paper_ids),
            },
            ensure_ascii=False,
        )
    )
    return 0 if manifest.failed == 0 else 1


def run_extract_paper_study(
    argv: Sequence[str],
    *,
    provider: JsonCompletionProvider | None = None,
) -> tuple[PipelineRunManifest, Path]:
    """Parse and execute ``extract-paper-study``; provider injection enables tests."""

    parser = _extract_paper_study_parser()
    args = parser.parse_args(list(argv))
    paper_folder = Path(args.paper_folder).expanduser().resolve()
    ensure_pdf_chunk_artifacts(paper_folder)
    entries = discover_paper_entries(paper_folder, index_path=args.index)
    output_root = (
        Path(args.output_folder).expanduser().resolve()
        if args.output_folder is not None
        else paper_folder / ".odracir" / "paper-study"
    )
    corpus_manifest = build_corpus_manifest_from_entries(
        entries,
        max_feature_tokens=args.max_profile_features,
        cluster_distance_threshold=args.cluster_distance_threshold,
    )
    corpus_manifest_path = write_corpus_manifest(
        corpus_manifest,
        output_root / "recon" / "corpus_manifest.json",
    )
    # Recon is the authoritative Batch 0 membership boundary.  Byte-identical
    # inputs remain auditable in ``duplicate_groups`` but must not reach either
    # strategic planning or the model provider twice.
    representative_ids = {profile.paper_id for profile in corpus_manifest.profiles}
    entries = tuple(
        entry for entry in entries if entry.paper_id in representative_ids
    )
    if {entry.paper_id for entry in entries} != representative_ids:
        missing = sorted(
            representative_ids - {entry.paper_id for entry in entries}
        )
        raise ValueError(
            "Recon representatives could not be resolved to scheduler entries: "
            f"{missing}"
        )
    strategic_plan = MedoidBatcher().plan(
        corpus_manifest,
        batch_size=args.batch_size,
    )
    strategic_plan_path = _write_json_artifact(
        strategic_plan.model_dump(mode="json"),
        output_root / "scheduler" / "strategic_batch_plan.json",
    )
    completion_provider = provider or DeepSeekJsonProvider.from_environment(
        env_file=args.env_file
    )
    pipeline = PaperStudyPipeline(
        completion_provider,
        PaperStudyPipelineConfig(
            output_root=str(output_root),
            max_chunks=args.max_chunks,
            max_tokens=args.max_tokens,
            validation_retries=args.validation_retries,
            minimum_quality_score=args.minimum_quality_score,
        ),
    )
    scheduler_result = run_paper_study_scheduler(
        entries,
        pipeline,
        batch_size=args.batch_size,
        max_claims_per_paper=args.max_claims_per_paper,
        max_context_findings=args.max_context_findings,
        strategic_plan=strategic_plan,
        corpus_manifest=corpus_manifest,
    )
    corpus_id = args.corpus_id or (
        f"corpus-{corpus_manifest.digest().removeprefix('sha256:')[:24]}"
    )
    assembly_result = assemble_scheduler_result(
        scheduler_result,
        corpus_id=corpus_id,
    )
    assembly_paths = write_corpus_assembly(assembly_result, output_root)
    manifest = build_run_manifest(
        paper_folder=paper_folder,
        pipeline=pipeline,
        scheduler_result=scheduler_result,
    )
    manifest = PipelineRunManifest.model_validate(
        {
            **manifest.model_dump(mode="python"),
            "corpus_manifest_path": str(corpus_manifest_path.resolve()),
            "strategic_batch_plan_path": str(strategic_plan_path.resolve()),
            "assembly_manifest_path": assembly_paths["assembly_manifest"],
            "global_state_ledger_path": assembly_paths["ledger"],
            "delivery_paths": {
                key.removeprefix("delivery:"): value
                for key, value in assembly_paths.items()
                if key.startswith("delivery:")
            },
        }
    )
    manifest_path = write_run_manifest(manifest, output_root / "run_manifest.json")
    return manifest, manifest_path


def _extract_paper_study_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="odracir extract-paper-study",
        description=(
            "Run PDF preparation, Corpus Reconnaissance, strategic batching, "
            "paper extraction, ledger reduction, and final reconciliation."
        ),
    )
    parser.add_argument(
        "--paper-folder",
        required=True,
        help=(
            "Folder containing formal PDFs, odracir_index.json, or "
            ".odracir/chunks/*.json."
        ),
    )
    parser.add_argument(
        "--index",
        help="Optional index path; relative paths are resolved under --paper-folder.",
    )
    parser.add_argument("--output-folder", help="Output root for paper-study artifacts.")
    parser.add_argument("--batch-size", type=_positive_int, default=10)
    parser.add_argument("--max-chunks", type=_positive_int, default=4)
    parser.add_argument("--max-tokens", type=_positive_int, default=16_000)
    parser.add_argument("--validation-retries", type=_nonnegative_int, default=1)
    parser.add_argument("--max-claims-per-paper", type=_nonnegative_int, default=3)
    parser.add_argument("--max-context-findings", type=_positive_int, default=100)
    parser.add_argument(
        "--max-profile-features",
        type=_nonnegative_int,
        default=DEFAULT_MAX_FEATURE_TOKENS,
        help="Maximum source-only routing features retained per paper.",
    )
    parser.add_argument(
        "--cluster-distance-threshold",
        type=_unit_float,
        default=DEFAULT_CLUSTER_DISTANCE_THRESHOLD,
        help="Complete-link Recon clustering distance threshold (default: 0.45).",
    )
    parser.add_argument(
        "--corpus-id",
        help="Stable corpus identifier; otherwise derived from the Recon manifest.",
    )
    parser.add_argument(
        "--minimum-quality-score",
        type=_unit_float,
        default=0.6,
        help="QualityGate threshold recorded in the run manifest (default: 0.6).",
    )
    parser.add_argument(
        "--env-file",
        help=(
            "Optional explicit dotenv file for DeepSeek configuration; when omitted, "
            "the nearest project .env is discovered automatically."
        ),
    )
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
    if not 0.0 <= parsed <= 1.0:
        raise argparse.ArgumentTypeError("must be between 0.0 and 1.0")
    return parsed


def _print_root_help(*, file: TextIO = sys.stdout) -> None:
    print(
        "usage: odracir <command> [options]\n\n"
        "commands:\n"
        "  extract-paper-study  Run Recon through reconciled corpus delivery\n\n"
        "Run 'odracir extract-paper-study --help' for command options.",
        file=file,
    )


def _write_json_artifact(payload: object, path: Path) -> Path:
    """Atomically persist a CLI-level orchestration artifact."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    return path


if __name__ == "__main__":
    raise SystemExit(main())
