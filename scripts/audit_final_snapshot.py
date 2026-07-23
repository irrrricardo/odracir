#!/usr/bin/env python3
"""Audit and visualize a materialized Stage 3/SciEngram release."""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import io
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Sequence


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify Odracir-to-SciEngram claim coverage, release digests, and "
            "write deterministic audit tables and SVG summaries."
        )
    )
    parser.add_argument("--root", required=True, help="Final reconciliation root.")
    parser.add_argument(
        "--output-folder",
        help="Output root; defaults to --root (using audit/ and visualizations/).",
    )
    parser.add_argument(
        "--conflict-specs",
        required=True,
        help="Exact human-review conflict specification used for this release.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    root = Path(args.root).expanduser().resolve()
    output = (
        Path(args.output_folder).expanduser().resolve()
        if args.output_folder
        else root
    )
    conflict_specs_path = Path(args.conflict_specs).expanduser().resolve()
    audit_root = output / "audit"
    visual_root = output / "visualizations"
    audit_root.mkdir(parents=True, exist_ok=True)
    visual_root.mkdir(parents=True, exist_ok=True)

    finalization = _read_json(root / "finalization_manifest.json")
    decisions = _read_json(root / "odracir/reconciliation_decisions.json")
    core_snapshot = _read_json(root / "odracir/core_knowledge_snapshot.json")
    export_manifest = _read_json(root / "sciengram_export/export_manifest.json")
    checkpoint = _read_json(root / "sciengram_core/core_checkpoint.json")
    replayed = _read_json(root / "sciengram_core/replayed_checkpoint.json")
    normalized = _read_json(
        root / "sciengram_core/core_snapshot.sciengram/manifest.json"
    )
    compatibility = _read_json(root / "sciengram_core/compatibility_patch.json")
    alignment_audit = _read_json(root / "sciengram_core/alignment_audit.json")
    contract = _read_json(root / "sciengram_core/contract_audit.json")
    strict_eval = _read_json(root / "sciengram_0.10/strict_evaluation.json")
    conflicts = _read_json(root / "human_review/critical_conflicts.json")
    conflict_specs = json.loads(conflict_specs_path.read_text(encoding="utf-8"))
    if not isinstance(conflict_specs, list):
        raise ValueError("conflict specification must be an array")
    quality_rows = _read_csv(root / "sciengram_export/quality_report.csv")

    rows = _claim_crosswalk(root, checkpoint)
    _write_json(
        {
            "schema_version": "odracir-sciengram-claim-crosswalk/1",
            "source_ledger_digest": finalization["source_ledger_digest"],
            "claim_count": len(rows),
            "claims": rows,
        },
        audit_root / "claim_crosswalk.json",
    )
    _write_crosswalk_csv(rows, audit_root / "claim_crosswalk.csv")
    shortlist_csv = root / "human_review/critical_conflict_shortlist.csv"
    shortlist_markdown = root / "human_review/critical_conflict_shortlist.md"
    _write_conflict_shortlist(conflicts, shortlist_csv, shortlist_markdown)

    disposition_counts = Counter(row["reconciliation_disposition"] for row in rows)
    odracir_clusters: dict[str, list[dict[str, Any]]] = defaultdict(list)
    core_clusters: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        odracir_clusters[row["odracir_assertion_id"]].append(row)
        core_clusters[row["sciengram_canonical_claim_id"]].append(row)
    cross_paper_core_clusters = sum(
        len({row["paper_id"] for row in members}) > 1
        for members in core_clusters.values()
    )
    belief_labels = Counter(
        label
        for item in checkpoint["belief_states"]
        for label in item.get("derived_labels", [])
    )
    max_alignment_candidate_score = max(
        (
            candidate["total"]
            for decision in alignment_audit["decisions"]
            for candidate in decision["candidates"]
        ),
        default=0.0,
    )
    normalized_physical_valid = _validate_normalized_store(
        root / "sciengram_core/core_snapshot.sciengram",
        normalized,
    )
    core_materialization = _core_materialization_audit(root)
    finalization_checksum_valid = _single_checksum_valid(
        root / "finalization_manifest.sha256",
        root / "finalization_manifest.json",
    )
    conflict_checksums_valid = _checksum_file_valid(
        root / "human_review/critical_conflicts.sha256",
        root / "human_review",
    )
    canonical_none_count = sum(
        bool(re.search(r"\bnone\b", node["text"], re.IGNORECASE))
        for node in checkpoint["graph"]["nodes"]
        if node["kind"] == "canonical_claim"
    )

    checkpoint_digest = checkpoint["metadata"]["semantic_digest"]
    replay_digest = replayed["metadata"]["semantic_digest"]
    normalized_digest = normalized["semantic_digest"]
    ledger_digests = {
        finalization["source_ledger_digest"],
        core_snapshot["source_ledger_digest"],
        decisions["source_ledger_digest"],
        export_manifest["source_ledger_digest"],
        conflicts["ledger_digest"],
    }
    checks = {
        "claim_crosswalk_complete": len(rows)
        == export_manifest["aggregate_counts"]["claims"],
        "claim_keys_unique": len(rows)
        == len({(row["paper_id"], row["claim_id"]) for row in rows}),
        "local_assertions_unique": len(rows)
        == len({row["sciengram_local_assertion_id"] for row in rows}),
        "ledger_digest_bound_across_planes": len(ledger_digests) == 1,
        "contract_audit_passed": contract["failed_packet_count"] == 0
        and contract["all_relations_accounted"],
        "core_checkpoint_has_no_validation_errors": not checkpoint["metadata"].get(
            "validation_errors"
        ),
        "core_checkpoint_materializes_and_validates": core_materialization[
            "checkpoint_valid"
        ],
        "normalized_store_materializes_and_validates": core_materialization[
            "normalized_valid"
        ],
        "core_replay_semantically_identical": checkpoint_digest == replay_digest,
        "normalized_store_semantically_identical": checkpoint_digest
        == normalized_digest,
        "normalized_store_physical_manifest_valid": normalized_physical_valid,
        "finalization_manifest_checksum_valid": finalization_checksum_valid,
        "finalization_declared_assembly_checksum_valid": _file_digest(
            Path(finalization["source_assembly_manifest"])
        )
        == finalization["source_assembly_manifest_sha256"],
        "finalization_declared_reconciliation_checksum_valid": _file_digest(
            Path(finalization["reconciliation"]["manifest"])
        )
        == finalization["reconciliation"]["manifest_sha256"],
        "finalization_declared_export_checksum_valid": _file_digest(
            Path(finalization["sciengram_export"]["manifest"])
        )
        == finalization["sciengram_export"]["manifest_sha256"],
        "finalization_declared_quality_checksum_valid": _file_digest(
            Path(finalization["sciengram_export"]["quality_report"])
        )
        == finalization["sciengram_export"]["quality_report_sha256"],
        "human_review_checksums_valid": conflict_checksums_valid,
        "human_review_spec_count_bound": len(conflict_specs)
        == len(conflicts["conflicts"]),
        "compatibility_wrapper_checksum_valid": _file_digest(
            Path(compatibility["wrapper_path"])
        )
        == compatibility["wrapper_sha256"],
        "compatibility_upstream_checksum_valid": _file_digest(
            Path(compatibility["upstream_relations_path"])
        )
        == compatibility["upstream_relations_sha256"],
        "canonical_none_negation_removed": canonical_none_count == 0,
        "compatibility_strict_gate_passed": strict_eval["quality_status"] == "passed"
        and not strict_eval["issues"],
        "compatibility_object_coverage_complete": strict_eval["metrics"][
            "packet_object_coverage"
        ]
        == 1.0,
        "compatibility_edge_coverage_complete": strict_eval["metrics"][
            "edge_coverage_by_relation_id"
        ]
        == 1.0,
    }
    warnings = []
    if cross_paper_core_clusters == 0:
        warnings.append(
            "The 0.90 SciEngram alignment threshold produced no cross-paper "
            "canonical co-clusters; the snapshot is corpus-wide but its 91 claim "
            "families remain singleton evidence families."
        )
    if belief_labels.get("INSUFFICIENT"):
        warnings.append(
            "Every active belief state is labelled INSUFFICIENT because each has "
            "only one independent source paper after conservative admission."
        )
    core_local_assertion_ids = {
        node["id"]
        for node in checkpoint["graph"]["nodes"]
        if node["kind"] == "paper_assertion"
        and node["attributes"].get("reconciliation_disposition")
        == "core_accepted"
    }
    proposed_eligibility = [
        item
        for item in checkpoint["reasoning_ledger"]["eligibility"]
        if item.get("status") == "proposed"
        and item["source_assertion_id"] in core_local_assertion_ids
    ]
    if proposed_eligibility:
        warnings.append(
            f"SciEngram retained {len(proposed_eligibility)} grounded core support "
            "edges as proposed because they scored below its 0.85 automatic "
            "finding-admission threshold."
        )
    if finalization["reconciliation"]["evidence_disposition_counts"].get(
        "excluded_invalid", 0
    ):
        warnings.append(
            "Claims lacking a complete Claim-to-Result inference basis were retained "
            "for audit but excluded from core belief registration."
        )

    artifact_paths = [
        "finalization_manifest.json",
        "odracir/core_knowledge_snapshot.json",
        "odracir/reconciliation_decisions.json",
        "odracir/reconciliation_manifest.json",
        "sciengram_export/export_manifest.json",
        "sciengram_export/quality_report.csv",
        "sciengram_core/contract_audit.json",
        "sciengram_core/core_checkpoint.json",
        "sciengram_core/replayed_checkpoint.json",
        "sciengram_core/core_snapshot.sciengram/manifest.json",
        "sciengram_core/compatibility_patch.json",
        "sciengram_core/alignment_audit.json",
        "sciengram_core/replay_manifest.json",
        "sciengram_core/scientific_events.jsonl",
        "sciengram_0.10/cognifold_graph.json",
        "sciengram_0.10/import_summary.json",
        "sciengram_0.10/strict_evaluation.json",
        "human_review/critical_conflicts.json",
        "human_review/critical_conflicts.csv",
        "human_review/critical_conflicts.md",
        "human_review/critical_conflict_shortlist.csv",
        "human_review/critical_conflict_shortlist.md",
    ]
    audit = {
        "schema_version": "stage3-release-audit/1",
        "valid": all(checks.values()),
        "corpus_id": finalization["corpus_id"],
        "source_ledger_digest": finalization["source_ledger_digest"],
        "source_ledger_revision": finalization["source_ledger_revision"],
        "checks": checks,
        "counts": {
            "papers": export_manifest["packet_count"],
            "study_units": export_manifest["aggregate_counts"]["experiments"],
            "results": export_manifest["aggregate_counts"]["results"],
            "claims": len(rows),
            "odracir_assertions": len(odracir_clusters),
            "sciengram_canonical_claims": len(core_clusters),
            "sciengram_cross_paper_claim_clusters": cross_paper_core_clusters,
            "core_accepted_claims": disposition_counts["core_accepted"],
            "deferred_claims": disposition_counts["deferred"],
            "excluded_invalid_claims": disposition_counts["excluded_invalid"],
            "core_registered_support_edges": contract["raw_relation_counts"].get(
                "supports", 0
            ),
            "core_relation_observations": len(checkpoint["relation_ledger"]),
            "core_belief_states": len(checkpoint["belief_states"]),
            "core_proposed_eligibility_assessments": len(proposed_eligibility),
            "critical_human_review_pairs": len(conflicts["conflicts"]),
        },
        "quality": {
            "mean_score": round(
                sum(float(row["quality_score"]) for row in quality_rows)
                / len(quality_rows),
                6,
            ),
            "accepted_packets": sum(
                row["packet_status"] == "accepted" for row in quality_rows
            ),
            "provisional_packets": sum(
                row["packet_status"] == "provisional" for row in quality_rows
            ),
        },
        "core": {
            "semantic_digest": checkpoint_digest,
            "normalized_store_digest": normalized["store_digest"],
            "belief_label_counts": dict(sorted(belief_labels.items())),
            "evidence_policy": checkpoint["metadata"]["evidence_policy"],
            "alignment_threshold": 0.90,
            "alignment_created_canonical_count": sum(
                item["created_canonical"] for item in alignment_audit["decisions"]
            ),
            "max_rejected_alignment_candidate_score": max_alignment_candidate_score,
            "compatibility_patch_id": compatibility["patch_id"],
            "materialization_verification": core_materialization,
        },
        "conflict_report_digest": conflicts["report_digest"],
        "conflict_specification": {
            "path": str(conflict_specs_path),
            "sha256": _file_digest(conflict_specs_path),
            "pair_count": len(conflict_specs),
            "discovery_mode": "explicit_spec_then_strict_provenance_resolution",
        },
        "warnings": warnings,
        "artifacts": {
            path: {
                "bytes": (root / path).stat().st_size,
                "sha256": _file_digest(root / path),
            }
            for path in artifact_paths
        },
    }
    audit_path = audit_root / "release_audit.json"
    _write_json(audit, audit_path)
    checksum_payload = "\n".join(
        f"{_file_digest(path)}  {path.name}"
        for path in (
            audit_root / "claim_crosswalk.csv",
            audit_root / "claim_crosswalk.json",
            audit_path,
        )
    )
    _write_text(checksum_payload + "\n", audit_root / "audit.sha256")

    disposition_svg_path = visual_root / "reconciliation_dispositions.svg"
    quality_svg_path = visual_root / "quality_and_status.svg"
    conflict_svg_path = visual_root / "critical_conflict_map.svg"
    _write_text(
        _disposition_svg(disposition_counts),
        disposition_svg_path,
    )
    _write_text(
        _quality_svg(quality_rows, conflicts),
        quality_svg_path,
    )
    _write_text(
        _conflict_svg(conflicts),
        conflict_svg_path,
    )

    release_manifest = {
        "schema_version": "stage3-sciengram-release/1",
        "valid": audit["valid"],
        "engine_readable": checks["contract_audit_passed"]
        and checks["core_checkpoint_materializes_and_validates"]
        and checks["normalized_store_materializes_and_validates"]
        and checks["compatibility_strict_gate_passed"],
        "consensus_ready": cross_paper_core_clusters > 0
        and not belief_labels.get("INSUFFICIENT"),
        "semantic_status": "conservative_candidate_snapshot",
        "corpus_id": audit["corpus_id"],
        "source_ledger_digest": audit["source_ledger_digest"],
        "counts": audit["counts"],
        "core_semantic_digest": checkpoint_digest,
        "normalized_store_digest": normalized["store_digest"],
        "release_audit": _artifact_descriptor(audit_path),
        "claim_crosswalk_csv": _artifact_descriptor(
            audit_root / "claim_crosswalk.csv"
        ),
        "claim_crosswalk_json": _artifact_descriptor(
            audit_root / "claim_crosswalk.json"
        ),
        "core_snapshot": _artifact_descriptor(
            root / "sciengram_core/core_snapshot.sciengram/manifest.json"
        ),
        "compatibility_graph": _artifact_descriptor(
            root / "sciengram_0.10/cognifold_graph.json"
        ),
        "human_review": {
            "full_report": _artifact_descriptor(
                root / "human_review/critical_conflicts.json"
            ),
            "shortlist_csv": _artifact_descriptor(shortlist_csv),
            "shortlist_markdown": _artifact_descriptor(shortlist_markdown),
            "specification": _artifact_descriptor(conflict_specs_path),
        },
        "visualizations": {
            path.name: _artifact_descriptor(path)
            for path in (disposition_svg_path, quality_svg_path, conflict_svg_path)
        },
        "warnings": warnings,
    }
    release_path = output / "release_manifest.json"
    _write_json(release_manifest, release_path)
    _write_text(
        f"{_file_digest(release_path)}  {release_path.name}\n",
        output / "release_manifest.sha256",
    )

    print(
        json.dumps(
            {
                "valid": audit["valid"],
                "audit": str(audit_path),
                "release_manifest": str(release_path),
                "claims": len(rows),
                "core_belief_states": len(checkpoint["belief_states"]),
                "critical_conflicts": len(conflicts["conflicts"]),
                "warnings": warnings,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if audit["valid"] else 1


def _claim_crosswalk(root: Path, checkpoint: dict[str, Any]) -> list[dict[str, Any]]:
    graph = checkpoint["graph"]
    local_nodes = {
        (node["paper_id"], node["source_object_id"]): node
        for node in graph["nodes"]
        if node["kind"] == "paper_assertion"
    }
    canonical_nodes = {
        node["id"]: node
        for node in graph["nodes"]
        if node["kind"] == "canonical_claim"
    }
    alignments = {
        edge["source"]: edge
        for edge in graph["edges"]
        if edge["kind"] == "aligns_to"
    }
    observations = Counter(
        item["source_assertion_id"] for item in checkpoint["relation_ledger"]
    )
    belief_ids = {item["canonical_claim_id"] for item in checkpoint["belief_states"]}
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for path in sorted((root / "sciengram_export/crosswalks").glob("*.json")):
        crosswalk = _read_json(path)
        paper_id = crosswalk["paper_id"]
        packet = _read_json(root / f"sciengram_export/packets/{paper_id}.json")
        claims = {item["claim_id"]: item for item in packet["claims"]}
        for receipt in crosswalk["alignments"]:
            claim_id = receipt["claim_id"]
            key = (paper_id, claim_id)
            if key in seen:
                raise ValueError(f"duplicate exported claim key: {key!r}")
            seen.add(key)
            local = local_nodes.get(key)
            if local is None:
                raise ValueError(f"SciEngram local assertion missing for {key!r}")
            edge = alignments.get(local["id"])
            if edge is None:
                raise ValueError(f"SciEngram alignment edge missing for {key!r}")
            canonical = canonical_nodes.get(edge["target"])
            if canonical is None:
                raise ValueError(f"SciEngram canonical target missing for {key!r}")
            attributes = local["attributes"]
            if attributes["target_assertion_id"] != receipt["target_assertion_id"]:
                raise ValueError(f"Odracir assertion binding changed for {key!r}")
            if attributes["reconciliation_disposition"] != receipt["disposition"]:
                raise ValueError(f"reconciliation disposition changed for {key!r}")
            claim = claims[claim_id]
            rows.append(
                {
                    "paper_id": paper_id,
                    "claim_id": claim_id,
                    "claim_statement": claim["statement"],
                    "claim_polarity": claim["polarity"],
                    "packet_status": packet["admission_status"],
                    "packet_quality_score": packet["quality_score"],
                    "reconciliation_disposition": receipt["disposition"],
                    "reconciliation_effective_weight_ppm": receipt[
                        "effective_weight_ppm"
                    ],
                    "odracir_assertion_id": receipt["target_assertion_id"],
                    "sciengram_local_assertion_id": local["id"],
                    "sciengram_canonical_claim_id": canonical["id"],
                    "sciengram_canonical_statement": canonical["text"],
                    "sciengram_alignment_confidence": edge["confidence"],
                    "sciengram_relation_observation_count": observations[local["id"]],
                    "sciengram_has_belief_state": canonical["id"] in belief_ids,
                }
            )
    return sorted(rows, key=lambda row: (_paper_key(row["paper_id"]), row["claim_id"]))


def _write_crosswalk_csv(rows: list[dict[str, Any]], path: Path) -> None:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    _write_text(buffer.getvalue(), path)


def _write_conflict_shortlist(
    report: dict[str, Any],
    csv_path: Path,
    markdown_path: Path,
) -> None:
    resolution_hints = {
        "C1-norman-double-perturbation-baseline": (
            "Treat as conditioned_on(split, target, metric, baseline_family); "
            "do not select a global winner."
        ),
        "C2-replogle-single-perturbation-baseline": (
            "Treat as conditioned_on(split, preprocessing, evaluated_genes, "
            "metric, baseline_family)."
        ),
        "C3-generalization-winner-ranking": (
            "Treat as conditioned_on(task, dataset, split, cell_context, dose, "
            "metric, comparator_roster); do not encode a global winner."
        ),
    }
    fieldnames = [
        "conflict_id",
        "priority",
        "classification",
        "title",
        "side_a_paper_id",
        "side_a_claim_id",
        "side_a_packet_status",
        "side_a_quality_score",
        "side_a_assertion_id",
        "side_b_paper_id",
        "side_b_claim_id",
        "side_b_packet_status",
        "side_b_quality_score",
        "side_b_assertion_id",
        "review_question",
        "recommended_resolution",
    ]
    rows = []
    markdown = [
        "# Critical conflict shortlist",
        "",
        f"Only {len(report['conflicts'])} high-value candidate tensions are listed. ",
        "They are not ledger-declared unconditional contradictions.",
        "",
    ]
    for index, conflict in enumerate(report["conflicts"], start=1):
        left = conflict["side_a"]
        right = conflict["side_b"]
        hint = resolution_hints[conflict["conflict_id"]]
        rows.append(
            {
                "conflict_id": conflict["conflict_id"],
                "priority": conflict["priority"],
                "classification": conflict["classification"],
                "title": conflict["title"],
                "side_a_paper_id": left["selector"]["paper_id"],
                "side_a_claim_id": left["selector"]["claim_id"],
                "side_a_packet_status": left["packet_status"],
                "side_a_quality_score": left["packet_quality_score"],
                "side_a_assertion_id": left["assertion"]["assertion_id"],
                "side_b_paper_id": right["selector"]["paper_id"],
                "side_b_claim_id": right["selector"]["claim_id"],
                "side_b_packet_status": right["packet_status"],
                "side_b_quality_score": right["packet_quality_score"],
                "side_b_assertion_id": right["assertion"]["assertion_id"],
                "review_question": conflict["review_question"],
                "recommended_resolution": hint,
            }
        )
        markdown.extend(
            (
                f"## {index}. {conflict['title']}",
                "",
                f"- Pair: `{left['selector']['paper_id']}/{left['selector']['claim_id']}` "
                f"({left['packet_status']}, q={left['packet_quality_score']:.4f}) vs "
                f"`{right['selector']['paper_id']}/{right['selector']['claim_id']}` "
                f"({right['packet_status']}, q={right['packet_quality_score']:.4f})",
                f"- Classification: `{conflict['classification']}`",
                f"- Human decision: {conflict['review_question']}",
                f"- Recommended encoding: {hint}",
                "",
            )
        )
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    _write_text(buffer.getvalue(), csv_path)
    _write_text("\n".join(markdown).rstrip() + "\n", markdown_path)


def _disposition_svg(counts: Counter[str]) -> str:
    items = [
        ("Core accepted", counts["core_accepted"], "#167d5a"),
        ("Deferred", counts["deferred"], "#d89b24"),
        ("Excluded: incomplete chain", counts["excluded_invalid"], "#b94a48"),
    ]
    total = sum(value for _, value, _ in items)
    x0, width = 70, 960
    cursor = x0
    rects = []
    legend = []
    for index, (label, value, color) in enumerate(items):
        segment = width * value / total
        rects.append(
            f'<rect x="{cursor:.2f}" y="125" width="{segment:.2f}" height="72" '
            f'fill="{color}"/><text x="{cursor + segment / 2:.2f}" y="169" '
            f'text-anchor="middle" class="inside">{value}</text>'
        )
        legend.append(
            f'<rect x="{80 + index * 345}" y="245" width="18" height="18" '
            f'fill="{color}" rx="3"/><text x="{106 + index * 345}" y="259" '
            f'class="legend">{html.escape(label)} ({value}, {value / total:.1%})</text>'
        )
        cursor += segment
    return _svg_frame(
        1100,
        330,
        "Final reconciliation dispositions",
        f"{total} claims · accepted-only policy · provisional evidence remains auditable",
        "".join(rects + legend),
    )


def _quality_svg(
    rows: list[dict[str, str]], conflicts: dict[str, Any]
) -> str:
    conflict_papers = {
        item[side]["selector"]["paper_id"]
        for item in conflicts["conflicts"]
        for side in ("side_a", "side_b")
    }
    ordered = sorted(rows, key=lambda row: _paper_key(row["paper_id"]))
    body = []
    chart_x, chart_width = 185, 780
    for index, row in enumerate(ordered):
        y = 100 + index * 27
        score = float(row["quality_score"])
        color = "#167d5a" if row["packet_status"] == "accepted" else "#d89b24"
        bar_width = max(0.0, (score - 0.6) / 0.4 * chart_width)
        outline = "#b94a48" if row["paper_id"] in conflict_papers else "none"
        body.extend(
            (
                f'<text x="65" y="{y + 15}" class="axis">{html.escape(row["paper_id"])}</text>',
                f'<rect x="{chart_x}" y="{y}" width="{bar_width:.2f}" height="18" '
                f'fill="{color}" stroke="{outline}" stroke-width="3" rx="3"/>',
                f'<text x="{chart_x + bar_width + 8:.2f}" y="{y + 15}" '
                f'class="value">{score:.4f}</text>',
            )
        )
    for tick in (0.6, 0.7, 0.8, 0.9, 1.0):
        x = chart_x + (tick - 0.6) / 0.4 * chart_width
        body.append(
            f'<line x1="{x:.2f}" y1="88" x2="{x:.2f}" y2="620" '
            f'stroke="#dfe5e8"/><text x="{x:.2f}" y="646" text-anchor="middle" '
            f'class="axis">{tick:.1f}</text>'
        )
    body.append(
        '<text x="65" y="680" class="note">Green = accepted; amber = provisional; '
        'red outline = appears in critical conflict review.</text>'
    )
    return _svg_frame(
        1100,
        720,
        "Packet quality and admission status",
        "19 formal papers · quality is not equivalent to consensus admission",
        "".join(body),
    )


def _conflict_svg(conflicts: dict[str, Any]) -> str:
    body = []
    axes = [
        "split · metric · baseline family",
        "split · preprocessing · evaluated genes · baseline family",
        "task · dataset · cell context · comparator roster",
    ]
    for index, conflict in enumerate(conflicts["conflicts"]):
        y = 105 + index * 170
        left = conflict["side_a"]
        right = conflict["side_b"]
        body.extend(
            (
                f'<text x="55" y="{y}" class="rowtitle">{html.escape(conflict["conflict_id"])}</text>',
                f'<text x="55" y="{y + 25}" class="small">{html.escape(conflict["title"])}</text>',
                _conflict_box(55, y + 42, left),
                _conflict_box(760, y + 42, right),
                f'<line x1="390" y1="{y + 85}" x2="750" y2="{y + 85}" '
                'stroke="#b94a48" stroke-width="2" stroke-dasharray="7 5"/>',
                f'<text x="570" y="{y + 73}" text-anchor="middle" class="small">'
                f'{html.escape(conflict["classification"])}</text>',
                f'<text x="570" y="{y + 105}" text-anchor="middle" class="axis">'
                f'condition on: {html.escape(axes[index])}</text>',
            )
        )
    return _svg_frame(
        1100,
        650,
        "Critical scientific conflict review",
        "Three high-value pairs only · candidate tensions, not unconditional contradictions",
        "".join(body),
    )


def _conflict_box(x: int, y: int, side: dict[str, Any]) -> str:
    status = side["packet_status"]
    color = "#167d5a" if status == "accepted" else "#d89b24"
    label = f'{side["selector"]["paper_id"]} · {status} · q={side["packet_quality_score"]:.4f}'
    return (
        f'<rect x="{x}" y="{y}" width="335" height="86" fill="#ffffff" '
        f'stroke="{color}" stroke-width="3" rx="8"/>'
        f'<text x="{x + 16}" y="{y + 28}" class="boxhead">{html.escape(label)}</text>'
        f'<text x="{x + 16}" y="{y + 53}" class="small">'
        f'{html.escape(side["selector"]["claim_id"][:28])}</text>'
        f'<text x="{x + 16}" y="{y + 73}" class="axis">'
        f'{html.escape(side["assertion_status"])} · {side["evidence_weight_ppm"]} ppm</text>'
    )


def _svg_frame(width: int, height: int, title: str, subtitle: str, body: str) -> str:
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <rect width="100%" height="100%" fill="#f7f9f8"/>
  <style>
    text {{ font-family: Inter, "DejaVu Sans", sans-serif; fill: #203039; }}
    .title {{ font-size: 25px; font-weight: 700; }}
    .subtitle {{ font-size: 14px; fill: #607078; }}
    .inside {{ font-size: 22px; font-weight: 700; fill: #ffffff; }}
    .legend {{ font-size: 13px; }}
    .axis {{ font-size: 12px; fill: #607078; }}
    .value {{ font-size: 12px; font-weight: 600; }}
    .note {{ font-size: 13px; fill: #607078; }}
    .rowtitle {{ font-size: 15px; font-weight: 700; }}
    .boxhead {{ font-size: 13px; font-weight: 700; }}
    .small {{ font-size: 12px; }}
  </style>
  <text x="55" y="42" class="title">{html.escape(title)}</text>
  <text x="55" y="67" class="subtitle">{html.escape(subtitle)}</text>
  {body}
</svg>
'''


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected an object in {path}")
    return value


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _paper_key(paper_id: str) -> tuple[int, ...]:
    return tuple(int(part) for part in paper_id.split("_") if part.isdigit())


def _core_materialization_audit(root: Path) -> dict[str, Any]:
    try:
        from sciengram_core.normalized_store import load_normalized_checkpoint
        from sciengram_core.store import load_checkpoint, semantic_digest
    except ImportError as exc:
        raise RuntimeError(
            "run this audit with SciEngram_Core_v1/src on PYTHONPATH"
        ) from exc

    graph, ledger, states, _metadata = load_checkpoint(
        root / "sciengram_core/core_checkpoint.json"
    )
    checkpoint_problems = graph.validate()
    checkpoint_digest = semantic_digest(graph, ledger, states)
    normalized_graph, normalized_ledger, normalized_states, _normalized_metadata = (
        load_normalized_checkpoint(
            root / "sciengram_core/core_snapshot.sciengram"
        )
    )
    normalized_problems = normalized_graph.validate()
    normalized_digest = semantic_digest(
        normalized_graph,
        normalized_ledger,
        normalized_states,
    )
    return {
        "checkpoint_valid": not checkpoint_problems,
        "checkpoint_problems": checkpoint_problems,
        "checkpoint_semantic_digest": checkpoint_digest,
        "normalized_valid": not normalized_problems
        and normalized_digest == checkpoint_digest,
        "normalized_problems": normalized_problems,
        "normalized_semantic_digest": normalized_digest,
    }


def _validate_normalized_store(root: Path, manifest: dict[str, Any]) -> bool:
    payload = {key: value for key, value in manifest.items() if key != "store_digest"}
    manifest_digest = hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    if manifest.get("store_digest") != manifest_digest:
        return False
    for descriptor in manifest.get("files", {}).values():
        path = root / descriptor["path"]
        if not path.is_file() or path.stat().st_size != descriptor["bytes"]:
            return False
        if _file_digest(path).removeprefix("sha256:") != descriptor["sha256"]:
            return False
    return True


def _single_checksum_valid(checksum_path: Path, target_path: Path) -> bool:
    parts = checksum_path.read_text(encoding="utf-8").strip().split()
    if len(parts) != 2 or parts[1] != target_path.name:
        return False
    expected = parts[0]
    if not expected.startswith("sha256:"):
        expected = "sha256:" + expected
    return _file_digest(target_path) == expected


def _checksum_file_valid(checksum_path: Path, member_root: Path) -> bool:
    lines = checksum_path.read_text(encoding="utf-8").splitlines()
    if not lines:
        return False
    for line in lines:
        parts = line.split()
        if len(parts) != 2:
            return False
        expected, name = parts
        if not expected.startswith("sha256:"):
            expected = "sha256:" + expected
        path = member_root / name
        if not path.is_file() or _file_digest(path) != expected:
            return False
    return True


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def _artifact_descriptor(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve()),
        "bytes": path.stat().st_size,
        "sha256": _file_digest(path),
    }


def _write_json(payload: object, path: Path) -> None:
    _write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        path,
    )


def _write_text(content: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())
