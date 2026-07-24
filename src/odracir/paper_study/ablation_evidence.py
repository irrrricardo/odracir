"""Deterministic Odracir 2.2 evidence bundles for SciEngram ablations.

This module never calls a model.  It reconstructs the frozen page-chunk
namespace from source PDFs, verifies every packet provenance reference, and
publishes a namespaced packet/chunk/crosswalk triple for each paper.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from collections.abc import Iterable, Mapping
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from odracir.paper_study.ingestion import extract_pdf_page_chunks
from odracir.paper_study.models import (
    PROVENANCE_SIMILARITY_THRESHOLD,
    PaperStudyPacketV2,
    StrictModel,
    provenance_text_similarity_ratio,
)


Horizon = Literal["long", "short"]

BUNDLE_SCHEMA = "odracir-ablation-evidence-bundle/1"
GROUP_SCHEMA = "odracir-ablation-evidence-group/1"
CHUNK_DOCUMENT_SCHEMA = "sciengram-odracir22-chunk-document/1"
LOCATOR_CROSSWALK_SCHEMA = "sciengram-odracir22-locator-crosswalk/1"
NAMESPACE_POLICY = "paper-id-horizon-suffix-v1"


class AblationEvidenceExportSummary(StrictModel):
    """Small CLI-facing summary for a completed evidence bundle."""

    output_root: str = Field(min_length=1)
    manifest_path: str = Field(min_length=1)
    paper_count: int = Field(ge=1)
    group_count: int = Field(ge=1)
    horizons: tuple[Horizon, ...] = Field(min_length=1)


def export_ablation_evidence_bundle(
    corpus_root: str | Path,
    packets_root: str | Path,
    output_root: str | Path,
    *,
    horizon: Horizon | None = None,
    group: str | None = None,
    paper_id: str | None = None,
) -> AblationEvidenceExportSummary:
    """Export a closed, namespaced packet/chunk/crosswalk evidence bundle.

    ``corpus_root`` and ``packets_root`` must both use ``long/<group>`` and
    ``short/<group>`` subtrees.  The destination is published atomically and
    must not already exist.  Source PDFs and accepted packet artifacts are
    never modified.
    """

    corpus = Path(corpus_root).expanduser().resolve()
    packets = Path(packets_root).expanduser().resolve()
    output = Path(output_root).expanduser().resolve()
    if not corpus.is_dir():
        raise ValueError(f"corpus root is not a directory: {corpus}")
    if not packets.is_dir():
        raise ValueError(f"packets root is not a directory: {packets}")
    if group is not None and horizon is None:
        raise ValueError("--group requires --horizon")
    if paper_id is not None and group is None:
        raise ValueError("--paper-id requires --horizon and --group")
    if output.exists():
        raise ValueError(f"output folder already exists: {output}")

    selections = _discover_groups(packets, horizon=horizon, group=group)
    staging = output.with_name(f".{output.name}.staging")
    if staging.exists():
        raise ValueError(f"stale staging folder already exists: {staging}")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging.mkdir(parents=True)

    group_records: list[dict[str, Any]] = []
    seen_bundle_ids: set[str] = set()
    try:
        for selected_horizon, selected_group, packet_paths in selections:
            selected_paths = packet_paths
            if paper_id is not None:
                selected_paths = tuple(path for path in packet_paths if path.stem == paper_id)
                if not selected_paths:
                    raise ValueError(
                        f"paper packet is missing: {selected_horizon}/{selected_group}/{paper_id}"
                    )
            group_record = _export_group(
                corpus,
                packets,
                staging,
                selected_horizon,
                selected_group,
                selected_paths,
                seen_bundle_ids=seen_bundle_ids,
            )
            group_records.append(group_record)
        if not group_records:
            raise ValueError("no evidence groups were selected")

        manifest: dict[str, Any] = {
            "schema": BUNDLE_SCHEMA,
            "producer": {"name": "odracir", "version": "2.2.0"},
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "namespace_policy": NAMESPACE_POLICY,
            "namespace_format": "<original_paper_id>_<horizon>",
            "source_corpus_root": str(corpus),
            "source_packets_root": str(packets),
            "paper_count": sum(int(item["paper_count"]) for item in group_records),
            "group_count": len(group_records),
            "groups": group_records,
        }
        manifest["content_digest"] = _object_digest(
            {key: value for key, value in manifest.items() if key != "created_at_utc"}
        )
        _write_json(manifest, staging / "bundle_manifest.json")
        staging.replace(output)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    horizons = tuple(
        value
        for value in ("long", "short")
        if any(item["horizon"] == value for item in group_records)
    )
    return AblationEvidenceExportSummary(
        output_root=str(output),
        manifest_path=str(output / "bundle_manifest.json"),
        paper_count=sum(int(item["paper_count"]) for item in group_records),
        group_count=len(group_records),
        horizons=horizons,
    )


def _discover_groups(
    packets_root: Path,
    *,
    horizon: Horizon | None,
    group: str | None,
) -> tuple[tuple[Horizon, str, tuple[Path, ...]], ...]:
    horizons: tuple[Horizon, ...] = (horizon,) if horizon else ("long", "short")
    rows: list[tuple[Horizon, str, tuple[Path, ...]]] = []
    for selected_horizon in horizons:
        horizon_root = packets_root / selected_horizon
        if not horizon_root.is_dir():
            if horizon is None:
                continue
            raise ValueError(f"packet horizon is missing: {horizon_root}")
        group_paths = (
            (horizon_root / group,)
            if group is not None
            else tuple(path for path in horizon_root.iterdir() if path.is_dir())
        )
        for group_path in sorted(group_paths, key=lambda item: _natural_key(item.name)):
            if not group_path.is_dir():
                raise ValueError(f"packet group is missing: {group_path}")
            packet_paths = tuple(
                sorted(
                    (path for path in group_path.glob("*.json") if path.is_file()),
                    key=lambda item: _natural_key(item.stem),
                )
            )
            if not packet_paths:
                raise ValueError(f"packet group is empty: {group_path}")
            rows.append((selected_horizon, group_path.name, packet_paths))
    return tuple(rows)


def _export_group(
    corpus_root: Path,
    packets_root: Path,
    output_root: Path,
    horizon: Horizon,
    group: str,
    packet_paths: tuple[Path, ...],
    *,
    seen_bundle_ids: set[str],
) -> dict[str, Any]:
    group_root = output_root / horizon / group
    packet_output = group_root / "packets"
    chunk_output = group_root / "evidence" / "chunks"
    crosswalk_output = group_root / "evidence" / "crosswalks"
    packet_output.mkdir(parents=True)
    chunk_output.mkdir(parents=True)
    crosswalk_output.mkdir(parents=True)

    records: list[dict[str, Any]] = []
    for packet_path in packet_paths:
        raw_bytes = packet_path.read_bytes()
        packet = json.loads(raw_bytes)
        if not isinstance(packet, dict):
            raise ValueError(f"paper packet must be a JSON object: {packet_path}")
        PaperStudyPacketV2.model_validate(packet)
        original_paper_id = str(packet.get("paper_id") or "")
        if not original_paper_id or packet_path.stem != original_paper_id:
            raise ValueError(f"packet filename and paper_id disagree: {packet_path}")
        bundle_paper_id = namespace_paper_id(original_paper_id, horizon)
        if bundle_paper_id in seen_bundle_ids:
            raise ValueError(f"duplicate namespaced paper_id: {bundle_paper_id}")
        seen_bundle_ids.add(bundle_paper_id)

        metadata = packet.get("metadata")
        if not isinstance(metadata, dict):
            raise ValueError(f"packet metadata must be an object: {packet_path}")
        source_file = str(metadata.get("source_file") or f"{original_paper_id}.pdf")
        source_pdf = _source_pdf(corpus_root, horizon, group, source_file)
        source_sha256, _pages, chunks = extract_pdf_page_chunks(source_pdf)
        expected_source_sha = str(metadata.get("source_sha256") or "")
        if source_sha256 != expected_source_sha:
            raise ValueError(
                f"packet/PDF source SHA mismatch: {horizon}/{group}/{original_paper_id}"
            )

        namespaced_packet = deepcopy(packet)
        namespaced_packet["paper_id"] = bundle_paper_id
        namespaced_metadata = dict(metadata)
        namespaced_metadata.update(
            {
                "ablation_original_paper_id": original_paper_id,
                "ablation_horizon": horizon,
                "ablation_group": group,
                "ablation_namespace_policy": NAMESPACE_POLICY,
                "ablation_source_packet_sha256": _sha256_bytes(raw_bytes),
            }
        )
        namespaced_packet["metadata"] = namespaced_metadata
        PaperStudyPacketV2.model_validate(namespaced_packet)

        chunk_rows = [item.model_dump(mode="json", by_alias=True) for item in chunks]
        chunk_document = {
            "schema": CHUNK_DOCUMENT_SCHEMA,
            "paper_id": bundle_paper_id,
            "original_paper_id": original_paper_id,
            "horizon": horizon,
            "group": group,
            "source_file": source_file,
            "source_sha256": source_sha256,
            "chunker": "odracir.pdf-page",
            "chunker_version": "1.0",
            "chunk_count": len(chunk_rows),
            "chunks": chunk_rows,
        }
        crosswalk = _locator_crosswalk(namespaced_packet, chunk_document)

        packet_target = packet_output / f"{bundle_paper_id}.json"
        chunk_target = chunk_output / f"{bundle_paper_id}.json"
        crosswalk_target = crosswalk_output / f"{bundle_paper_id}.json"
        _write_json(namespaced_packet, packet_target)
        _write_json(chunk_document, chunk_target)
        _write_json(crosswalk, crosswalk_target)
        packet_sha256 = _sha256_file(packet_target)
        chunk_sha256 = _sha256_file(chunk_target)
        crosswalk_sha256 = _sha256_file(crosswalk_target)
        records.append(
            {
                "original_paper_id": original_paper_id,
                "paper_id": bundle_paper_id,
                "source_packet_path": _relative(packet_path, packets_root),
                "source_packet_sha256": _sha256_bytes(raw_bytes),
                "source_pdf_path": _relative(source_pdf, corpus_root),
                "source_sha256": source_sha256,
                "packet_path": _relative(packet_target, output_root),
                "packet_sha256": packet_sha256,
                "chunk_path": _relative(chunk_target, output_root),
                "chunk_sha256": chunk_sha256,
                "crosswalk_path": _relative(crosswalk_target, output_root),
                "crosswalk_sha256": crosswalk_sha256,
                "chunk_count": len(chunk_rows),
                "provenance_reference_count": crosswalk[
                    "provenance_reference_count"
                ],
                "minimum_nonparaphrased_similarity": crosswalk[
                    "minimum_nonparaphrased_similarity"
                ],
            }
        )

    group_manifest: dict[str, Any] = {
        "schema": GROUP_SCHEMA,
        "horizon": horizon,
        "group": group,
        "namespace_policy": NAMESPACE_POLICY,
        "paper_count": len(records),
        "papers": records,
    }
    group_manifest["digest"] = _object_digest(group_manifest)
    manifest_target = group_root / "group_manifest.json"
    _write_json(group_manifest, manifest_target)
    return {
        "horizon": horizon,
        "group": group,
        "paper_count": len(records),
        "manifest_path": _relative(manifest_target, output_root),
        "manifest_sha256": _sha256_file(manifest_target),
        "paper_ids": [item["paper_id"] for item in records],
    }


def namespace_paper_id(original_paper_id: str, horizon: Horizon) -> str:
    """Return the frozen globally unique Ablation Lab paper identifier."""

    value = original_paper_id.strip()
    if not value or not re.fullmatch(r"[A-Za-z0-9._-]+", value):
        raise ValueError(f"unsafe source paper_id: {original_paper_id!r}")
    suffix = f"_{horizon}"
    return value if value.endswith(suffix) else f"{value}{suffix}"


def _locator_crosswalk(
    packet: Mapping[str, Any],
    chunk_document: Mapping[str, Any],
) -> dict[str, Any]:
    chunks = [item for item in chunk_document.get("chunks", []) if isinstance(item, Mapping)]
    by_id = {str(item.get("chunk_id") or ""): item for item in chunks}
    if not by_id or "" in by_id or len(by_id) != len(chunks):
        raise ValueError(f"chunk IDs are missing or duplicated: {packet.get('paper_id')}")
    coverage = packet.get("coverage_ledger")
    if not isinstance(coverage, Mapping):
        raise ValueError(f"packet coverage_ledger is invalid: {packet.get('paper_id')}")
    coverage_ids = {str(item) for item in coverage}
    if coverage_ids != set(by_id):
        missing = sorted(coverage_ids - set(by_id))
        extra = sorted(set(by_id) - coverage_ids)
        raise ValueError(
            f"packet/chunk namespace does not close: {packet.get('paper_id')}; "
            f"missing={missing}, extra={extra}"
        )

    bindings: list[dict[str, Any]] = []
    minimum_similarity: float | None = None
    for source_path, provenance in _provenance_records_with_paths(packet):
        chunk_id = str(provenance["chunk_id"])
        chunk = by_id.get(chunk_id)
        if chunk is None:
            raise ValueError(f"provenance references unknown chunk: {source_path}/{chunk_id}")
        page_start = int(provenance["page_start"])
        page_end = int(provenance["page_end"])
        if int(chunk["page_start"]) > page_end or int(chunk["page_end"]) < page_start:
            raise ValueError(f"provenance page range misses its chunk: {source_path}")
        paraphrased = bool(provenance["paraphrased"])
        similarity: float | None = None
        if not paraphrased:
            similarity = round(
                provenance_text_similarity_ratio(
                    str(provenance["text_excerpt"]),
                    str(chunk["text"]),
                ),
                6,
            )
            if similarity < PROVENANCE_SIMILARITY_THRESHOLD:
                raise ValueError(
                    f"provenance similarity {similarity:.4f} is below "
                    f"{PROVENANCE_SIMILARITY_THRESHOLD:.2f}: {source_path}"
                )
            minimum_similarity = (
                similarity
                if minimum_similarity is None
                else min(minimum_similarity, similarity)
            )
        bindings.append(
            {
                "source_json_path": source_path,
                "upstream_chunk_id": chunk_id,
                "resolved_chunk_id": chunk_id,
                "page_start": page_start,
                "page_end": page_end,
                "paraphrased": paraphrased,
                "binding": "explicit_chunk_id",
                "text_similarity": similarity,
            }
        )
    bindings.sort(key=lambda item: item["source_json_path"])
    payload: dict[str, Any] = {
        "schema": LOCATOR_CROSSWALK_SCHEMA,
        "paper_id": str(packet["paper_id"]),
        "source_sha256": str(chunk_document["source_sha256"]),
        "mode": "exact_chunk_id",
        "original_chunk_namespace_available": True,
        "coverage_entry_count": len(coverage_ids),
        "resolved_chunk_count": len(by_id),
        "coverage_count_matches_resolved_chunks": True,
        "provenance_reference_count": len(bindings),
        "minimum_nonparaphrased_similarity": minimum_similarity,
        "bindings": bindings,
    }
    payload["digest"] = _object_digest(payload)
    return payload


def _provenance_records_with_paths(
    value: Any,
    path: str = "$",
) -> Iterable[tuple[str, Mapping[str, Any]]]:
    if isinstance(value, Mapping):
        required = {"chunk_id", "page_start", "page_end", "text_excerpt", "paraphrased"}
        if required <= set(value):
            yield path, value
        for key, item in value.items():
            yield from _provenance_records_with_paths(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _provenance_records_with_paths(item, f"{path}[{index}]")


def _source_pdf(
    corpus_root: Path,
    horizon: Horizon,
    group: str,
    source_file: str,
) -> Path:
    group_root = (corpus_root / horizon / group).resolve()
    candidate = (group_root / source_file).resolve()
    try:
        candidate.relative_to(group_root)
    except ValueError as exc:
        raise ValueError(f"packet source_file escapes its corpus group: {source_file}") from exc
    if not candidate.is_file() or candidate.suffix.casefold() != ".pdf":
        raise ValueError(f"source PDF is missing: {candidate}")
    return candidate


def _natural_key(value: str) -> tuple[tuple[int, object], ...]:
    return tuple(
        (1, int(part)) if part.isdigit() else (0, part.casefold())
        for part in re.split(r"(\d+)", value)
        if part
    )


def _relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _object_digest(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _write_json(payload: object, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
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
