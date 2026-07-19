"""Independent one-PDF-to-one-JSON Odracir 2.1 pipeline."""

from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import Field

from odracir.paper_study.canonicalization import (
    apply_canonicalization_plan,
    plan_canonicalization,
)
from odracir.paper_study.extraction import JsonCompletionProvider, extract_paper_study
from odracir.paper_study.models import (
    PROVENANCE_SOURCE_TEXT_CONTEXT_KEY,
    PaperStudyPacketV2,
    StrictModel,
)
from odracir.paper_study.planning import (
    build_extraction_plan,
    load_chunk_artifact,
)
from odracir.paper_study.quality import evaluate_packet_quality
from odracir.paper_study.scheduler import PaperIndexEntry


_SAFE_PAPER_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class IndependentRunSummary(StrictModel):
    """Compact stdout-only result; this is deliberately not a corpus artifact."""

    schema_version: str = "2.1-run.1"
    input_folder: str = Field(min_length=1)
    output_folder: str = Field(min_length=1)
    paper_ids: tuple[str, ...]
    output_paths: dict[str, str]
    failures: dict[str, str]

    @property
    def succeeded(self) -> int:
        return len(self.output_paths)

    @property
    def failed(self) -> int:
        return len(self.failures)


def run_independent_extractions(
    entries: list[PaperIndexEntry],
    provider: JsonCompletionProvider,
    *,
    input_folder: str | Path,
    output_folder: str | Path,
    max_chunks: int = 4,
    max_tokens: int = 16_000,
    validation_retries: int = 1,
    minimum_quality_score: float = 0.6,
) -> IndependentRunSummary:
    """Extract every entry independently, with no shared state or corpus ordering."""

    root = Path(output_folder).expanduser().resolve()
    _prepare_empty_output_folder(root)
    outputs: dict[str, str] = {}
    failures: dict[str, str] = {}
    ordered = sorted(entries, key=lambda item: (item.paper_id.casefold(), item.source_path))
    for entry in ordered:
        try:
            path = extract_one_paper(
                entry,
                provider,
                output_folder=root,
                max_chunks=max_chunks,
                max_tokens=max_tokens,
                validation_retries=validation_retries,
                minimum_quality_score=minimum_quality_score,
            )
            outputs[entry.paper_id] = str(path)
        except Exception as exc:  # failures are isolated to their source PDF
            failures[entry.paper_id] = str(exc) or type(exc).__name__
    return IndependentRunSummary(
        input_folder=str(Path(input_folder).expanduser().resolve()),
        output_folder=str(root),
        paper_ids=tuple(entry.paper_id for entry in ordered),
        output_paths=outputs,
        failures=failures,
    )


def extract_one_paper(
    entry: PaperIndexEntry,
    provider: JsonCompletionProvider,
    *,
    output_folder: str | Path,
    max_chunks: int = 4,
    max_tokens: int = 16_000,
    validation_retries: int = 1,
    minimum_quality_score: float = 0.6,
) -> Path:
    """Convert one prepared source artifact to exactly one final JSON file."""

    if not _SAFE_PAPER_ID_RE.fullmatch(entry.paper_id) or entry.paper_id in {".", ".."}:
        raise ValueError(f"unsafe paper_id: {entry.paper_id!r}")
    artifact = load_chunk_artifact(entry.source_path)
    if artifact.paper_id != entry.paper_id:
        raise ValueError("chunk artifact paper_id does not match its input entry")
    plan = build_extraction_plan(
        artifact,
        source_chunk_artifact=entry.source_path,
        max_chunks=max_chunks,
    )
    extracted = extract_paper_study(
        artifact,
        plan,
        provider,
        max_tokens=max_tokens,
        validation_retries=validation_retries,
    )
    canonical = apply_canonicalization_plan(
        extracted.packet,
        plan_canonicalization(extracted.packet),
    )
    selected_ids = set(plan.selected_chunk_ids)
    canonical = PaperStudyPacketV2.model_validate(
        canonical.model_dump(mode="python"),
        context={
            PROVENANCE_SOURCE_TEXT_CONTEXT_KEY: {
                chunk.chunk_id: chunk.text
                for chunk in artifact.chunks
                if chunk.chunk_id in selected_ids
            }
        },
    )
    report = evaluate_packet_quality(canonical)
    canonical.quality_score = report.score
    if report.score < minimum_quality_score:
        raise ValueError(
            f"quality score {report.score:.4f} is below {minimum_quality_score:.4f}"
        )
    return _write_packet(canonical, Path(output_folder) / f"{entry.paper_id}.json")


def _prepare_empty_output_folder(root: Path) -> None:
    if root.exists() and any(root.iterdir()):
        raise ValueError(f"output folder must be empty: {root}")
    root.mkdir(parents=True, exist_ok=True)


def _write_packet(packet: PaperStudyPacketV2, target: Path) -> Path:
    # Admission/reconciliation and canonical merge audits belong to the old
    # corpus workflow. The 2.1 public artifact is only the independent paper.
    payload = packet.model_dump(
        mode="json",
        exclude={"status", "requires_reconciliation", "merge_decisions"},
    )
    temporary = target.with_name(f".{target.name}.tmp")
    temporary.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)
    return target.resolve()
