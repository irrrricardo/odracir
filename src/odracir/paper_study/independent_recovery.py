"""Auditable, paper-local recovery for independent Odracir 2.2 runs."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence
from uuid import uuid4

from pydantic import Field

from odracir.paper_study.extraction import JsonCompletionProvider
from odracir.paper_study.independent import (
    IndependentRunSummary,
    run_independent_extractions,
)
from odracir.paper_study.ingestion import ensure_pdf_chunk_artifacts
from odracir.paper_study.models import PaperStudyPacketV2, StrictModel
from odracir.paper_study.inputs import discover_paper_entries
from odracir.paper_study.run_reporting import PaperRunRecord, PricingSnapshot


_SAFE_PAPER_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class IndependentRecoverySummary(StrictModel):
    """Recovery result with final-delivery and audit locations."""

    schema_version: str = "odracir-independent-recovery/1"
    status: str
    source_report: str = Field(min_length=1)
    paper_folder: str = Field(min_length=1)
    delivery_folder: str = Field(min_length=1)
    work_folder: str = Field(min_length=1)
    report_folder: str = Field(min_length=1)
    requested_paper_ids: tuple[str, ...]
    attempted_paper_ids: tuple[str, ...]
    merged_paper_ids: tuple[str, ...]
    already_present_paper_ids: tuple[str, ...]
    failures: dict[str, str]
    delivery_paths: dict[str, str]
    run_report_paths: dict[str, str]
    audit_path: str = Field(min_length=1)


def recover_independent_failures(
    source_report: str | Path,
    provider: JsonCompletionProvider,
    *,
    paper_folder: str | Path,
    delivery_folder: str | Path,
    work_folder: str | Path,
    report_folder: str | Path,
    paper_ids: Sequence[str] | None = None,
    allow_source_change: bool = False,
    max_chunks: int = 8,
    max_tokens: int = 16_000,
    validation_retries: int = 3,
    minimum_quality_score: float = 0.6,
    pricing: PricingSnapshot | None = None,
) -> IndependentRecoverySummary:
    """Retry failed papers and atomically add validated successes to delivery.

    The original report and existing delivery files are immutable.  A fresh work root
    receives staged PDFs and temporary packets; a separate recovery report root retains
    the new run report plus a merge audit.
    """

    source_report_path = Path(source_report).expanduser().resolve()
    source_root = Path(paper_folder).expanduser().resolve()
    delivery_root = Path(delivery_folder).expanduser().resolve()
    work_root = Path(work_folder).expanduser().resolve()
    report_root = Path(report_folder).expanduser().resolve()
    _validate_recovery_roots(
        source_root=source_root,
        delivery_root=delivery_root,
        work_root=work_root,
        report_root=report_root,
    )
    records = _load_source_records(source_report_path)
    failed_by_id = {record.paper_id: record for record in records if record.status == "failed"}
    selected_ids = _select_failed_ids(failed_by_id, paper_ids)
    _prepare_empty_directory(work_root, label="work folder")
    _prepare_empty_directory(report_root, label="report folder")
    delivery_root.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now(timezone.utc)
    resolved_pricing = pricing or PricingSnapshot()

    current_sources: dict[str, Path] = {}
    source_hashes: dict[str, str] = {}
    already_present: list[str] = []
    pending: list[str] = []
    delivery_paths: dict[str, str] = {}
    source_changes: dict[str, dict[str, str]] = {}
    for paper_id in selected_ids:
        if not _SAFE_PAPER_ID_RE.fullmatch(paper_id) or paper_id in {".", ".."}:
            raise ValueError(f"unsafe paper_id in source report: {paper_id!r}")
        source_pdf = source_root / f"{paper_id}.pdf"
        if not source_pdf.is_file():
            raise ValueError(f"recovery source PDF is missing: {source_pdf}")
        current_sha = _sha256(source_pdf)
        prior_sha = failed_by_id[paper_id].source_sha256
        if prior_sha and prior_sha != current_sha:
            source_changes[paper_id] = {
                "reported_source_sha256": prior_sha,
                "current_source_sha256": current_sha,
            }
            if not allow_source_change:
                raise ValueError(
                    f"source PDF changed since the failed run for {paper_id}: "
                    "pass allow_source_change=True only after reviewing the replacement"
                )
        current_sources[paper_id] = source_pdf
        source_hashes[paper_id] = current_sha
        destination = delivery_root / f"{paper_id}.json"
        if destination.exists():
            _validate_delivery_packet(
                destination,
                paper_id=paper_id,
                source_sha256=current_sha,
                minimum_quality_score=minimum_quality_score,
            )
            already_present.append(paper_id)
            delivery_paths[paper_id] = str(destination)
        else:
            pending.append(paper_id)

    run_summary: IndependentRunSummary | None = None
    merged: list[str] = []
    failures: dict[str, str] = {}
    run_report_paths: dict[str, str] = {}
    if pending:
        input_root = work_root / "input"
        packet_root = work_root / "packets"
        input_root.mkdir(parents=True)
        for paper_id in pending:
            shutil.copy2(current_sources[paper_id], input_root / f"{paper_id}.pdf")
        ensure_pdf_chunk_artifacts(input_root)
        entries = discover_paper_entries(input_root)
        discovered_ids = {entry.paper_id for entry in entries}
        if discovered_ids != set(pending):
            raise ValueError(
                "staged recovery inputs do not match requested failures: "
                f"expected={sorted(pending)}, discovered={sorted(discovered_ids)}"
            )
        run_summary = run_independent_extractions(
            entries,
            provider,
            input_folder=input_root,
            output_folder=packet_root,
            report_folder=report_root / "run",
            max_chunks=max_chunks,
            max_tokens=max_tokens,
            validation_retries=validation_retries,
            minimum_quality_score=minimum_quality_score,
            pricing=resolved_pricing,
        )
        run_report_paths = dict(run_summary.report_paths)
        failures = dict(run_summary.failures)
        for paper_id, temporary_path in sorted(run_summary.output_paths.items()):
            temporary_packet = Path(temporary_path)
            _validate_delivery_packet(
                temporary_packet,
                paper_id=paper_id,
                source_sha256=source_hashes[paper_id],
                minimum_quality_score=minimum_quality_score,
            )
            destination = delivery_root / f"{paper_id}.json"
            _copy_without_overwrite(temporary_packet, destination)
            _validate_delivery_packet(
                destination,
                paper_id=paper_id,
                source_sha256=source_hashes[paper_id],
                minimum_quality_score=minimum_quality_score,
            )
            merged.append(paper_id)
            delivery_paths[paper_id] = str(destination)

    completed_at = datetime.now(timezone.utc)
    status = "no-op" if not pending else ("completed" if not failures else "partial")
    audit_path = report_root / "recovery.json"
    audit = {
        "schema_version": "odracir-independent-recovery-audit/1",
        "status": status,
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "source_report": str(source_report_path),
        "paper_folder": str(source_root),
        "delivery_folder": str(delivery_root),
        "work_folder": str(work_root),
        "provider": provider.provider_name,
        "model": provider.model,
        "parameters": {
            "max_chunks": max_chunks,
            "max_tokens": max_tokens,
            "validation_retries": validation_retries,
            "minimum_quality_score": minimum_quality_score,
            "allow_source_change": allow_source_change,
        },
        "requested_paper_ids": selected_ids,
        "attempted_paper_ids": pending,
        "merged_paper_ids": sorted(merged),
        "already_present_paper_ids": sorted(already_present),
        "failures": failures,
        "source_changes": source_changes,
        "delivery_paths": delivery_paths,
        "run_summary": (
            run_summary.model_dump(mode="json") if run_summary is not None else None
        ),
    }
    _write_json(audit_path, audit)
    return IndependentRecoverySummary(
        status=status,
        source_report=str(source_report_path),
        paper_folder=str(source_root),
        delivery_folder=str(delivery_root),
        work_folder=str(work_root),
        report_folder=str(report_root),
        requested_paper_ids=tuple(selected_ids),
        attempted_paper_ids=tuple(pending),
        merged_paper_ids=tuple(sorted(merged)),
        already_present_paper_ids=tuple(sorted(already_present)),
        failures=failures,
        delivery_paths=delivery_paths,
        run_report_paths=run_report_paths,
        audit_path=str(audit_path),
    )


def _load_source_records(path: Path) -> list[PaperRunRecord]:
    if not path.is_file():
        raise ValueError(f"source run report is missing: {path}")
    records = [
        PaperRunRecord.model_validate(json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not records:
        raise ValueError(f"source run report contains no paper records: {path}")
    ids = [record.paper_id for record in records]
    if len(ids) != len(set(ids)):
        raise ValueError("source run report contains duplicate paper_id values")
    return records


def _select_failed_ids(
    failed_by_id: dict[str, PaperRunRecord],
    requested: Sequence[str] | None,
) -> list[str]:
    if requested is None:
        selected = sorted(failed_by_id, key=str.casefold)
    else:
        selected = sorted(set(requested), key=str.casefold)
        unknown = set(selected) - set(failed_by_id)
        if unknown:
            raise ValueError(
                "requested paper IDs are not failed records in the source report: "
                f"{sorted(unknown)}"
            )
    if not selected:
        raise ValueError("source run report has no selected failed papers")
    return selected


def _validate_recovery_roots(
    *,
    source_root: Path,
    delivery_root: Path,
    work_root: Path,
    report_root: Path,
) -> None:
    roots = {
        "paper folder": source_root,
        "delivery folder": delivery_root,
        "work folder": work_root,
        "report folder": report_root,
    }
    if len(set(roots.values())) != len(roots):
        raise ValueError("paper, delivery, work, and report folders must be distinct")
    for mutable_label, mutable_root in (
        ("work folder", work_root),
        ("report folder", report_root),
    ):
        for protected_label, protected_root in (
            ("paper folder", source_root),
            ("delivery folder", delivery_root),
        ):
            if protected_root.is_relative_to(mutable_root) or mutable_root.is_relative_to(
                protected_root
            ):
                raise ValueError(
                    f"{mutable_label} and {protected_label} must not be nested"
                )


def _prepare_empty_directory(path: Path, *, label: str) -> None:
    if path.exists() and any(path.iterdir()):
        raise ValueError(f"{label} must be empty: {path}")
    path.mkdir(parents=True, exist_ok=True)


def _validate_delivery_packet(
    path: Path,
    *,
    paper_id: str,
    source_sha256: str,
    minimum_quality_score: float,
) -> None:
    packet = PaperStudyPacketV2.model_validate_json(path.read_text(encoding="utf-8"))
    if packet.paper_id != paper_id:
        raise ValueError(
            f"recovery packet paper_id mismatch: expected={paper_id}, actual={packet.paper_id}"
        )
    packet_source_sha = packet.metadata.get("source_sha256")
    if packet_source_sha != source_sha256:
        raise ValueError(
            f"recovery packet source hash mismatch for {paper_id}: "
            f"expected={source_sha256}, actual={packet_source_sha}"
        )
    if packet.quality_score < minimum_quality_score:
        raise ValueError(
            f"recovery packet quality {packet.quality_score:.4f} is below "
            f"{minimum_quality_score:.4f} for {paper_id}"
        )


def _copy_without_overwrite(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(
        f".{destination.name}.recovery-{uuid4().hex}.tmp"
    )
    shutil.copy2(source, temporary)
    try:
        os.link(temporary, destination)
    except FileExistsError as exc:
        raise ValueError(f"refusing to overwrite existing delivery: {destination}") from exc
    finally:
        temporary.unlink(missing_ok=True)


def _sha256(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def _write_json(path: Path, payload: object) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
