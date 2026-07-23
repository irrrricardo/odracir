#!/usr/bin/env python3
"""Generate dependency-free reports for a completed Odracir Stage 3 run.

The input is the run's output root.  The script consumes the four Stage 3
manifests plus the content-addressed final ledger and emits machine-readable
JSON/CSV alongside small, deterministic SVG overviews.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from html import escape
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


class VisualizationError(RuntimeError):
    """Raised when a completed Stage 3 result cannot be visualized safely."""


REQUIRED_INPUTS = {
    "corpus_manifest": Path("recon/corpus_manifest.json"),
    "strategic_batch_plan": Path("scheduler/strategic_batch_plan.json"),
    "run_manifest": Path("run_manifest.json"),
    "assembly_manifest": Path("assembly_manifest.json"),
}

ROLE_COLORS = {
    "seed_medoid": "#6d5bd0",
    "skeleton_neighbor": "#1f9d8a",
    "conflict_interleave": "#e07a3f",
}
RELATION_COLORS = {
    "same_as": "#1971c2",
    "broader_than": "#5f3dc4",
    "narrower_than": "#7048e8",
    "supports": "#2b8a3e",
    "contradicts": "#c92a2a",
    "conditioned_on": "#e67700",
    "qualifies": "#0b7285",
    "supersedes": "#495057",
}
STATUS_COLORS = {
    "supported": "#2b8a3e",
    "contested": "#c92a2a",
    "unresolved": "#e67700",
    "superseded": "#868e96",
}


def _load_object(path: Path, *, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise VisualizationError(f"Missing {label}: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VisualizationError(f"Cannot read valid JSON from {label}: {path}") from exc
    if not isinstance(payload, dict):
        raise VisualizationError(f"Expected a JSON object for {label}: {path}")
    return payload


def _require_list(payload: Mapping[str, Any], key: str, *, label: str) -> list[Any]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise VisualizationError(f"{label}.{key} must be a JSON array")
    return value


def _objects(values: Sequence[Any], *, label: str) -> list[dict[str, Any]]:
    if not all(isinstance(value, dict) for value in values):
        raise VisualizationError(f"{label} must contain only JSON objects")
    return list(values)  # type: ignore[return-value]


def _resolve_manifest_path(raw_path: Any, *, root: Path, fallback: Path) -> Path:
    if isinstance(raw_path, str) and raw_path.strip():
        candidate = Path(raw_path).expanduser()
        if not candidate.is_absolute():
            candidate = root / candidate
        if candidate.is_file():
            return candidate.resolve()
    if fallback.is_file():
        return fallback.resolve()
    raise VisualizationError(
        "Assembly manifest does not point to a readable final ledger and the "
        f"compatibility ledger is missing: {fallback}"
    )


def _resolve_stage3_input_path(
    raw_path: Any,
    *,
    root: Path,
    fallback: Path,
    label: str,
) -> Path:
    candidate = _resolve_optional_path(raw_path, root=root)
    if candidate is not None and candidate.is_file():
        return candidate
    if fallback.is_file():
        return fallback.resolve()
    raise VisualizationError(
        f"Missing {label}: neither run_manifest pointer {raw_path!r} nor "
        f"fallback {fallback} is readable"
    )


def _resolve_optional_path(raw_path: Any, *, root: Path) -> Path | None:
    if not isinstance(raw_path, str) or not raw_path.strip():
        return None
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    return candidate.resolve()


def _json_digest(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _csv_value(value: Any) -> Any:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return " | ".join(str(item) for item in value)
    return value


def _write_csv(path: Path, fieldnames: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({name: _csv_value(row.get(name)) for name in fieldnames})


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_svg(path: Path, *, width: int, height: int, body: str) -> None:
    path.write_text(
        "\n".join(
            (
                '<?xml version="1.0" encoding="UTF-8"?>',
                f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
                f'height="{height}" viewBox="0 0 {width} {height}">',
                "<style>"
                "text{font-family:Inter,Arial,sans-serif;fill:#263238}"
                ".title{font-size:20px;font-weight:700}"
                ".subtitle{font-size:12px;fill:#607d8b}"
                ".axis{font-size:11px;fill:#455a64}"
                ".label{font-size:10px}"
                ".small{font-size:9px;fill:#546e7a}"
                "</style>",
                '<rect width="100%" height="100%" fill="#fbfcfe"/>',
                body,
                "</svg>",
                "",
            )
        ),
        encoding="utf-8",
    )


def _short(value: Any, limit: int = 28) -> str:
    text = str(value or "")
    return text if len(text) <= limit else text[: max(1, limit - 1)] + "…"


def _paper_profile_rows(
    profiles: Sequence[Mapping[str, Any]],
    clusters: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    cluster_by_paper: dict[str, str] = {}
    for cluster in clusters:
        cluster_id = str(cluster.get("cluster_id", ""))
        for paper_id in cluster.get("member_paper_ids", []):
            cluster_by_paper[str(paper_id)] = cluster_id
    rows = []
    for profile in profiles:
        metadata = profile.get("metadata_features")
        metadata = metadata if isinstance(metadata, dict) else {}
        paper_id = str(profile.get("paper_id", ""))
        rows.append(
            {
                "paper_id": paper_id,
                "cluster_id": cluster_by_paper.get(paper_id, ""),
                "title": metadata.get("title"),
                "year": metadata.get("year"),
                "domain": profile.get("domain"),
                "logic_mode": profile.get("logic_mode"),
                "chunk_count": profile.get("chunk_count"),
                "page_start": profile.get("page_start"),
                "page_end": profile.get("page_end"),
                "total_char_count": profile.get("total_char_count"),
                "total_token_estimate": profile.get("total_token_estimate"),
                "experimental_systems": profile.get("experimental_systems", []),
                "methods": profile.get("methods", []),
                "causal_rungs": profile.get("causal_rungs", []),
                "conflict_signals": profile.get("conflict_signals", []),
                "conflict_score": profile.get("conflict_score"),
                "quality_proxy": profile.get("quality_proxy"),
                "profile_digest": profile.get("profile_digest"),
            }
        )
    return rows


def _quality_rows(
    papers: Sequence[Mapping[str, Any]],
    deliveries_by_paper: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    for paper in papers:
        paper_id = str(paper.get("paper_id", ""))
        delivery = deliveries_by_paper.get(paper_id, {})
        packet = delivery.get("packet")
        packet = packet if isinstance(packet, dict) else {}
        packet_status = paper.get("packet_status") or packet.get("status")
        quality_score = paper.get("quality_score")
        if not isinstance(quality_score, (int, float)):
            quality_score = packet.get("quality_score")
        requires_reconciliation = paper.get("requires_reconciliation")
        if not isinstance(requires_reconciliation, bool):
            requires_reconciliation = packet.get("requires_reconciliation")
        admitted_provisionally = paper.get("admitted_provisionally") is True
        if packet_status == "provisional":
            admitted_provisionally = True
        rows.append(
            {
                "paper_id": paper_id,
                "batch_number": paper.get("batch_number"),
                "position_in_batch": paper.get("position_in_batch"),
                "status": paper.get("status"),
                "quality_score": quality_score,
                "quality_passed": paper.get("quality_passed"),
                "packet_status": packet_status,
                "requires_reconciliation": requires_reconciliation,
                "admitted_provisionally": admitted_provisionally,
                "warning_codes": paper.get("warning_codes", []),
                "failed_stage": paper.get("failed_stage"),
                "error_type": paper.get("error_type"),
                "error_message": paper.get("error_message"),
            }
        )
    return rows


def _effective_assignments(
    assignments: Sequence[Mapping[str, Any]],
    papers: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Join planned roles to actual execution coordinates after recovery."""

    outcomes = {str(item.get("paper_id", "")): item for item in papers}
    effective: list[dict[str, Any]] = []
    planned_ids: set[str] = set()
    for assignment in assignments:
        paper_id = str(assignment.get("paper_id", ""))
        planned_ids.add(paper_id)
        planned_batch = assignment.get("batch_number")
        planned_position = assignment.get("position_in_batch")
        outcome = outcomes.get(paper_id, {})
        actual_batch = outcome.get("batch_number", planned_batch)
        actual_position = outcome.get("position_in_batch", planned_position)
        effective.append(
            {
                **assignment,
                "batch_number": actual_batch,
                "position_in_batch": actual_position,
                "planned_batch_number": planned_batch,
                "planned_position_in_batch": planned_position,
                "execution_moved": (
                    actual_batch != planned_batch or actual_position != planned_position
                ),
            }
        )
    for paper_id, outcome in outcomes.items():
        if paper_id in planned_ids:
            continue
        effective.append(
            {
                "paper_id": paper_id,
                "batch_number": outcome.get("batch_number"),
                "position_in_batch": outcome.get("position_in_batch"),
                "planned_batch_number": None,
                "planned_position_in_batch": None,
                "role": "unplanned_recovery",
                "anchor_paper_id": paper_id,
                "skeleton_similarity_ppm": None,
                "conflict_signal_overlap": None,
                "execution_moved": True,
            }
        )
    return sorted(
        effective,
        key=lambda item: (
            int(item.get("batch_number") or 0),
            int(item.get("position_in_batch") or 0),
            str(item.get("paper_id", "")),
        ),
    )


def _batch_rows(
    assignments: Sequence[Mapping[str, Any]],
    papers: Sequence[Mapping[str, Any]],
    batch_summaries: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    outcomes = {str(item.get("paper_id")): item for item in papers}
    summaries = {int(item.get("batch_number", -1)): item for item in batch_summaries}
    rows = []
    for assignment in assignments:
        paper_id = str(assignment.get("paper_id", ""))
        batch_number = int(assignment.get("batch_number", -1))
        outcome = outcomes.get(paper_id, {})
        summary = summaries.get(batch_number, {})
        rows.append(
            {
                "batch_number": batch_number,
                "position_in_batch": assignment.get("position_in_batch"),
                "planned_batch_number": assignment.get("planned_batch_number"),
                "planned_position_in_batch": assignment.get(
                    "planned_position_in_batch"
                ),
                "execution_moved": assignment.get("execution_moved", False),
                "paper_id": paper_id,
                "role": assignment.get("role"),
                "anchor_paper_id": assignment.get("anchor_paper_id"),
                "skeleton_similarity_ppm": assignment.get("skeleton_similarity_ppm"),
                "conflict_signal_overlap": assignment.get("conflict_signal_overlap"),
                "run_status": outcome.get("status"),
                "quality_score": outcome.get("quality_score"),
                "batch_succeeded": summary.get("succeeded"),
                "batch_failed": summary.get("failed"),
                "extracted_finding_count": summary.get("extracted_finding_count"),
            }
        )
    return rows


def _relation_rows(
    assertions: Sequence[Mapping[str, Any]], relations: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    assertion_by_id = {
        str(assertion.get("assertion_id")): assertion for assertion in assertions
    }
    rows = []
    for relation in relations:
        source_id = str(relation.get("source_assertion_id", ""))
        target_id = str(relation.get("target_assertion_id", ""))
        source = assertion_by_id.get(source_id, {})
        target = assertion_by_id.get(target_id, {})
        score_ppm = relation.get("score_ppm")
        rows.append(
            {
                "relation_id": relation.get("relation_id"),
                "source_assertion_id": source_id,
                "target_assertion_id": target_id,
                "relation_type": relation.get("relation_type"),
                "score_ppm": score_ppm,
                "score": (
                    round(float(score_ppm) / 1_000_000, 6)
                    if isinstance(score_ppm, (int, float))
                    else None
                ),
                "source_status": source.get("status"),
                "target_status": target.get("status"),
                "source_statement": source.get("preferred_statement"),
                "target_statement": target.get("preferred_statement"),
            }
        )
    return rows


def _delivery_audit(
    *,
    assembly: Mapping[str, Any],
    run: Mapping[str, Any],
    papers: Sequence[Mapping[str, Any]],
    run_root: Path,
    assembly_root: Path,
    final_ledger_digest: str,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    expected_ids = tuple(
        sorted(
            str(paper.get("paper_id", ""))
            for paper in papers
            if paper.get("status") == "succeeded"
        )
    )
    path_maps: list[tuple[Mapping[str, Any], Path]] = []
    for owner, owner_root in ((assembly, assembly_root), (run, run_root)):
        for key in ("delivery_paths", "compatibility_delivery_paths"):
            value = owner.get(key, {})
            if isinstance(value, dict):
                path_maps.append((value, owner_root))
    declared_ids = {
        str(paper_id) for path_map, _ in path_maps for paper_id in path_map
    }
    found_ids: list[str] = []
    missing_ids: list[str] = []
    invalid: dict[str, str] = {}
    deliveries: dict[str, dict[str, Any]] = {}
    packet_digest_mismatches: list[str] = []
    alignment_output_digest_mismatches: list[str] = []
    alignment_scores: list[int] = []
    alignment_types: Counter[str] = Counter()

    for paper_id in expected_ids:
        declared_paths = [
            path
            for path_map, owner_root in path_maps
            if (
                path := _resolve_optional_path(
                    path_map.get(paper_id),
                    root=owner_root,
                )
            )
            is not None
        ]
        path = next((candidate for candidate in declared_paths if candidate.is_file()), None)
        if path is None:
            missing_ids.append(paper_id)
            continue
        found_ids.append(paper_id)
        try:
            delivery = _load_object(path, label=f"delivery {paper_id}")
            packet = delivery.get("packet")
            alignments = delivery.get("alignments")
            if not isinstance(packet, dict):
                raise VisualizationError("delivery.packet must be a JSON object")
            if str(packet.get("paper_id", "")) != paper_id:
                raise VisualizationError("delivery packet paper_id does not match")
            if not isinstance(alignments, list) or not all(
                isinstance(item, dict) for item in alignments
            ):
                raise VisualizationError("delivery.alignments must contain objects")
        except VisualizationError as exc:
            invalid[paper_id] = str(exc)
            continue

        deliveries[paper_id] = delivery
        if delivery.get("packet_digest") != _json_digest(packet):
            packet_digest_mismatches.append(paper_id)
        for alignment in alignments:
            if alignment.get("output_ledger_digest") != final_ledger_digest:
                alignment_output_digest_mismatches.append(
                    f"{paper_id}:{alignment.get('alignment_id', '')}"
                )
            score = alignment.get("score_ppm")
            if isinstance(score, int):
                alignment_scores.append(score)
            alignment_types[str(alignment.get("relation_type", "unknown"))] += 1

    audit = {
        "expected_count": len(expected_ids),
        "found_count": len(found_ids),
        "valid_count": len(deliveries),
        "missing_count": len(missing_ids),
        "invalid_count": len(invalid),
        "expected_paper_ids": list(expected_ids),
        "missing_paper_ids": missing_ids,
        "invalid": dict(sorted(invalid.items())),
        "unexpected_declared_paper_ids": sorted(declared_ids - set(expected_ids)),
        "packet_digest_mismatch_count": len(packet_digest_mismatches),
        "packet_digest_mismatch_paper_ids": sorted(packet_digest_mismatches),
        "alignment_count": sum(alignment_types.values()),
        "alignment_relation_types": dict(sorted(alignment_types.items())),
        "alignment_score_ppm": {
            "min": min(alignment_scores, default=None),
            "max": max(alignment_scores, default=None),
            "mean": (
                round(sum(alignment_scores) / len(alignment_scores), 3)
                if alignment_scores
                else None
            ),
            "histogram": dict(
                sorted(Counter(str(score) for score in alignment_scores).items())
            ),
        },
        "output_ledger_digest_mismatch_count": len(
            alignment_output_digest_mismatches
        ),
        "output_ledger_digest_mismatches": sorted(
            alignment_output_digest_mismatches
        ),
    }
    return deliveries, audit


def _evidence_weight_audit(assertions: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    admissions: Counter[str] = Counter()
    weights: Counter[str] = Counter()
    violations: list[str] = []
    provisional_only = 0
    evidence_count = 0
    for assertion in assertions:
        assertion_id = str(assertion.get("assertion_id", ""))
        evidence = assertion.get("evidence", [])
        if not isinstance(evidence, list):
            violations.append(f"{assertion_id}:evidence_not_array")
            continue
        statuses = set()
        for index, item in enumerate(evidence):
            if not isinstance(item, dict):
                violations.append(f"{assertion_id}:{index}:not_object")
                continue
            evidence_count += 1
            status = str(item.get("admission_status", "unknown"))
            weight = item.get("weight_ppm")
            statuses.add(status)
            admissions[status] += 1
            weights[str(weight)] += 1
            if status == "accepted" and weight != 1_000_000:
                violations.append(f"{assertion_id}:{index}:accepted_weight")
            if status == "provisional" and not (
                isinstance(weight, int) and 1 <= weight <= 500_000
            ):
                violations.append(f"{assertion_id}:{index}:provisional_weight")
        if statuses == {"provisional"}:
            provisional_only += 1
    return {
        "evidence_count": evidence_count,
        "admission_statuses": dict(sorted(admissions.items())),
        "weight_ppm_histogram": dict(sorted(weights.items())),
        "provisional_only_assertion_count": provisional_only,
        "weight_violation_count": len(violations),
        "weight_violations": violations,
    }


def _snapshot_chain_audit(
    *,
    assembly: Mapping[str, Any],
    root: Path,
    final_revision: Any,
    final_ledger_digest: str,
) -> dict[str, Any]:
    raw_paths = assembly.get("snapshot_paths", [])
    if not isinstance(raw_paths, list):
        return {
            "available": False,
            "chain_ok": False,
            "error": "assembly_manifest.snapshot_paths is not an array",
        }
    if not raw_paths:
        return {"available": False, "chain_ok": None, "snapshot_count": 0}

    snapshots: dict[int, tuple[dict[str, Any], str]] = {}
    invalid: list[str] = []
    missing_paths: list[str] = []
    for raw_path in raw_paths:
        path = _resolve_optional_path(raw_path, root=root)
        if path is None or not path.is_file():
            missing_paths.append(str(raw_path))
            continue
        try:
            payload = _load_object(path, label="ledger snapshot")
            revision = payload.get("revision")
            if not isinstance(revision, int) or revision < 0:
                raise VisualizationError("ledger snapshot revision must be nonnegative")
            if revision in snapshots:
                raise VisualizationError(f"duplicate snapshot revision {revision}")
            snapshots[revision] = (payload, _json_digest(payload))
        except VisualizationError as exc:
            invalid.append(f"{path}:{exc}")

    revisions = sorted(snapshots)
    expected_revisions = (
        list(range(final_revision + 1))
        if isinstance(final_revision, int) and final_revision >= 0
        else []
    )
    missing_revisions = sorted(set(expected_revisions) - set(revisions))
    parent_mismatches: list[int] = []
    event_prefix_mismatches: list[int] = []
    for revision in revisions:
        if revision == 0 or revision - 1 not in snapshots:
            continue
        current, _ = snapshots[revision]
        previous, previous_digest = snapshots[revision - 1]
        if current.get("parent_digest") != previous_digest:
            parent_mismatches.append(revision)
        old_events = previous.get("events")
        new_events = current.get("events")
        if isinstance(old_events, list) and isinstance(new_events, list):
            if new_events[: len(old_events)] != old_events:
                event_prefix_mismatches.append(revision)
    final_snapshot_matches = (
        isinstance(final_revision, int)
        and final_revision in snapshots
        and snapshots[final_revision][1] == final_ledger_digest
    )
    chain_ok = not any(
        (
            missing_paths,
            invalid,
            missing_revisions,
            parent_mismatches,
            event_prefix_mismatches,
        )
    ) and final_snapshot_matches
    return {
        "available": True,
        "chain_ok": chain_ok,
        "declared_snapshot_count": len(raw_paths),
        "snapshot_count": len(snapshots),
        "revisions": revisions,
        "missing_revisions": missing_revisions,
        "missing_paths": missing_paths,
        "invalid": invalid,
        "parent_digest_mismatch_revisions": parent_mismatches,
        "event_prefix_mismatch_revisions": event_prefix_mismatches,
        "final_snapshot_matches_ledger": final_snapshot_matches,
    }


def _load_optional_recovery_manifest(
    root: Path,
) -> tuple[dict[str, Any] | None, Path | None]:
    candidates = (
        root / "recovery" / "recovery_manifest.json",
        root / "recovery_manifest.json",
    )
    for path in candidates:
        if path.is_file():
            return _load_object(path, label="recovery manifest"), path.resolve()
    return None, None


def _cluster_batch_svg(
    clusters: Sequence[Mapping[str, Any]], assignments: Sequence[Mapping[str, Any]]
) -> tuple[int, int, str]:
    ordered_clusters = sorted(clusters, key=lambda item: str(item.get("cluster_id", "")))
    cluster_by_paper = {
        str(paper_id): str(cluster.get("cluster_id", ""))
        for cluster in ordered_clusters
        for paper_id in cluster.get("member_paper_ids", [])
    }
    batches = sorted({int(item.get("batch_number", 0)) for item in assignments})
    width = max(760, 250 + 115 * len(batches))
    height = max(300, 150 + 78 * len(ordered_clusters))
    left, top, cell_w, cell_h = 220, 105, 105, 68
    parts = [
        '<text x="28" y="34" class="title">Corpus clusters → execution batches</text>',
        '<text x="28" y="55" class="subtitle">Columns use actual execution coordinates; color preserves the planned strategic role.</text>',
    ]
    for index, batch in enumerate(batches):
        x = left + index * cell_w + cell_w / 2
        parts.append(f'<text x="{x:.1f}" y="88" class="axis" text-anchor="middle">Batch {batch}</text>')
    for row, cluster in enumerate(ordered_clusters):
        y = top + row * cell_h
        cluster_id = str(cluster.get("cluster_id", ""))
        member_count = len(cluster.get("member_paper_ids", []))
        parts.append(
            f'<text x="18" y="{y + 27}" class="axis">{escape(_short(cluster_id, 25))} ({member_count})</text>'
        )
        for column, _batch in enumerate(batches):
            x = left + column * cell_w
            parts.append(
                f'<rect x="{x}" y="{y}" width="{cell_w - 8}" height="{cell_h - 8}" rx="5" fill="#f1f4f8" stroke="#dbe3ea"/>'
            )
    per_cell: dict[tuple[str, int], list[Mapping[str, Any]]] = defaultdict(list)
    for assignment in assignments:
        paper_id = str(assignment.get("paper_id", ""))
        per_cell[(cluster_by_paper.get(paper_id, ""), int(assignment.get("batch_number", 0)))].append(assignment)
    cluster_index = {str(item.get("cluster_id", "")): index for index, item in enumerate(ordered_clusters)}
    batch_index = {batch: index for index, batch in enumerate(batches)}
    for (cluster_id, batch), items in sorted(per_cell.items()):
        if cluster_id not in cluster_index or batch not in batch_index:
            continue
        base_x = left + batch_index[batch] * cell_w + 12
        base_y = top + cluster_index[cluster_id] * cell_h + 12
        for index, item in enumerate(sorted(items, key=lambda value: int(value.get("position_in_batch", 0)))):
            paper_id = str(item.get("paper_id", ""))
            x = base_x + (index % 3) * 27
            y = base_y + (index // 3) * 26
            color = ROLE_COLORS.get(str(item.get("role")), "#78909c")
            parts.extend(
                (
                    f'<circle cx="{x}" cy="{y}" r="8" fill="{color}"><title>{escape(paper_id)} — {escape(str(item.get("role", "")))}</title></circle>',
                    f'<text x="{x}" y="{y + 19}" class="small" text-anchor="middle">{escape(_short(paper_id, 7))}</text>',
                )
            )
    legend_y = height - 26
    legend_x = 28
    for role, color in ROLE_COLORS.items():
        parts.append(f'<circle cx="{legend_x}" cy="{legend_y}" r="6" fill="{color}"/>')
        parts.append(f'<text x="{legend_x + 11}" y="{legend_y + 4}" class="small">{escape(role)}</text>')
        legend_x += 130
    return width, height, "\n".join(parts)


def _quality_svg(quality_rows: Sequence[Mapping[str, Any]]) -> tuple[int, int, str]:
    rows = sorted(
        quality_rows,
        key=lambda row: (
            int(row.get("batch_number") or 0),
            int(row.get("position_in_batch") or 0),
            str(row.get("paper_id", "")),
        ),
    )
    width = 940
    height = max(290, 125 + 27 * len(rows))
    left, right, top, row_h = 230, 56, 82, 27
    plot_w = width - left - right
    parts = [
        '<text x="28" y="34" class="title">Per-paper quality scores</text>',
        '<text x="28" y="55" class="subtitle">Green: accepted pass · amber: provisional · red: rejected gate · gray: no score</text>',
    ]
    for tick in range(0, 11, 2):
        score = tick / 10
        x = left + score * plot_w
        parts.append(f'<line x1="{x:.1f}" y1="{top - 12}" x2="{x:.1f}" y2="{height - 35}" stroke="#e3e9ef"/>')
        parts.append(f'<text x="{x:.1f}" y="{top - 19}" class="axis" text-anchor="middle">{score:.1f}</text>')
    for index, row in enumerate(rows):
        y = top + index * row_h
        score = row.get("quality_score")
        paper_id = str(row.get("paper_id", ""))
        batch = row.get("batch_number")
        parts.append(f'<text x="18" y="{y + 10}" class="label">B{batch} · {escape(_short(paper_id, 27))}</text>')
        parts.append(f'<rect x="{left}" y="{y}" width="{plot_w}" height="13" rx="3" fill="#eef2f5"/>')
        if isinstance(score, (int, float)):
            bounded = min(1.0, max(0.0, float(score)))
            passed = row.get("quality_passed") is True
            provisional = row.get("packet_status") == "provisional"
            color = "#e67700" if provisional else ("#2b8a3e" if passed else "#c92a2a")
            parts.append(f'<rect x="{left}" y="{y}" width="{bounded * plot_w:.1f}" height="13" rx="3" fill="{color}"/>')
            parts.append(f'<text x="{left + bounded * plot_w + 6:.1f}" y="{y + 11}" class="small">{bounded:.3f}</text>')
        else:
            parts.append(f'<text x="{left + 6}" y="{y + 11}" class="small">no score ({escape(str(row.get("status", "unknown")))})</text>')
    return width, height, "\n".join(parts)


def _ledger_svg(
    assertions: Sequence[Mapping[str, Any]],
    relations: Sequence[Mapping[str, Any]],
    *,
    max_nodes: int = 80,
) -> tuple[int, int, str, dict[str, int]]:
    assertions_by_id = {
        str(assertion.get("assertion_id", "")): assertion for assertion in assertions
    }
    degree = Counter()
    for relation in relations:
        degree[str(relation.get("source_assertion_id", ""))] += 1
        degree[str(relation.get("target_assertion_id", ""))] += 1
    ranked = sorted(assertions_by_id, key=lambda item: (-degree[item], item))
    shown_ids = set(ranked[:max_nodes])
    shown_relations = [
        item
        for item in relations
        if str(item.get("source_assertion_id", "")) in shown_ids
        and str(item.get("target_assertion_id", "")) in shown_ids
    ]
    ordered_ids = sorted(shown_ids)
    width, height = 1120, 820
    cx, cy, radius = width / 2, height / 2 + 20, min(width, height) * 0.39
    positions = {
        assertion_id: (
            cx + radius * math.cos(-math.pi / 2 + 2 * math.pi * index / max(1, len(ordered_ids))),
            cy + radius * math.sin(-math.pi / 2 + 2 * math.pi * index / max(1, len(ordered_ids))),
        )
        for index, assertion_id in enumerate(ordered_ids)
    }
    omitted = len(assertions) - len(ordered_ids)
    parts = [
        '<defs><marker id="arrow" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto"><path d="M0,0 L7,3.5 L0,7 Z" fill="#90a4ae"/></marker></defs>',
        '<text x="28" y="34" class="title">Final GlobalStateLedger relation map</text>',
        f'<text x="28" y="55" class="subtitle">Showing {len(ordered_ids)} of {len(assertions)} assertions and {len(shown_relations)} of {len(relations)} relations; nodes are selected by degree.</text>',
    ]
    for relation in sorted(shown_relations, key=lambda item: str(item.get("relation_id", ""))):
        source_id = str(relation.get("source_assertion_id", ""))
        target_id = str(relation.get("target_assertion_id", ""))
        x1, y1 = positions[source_id]
        x2, y2 = positions[target_id]
        relation_type = str(relation.get("relation_type", ""))
        color = RELATION_COLORS.get(relation_type, "#90a4ae")
        dash = ' stroke-dasharray="5,4"' if relation_type == "conditioned_on" else ""
        parts.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{color}" stroke-width="1.4" opacity="0.62" marker-end="url(#arrow)"{dash}><title>{escape(relation_type)} · score {escape(str(relation.get("score_ppm", "")))}</title></line>'
        )
    node_radius = 7 if len(ordered_ids) > 40 else 10
    for assertion_id in ordered_ids:
        assertion = assertions_by_id[assertion_id]
        x, y = positions[assertion_id]
        status = str(assertion.get("status", ""))
        color = STATUS_COLORS.get(status, "#607d8b")
        statement = str(assertion.get("preferred_statement", ""))
        parts.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{node_radius}" fill="{color}" stroke="#fff" stroke-width="2"><title>{escape(assertion_id)}\n{escape(statement)}\nstatus: {escape(status)}</title></circle>'
        )
    legend_x = 28
    legend_y = height - 25
    for relation_type, color in RELATION_COLORS.items():
        parts.append(f'<line x1="{legend_x}" y1="{legend_y}" x2="{legend_x + 18}" y2="{legend_y}" stroke="{color}" stroke-width="3"/>')
        parts.append(f'<text x="{legend_x + 24}" y="{legend_y + 4}" class="small">{escape(relation_type)}</text>')
        legend_x += 130
    stats = {
        "displayed_assertion_count": len(ordered_ids),
        "omitted_assertion_count": omitted,
        "displayed_relation_count": len(shown_relations),
        "omitted_relation_count": len(relations) - len(shown_relations),
    }
    return width, height, "\n".join(parts), stats


def generate_visualizations(
    output_root: str | Path,
    output_dir: str | Path | None = None,
) -> dict[str, str]:
    """Generate Stage 3 JSON, CSV, and SVG reports and return absolute paths."""

    root = Path(output_root).expanduser().resolve()
    if not root.is_dir():
        raise VisualizationError(f"Stage 3 output root is not a directory: {root}")
    run_path = root / REQUIRED_INPUTS["run_manifest"]
    run = _load_object(run_path, label="run_manifest")
    corpus_path = _resolve_stage3_input_path(
        run.get("corpus_manifest_path"),
        root=root,
        fallback=root / REQUIRED_INPUTS["corpus_manifest"],
        label="corpus_manifest",
    )
    plan_path = _resolve_stage3_input_path(
        run.get("strategic_batch_plan_path"),
        root=root,
        fallback=root / REQUIRED_INPUTS["strategic_batch_plan"],
        label="strategic_batch_plan",
    )
    assembly_path = _resolve_stage3_input_path(
        run.get("assembly_manifest_path"),
        root=root,
        fallback=root / REQUIRED_INPUTS["assembly_manifest"],
        label="assembly_manifest",
    )
    corpus = _load_object(corpus_path, label="corpus_manifest")
    plan = _load_object(plan_path, label="strategic_batch_plan")
    assembly = _load_object(assembly_path, label="assembly_manifest")
    profiles = _objects(_require_list(corpus, "profiles", label="corpus_manifest"), label="corpus_manifest.profiles")
    clusters = _objects(_require_list(corpus, "clusters", label="corpus_manifest"), label="corpus_manifest.clusters")
    raw_duplicate_groups = corpus.get("duplicate_groups", [])
    if not isinstance(raw_duplicate_groups, list):
        raise VisualizationError("corpus_manifest.duplicate_groups must be a JSON array")
    duplicate_groups = _objects(
        raw_duplicate_groups,
        label="corpus_manifest.duplicate_groups",
    )
    assignments = _objects(_require_list(plan, "assignments", label="strategic_batch_plan"), label="strategic_batch_plan.assignments")
    papers = _objects(_require_list(run, "papers", label="run_manifest"), label="run_manifest.papers")
    batch_summaries = _objects(_require_list(run, "batches", label="run_manifest"), label="run_manifest.batches")
    if not profiles:
        raise VisualizationError("No Recon paper profiles are available to visualize")
    if not clusters:
        raise VisualizationError("No Recon clusters are available to visualize")
    if not assignments:
        raise VisualizationError("No strategic batch assignments are available to visualize")
    if not papers or not any(item.get("status") == "succeeded" for item in papers):
        raise VisualizationError("The run contains no successful paper results")

    ledger_path = _resolve_manifest_path(
        assembly.get("ledger_path") or assembly.get("compatibility_ledger_path"),
        root=assembly_path.parent,
        fallback=assembly_path.parent / "ledger/global_state_ledger.json",
    )
    ledger = _load_object(ledger_path, label="final ledger")
    assertions = _objects(_require_list(ledger, "assertions", label="final ledger"), label="final ledger.assertions")
    relations = _objects(_require_list(ledger, "relations", label="final ledger"), label="final ledger.relations")
    if not assertions:
        raise VisualizationError("The final ledger contains no assertions to visualize")

    destination = (
        Path(output_dir).expanduser().resolve()
        if output_dir is not None
        else root / "visualizations"
    )
    destination.mkdir(parents=True, exist_ok=True)

    final_ledger_digest = _json_digest(ledger)
    deliveries_by_paper, delivery_audit = _delivery_audit(
        assembly=assembly,
        run=run,
        papers=papers,
        run_root=run_path.parent,
        assembly_root=assembly_path.parent,
        final_ledger_digest=final_ledger_digest,
    )
    recovery, recovery_path = _load_optional_recovery_manifest(root)
    effective_assignments = _effective_assignments(assignments, papers)
    profile_rows = _paper_profile_rows(profiles, clusters)
    quality_rows = _quality_rows(papers, deliveries_by_paper)
    batch_rows = _batch_rows(effective_assignments, papers, batch_summaries)
    relation_rows = _relation_rows(assertions, relations)
    csv_specs = {
        "paper_profiles_csv": (
            destination / "paper_profiles.csv",
            [
                "paper_id", "cluster_id", "title", "year", "domain", "logic_mode",
                "chunk_count", "page_start", "page_end", "total_char_count",
                "total_token_estimate", "experimental_systems", "methods",
                "causal_rungs", "conflict_signals", "conflict_score",
                "quality_proxy", "profile_digest",
            ],
            profile_rows,
        ),
        "quality_csv": (
            destination / "quality.csv",
            [
                "paper_id", "batch_number", "position_in_batch", "status",
                "quality_score", "quality_passed", "packet_status",
                "requires_reconciliation", "admitted_provisionally",
                "warning_codes", "failed_stage",
                "error_type", "error_message",
            ],
            quality_rows,
        ),
        "relations_csv": (
            destination / "relations.csv",
            [
                "relation_id", "source_assertion_id", "target_assertion_id",
                "relation_type", "score_ppm", "score", "source_status",
                "target_status", "source_statement", "target_statement",
            ],
            relation_rows,
        ),
        "batches_csv": (
            destination / "batches.csv",
            [
                "batch_number", "position_in_batch", "planned_batch_number",
                "planned_position_in_batch", "execution_moved", "paper_id", "role",
                "anchor_paper_id", "skeleton_similarity_ppm",
                "conflict_signal_overlap", "run_status", "quality_score",
                "batch_succeeded", "batch_failed", "extracted_finding_count",
            ],
            batch_rows,
        ),
    }
    paths: dict[str, str] = {}
    for key, (path, columns, rows) in csv_specs.items():
        _write_csv(path, columns, rows)
        paths[key] = str(path.resolve())

    cluster_width, cluster_height, cluster_body = _cluster_batch_svg(
        clusters, effective_assignments
    )
    cluster_path = destination / "cluster_batch_map.svg"
    _write_svg(cluster_path, width=cluster_width, height=cluster_height, body=cluster_body)
    paths["cluster_batch_map_svg"] = str(cluster_path.resolve())
    quality_width, quality_height, quality_body = _quality_svg(quality_rows)
    quality_path = destination / "quality_scores.svg"
    _write_svg(quality_path, width=quality_width, height=quality_height, body=quality_body)
    paths["quality_scores_svg"] = str(quality_path.resolve())
    ledger_width, ledger_height, ledger_body, ledger_view = _ledger_svg(assertions, relations)
    ledger_svg_path = destination / "ledger_relations.svg"
    _write_svg(ledger_svg_path, width=ledger_width, height=ledger_height, body=ledger_body)
    paths["ledger_relations_svg"] = str(ledger_svg_path.resolve())

    scores = [
        float(row["quality_score"])
        for row in quality_rows
        if isinstance(row.get("quality_score"), (int, float))
    ]
    summary_path = destination / "visualization_summary.json"
    actual_batch_numbers = sorted(
        {
            int(item.get("batch_number", 0))
            for item in batch_summaries
            if isinstance(item.get("batch_number"), int)
        }
    )
    ledger_revision = ledger.get("revision")
    recovery_summary: dict[str, Any] = {"present": recovery is not None}
    if recovery is not None:
        recovery_batch = recovery.get("recovery_batch_number")
        recovery_summary.update(
            {
                "manifest_path": str(recovery_path),
                "status": recovery.get("status"),
                "recovery_batch_number": recovery_batch,
                "attempted_paper_ids": recovery.get("attempted_paper_ids", []),
                "succeeded_paper_ids": recovery.get("succeeded_paper_ids", []),
                "failed_paper_ids": recovery.get("failed_paper_ids", []),
                "recovery_batch_matches_final_revision": (
                    recovery_batch == ledger_revision
                ),
            }
        )
    snapshot_audit = _snapshot_chain_audit(
        assembly=assembly,
        root=assembly_path.parent,
        final_revision=ledger_revision,
        final_ledger_digest=final_ledger_digest,
    )
    event_types = Counter()
    events = ledger.get("events", [])
    if isinstance(events, list):
        event_types.update(
            str(event.get("event_type", "unknown"))
            for event in events
            if isinstance(event, dict)
        )
    summary = {
        "schema_version": "1.0",
        "output_root": str(root),
        "source_paths": {
            "corpus_manifest": str(corpus_path),
            "strategic_batch_plan": str(plan_path),
            "run_manifest": str(run_path.resolve()),
            "assembly_manifest": str(assembly_path),
            "final_ledger": str(ledger_path),
            **(
                {"recovery_manifest": str(recovery_path)}
                if recovery_path is not None
                else {}
            ),
        },
        "corpus": {
            "paper_count": len(profiles),
            "cluster_count": len(clusters),
            "batch_count": len(actual_batch_numbers),
            "actual_batch_numbers": actual_batch_numbers,
            "planned_batch_count": len(
                {
                    int(item.get("batch_number", 0))
                    for item in assignments
                    if isinstance(item.get("batch_number"), int)
                }
            ),
            "max_batch_number": max(actual_batch_numbers, default=0),
            "seed_count": sum(row.get("role") == "seed_medoid" for row in batch_rows),
            "execution_moved_count": sum(
                row.get("execution_moved") is True for row in batch_rows
            ),
            "duplicate_group_count": len(duplicate_groups),
            "deduplicated_input_count": sum(
                len(group.get("duplicate_paper_ids", [])) for group in duplicate_groups
            ),
        },
        "run": {
            "succeeded": sum(row.get("status") == "succeeded" for row in quality_rows),
            "failed": sum(row.get("status") == "failed" for row in quality_rows),
            "quality_passed": sum(row.get("quality_passed") is True for row in quality_rows),
            "quality_failed": sum(row.get("quality_passed") is False for row in quality_rows),
            "accepted_packets": sum(row.get("packet_status") == "accepted" for row in quality_rows),
            "provisional_packets": sum(row.get("packet_status") == "provisional" for row in quality_rows),
            "requires_reconciliation": sum(row.get("requires_reconciliation") is True for row in quality_rows),
            "quality_score_mean": round(sum(scores) / len(scores), 6) if scores else None,
            "quality_score_min": round(min(scores), 6) if scores else None,
            "quality_score_max": round(max(scores), 6) if scores else None,
        },
        "ledger": {
            "revision": ledger_revision,
            "calculated_digest": final_ledger_digest,
            "declared_digest": assembly.get("final_ledger_digest"),
            "declared_digest_matches": (
                assembly.get("final_ledger_digest") in {None, final_ledger_digest}
            ),
            "revision_matches_run_batches": (
                ledger_revision == max(actual_batch_numbers, default=0)
            ),
            "assertion_count": len(assertions),
            "relation_count": len(relations),
            "relation_types": dict(sorted(Counter(str(row.get("relation_type", "unknown")) for row in relations).items())),
            "assertion_statuses": dict(sorted(Counter(str(row.get("status", "unknown")) for row in assertions).items())),
            "event_types": dict(sorted(event_types.items())),
            "evidence_weights": _evidence_weight_audit(assertions),
            "snapshot_chain": snapshot_audit,
            "graph_view": ledger_view,
        },
        "deliveries": delivery_audit,
        "recovery": recovery_summary,
        "artifacts": dict(sorted({**paths, "summary_json": str(summary_path.resolve())}.items())),
    }
    _write_json(summary_path, summary)
    paths["summary_json"] = str(summary_path.resolve())
    return dict(sorted(paths.items()))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate CSV/JSON/SVG reports for a completed Odracir Stage 3 run."
    )
    parser.add_argument("output_root", help="Completed extract-paper-study output root")
    parser.add_argument(
        "--output-dir",
        help="Destination directory (default: OUTPUT_ROOT/visualizations)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        paths = generate_visualizations(args.output_root, args.output_dir)
    except VisualizationError as exc:
        print(f"visualize-stage3-run: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(paths, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
