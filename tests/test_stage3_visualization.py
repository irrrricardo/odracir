from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest


def _load_visualizer() -> ModuleType:
    path = Path(__file__).parents[1] / "scripts/visualize_stage3_run.py"
    spec = importlib.util.spec_from_file_location("visualize_stage3_run", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VISUALIZER = _load_visualizer()
VisualizationError = VISUALIZER.VisualizationError
generate_visualizations = VISUALIZER.generate_visualizations
main = VISUALIZER.main


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _digest(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _completed_run(root: Path) -> None:
    profiles = [
        {
            "paper_id": "paper-a",
            "metadata_features": {"title": "Seed paper", "year": 2021},
            "domain": "experimental",
            "logic_mode": "causal",
            "chunk_count": 4,
            "page_start": 1,
            "page_end": 12,
            "total_char_count": 1000,
            "total_token_estimate": 250,
            "experimental_systems": ["primary_cells"],
            "methods": ["rna_sequencing"],
            "causal_rungs": ["intervention"],
            "conflict_signals": [],
            "conflict_score": 0.0,
            "quality_proxy": 0.9,
            "profile_digest": "sha256:" + "a" * 64,
        },
        {
            "paper_id": "paper-b",
            "metadata_features": {"title": "Conflict paper", "year": 2023},
            "domain": "experimental",
            "logic_mode": "causal",
            "chunk_count": 3,
            "page_start": 1,
            "page_end": 9,
            "total_char_count": 800,
            "total_token_estimate": 200,
            "experimental_systems": ["cell_line"],
            "methods": ["crispr"],
            "causal_rungs": ["intervention"],
            "conflict_signals": ["however"],
            "conflict_score": 0.25,
            "quality_proxy": 0.8,
            "profile_digest": "sha256:" + "b" * 64,
        },
    ]
    clusters = [
        {
            "cluster_id": "pc_aaaaaaaaaaaaaaaaaaaaaaaa",
            "member_paper_ids": ["paper-a"],
        },
        {
            "cluster_id": "pc_bbbbbbbbbbbbbbbbbbbbbbbb",
            "member_paper_ids": ["paper-b"],
        },
    ]
    _write_json(
        root / "recon/corpus_manifest.json",
        {"manifest_digest": "sha256:" + "1" * 64, "profiles": profiles, "clusters": clusters},
    )
    _write_json(
        root / "scheduler/strategic_batch_plan.json",
        {
            "batch_size": 1,
            "seed_paper_ids": ["paper-a"],
            "assignments": [
                {
                    "paper_id": "paper-a",
                    "batch_number": 1,
                    "position_in_batch": 1,
                    "role": "seed_medoid",
                    "anchor_paper_id": "paper-a",
                    "skeleton_similarity_ppm": 1_000_000,
                    "conflict_signal_overlap": 0,
                },
                {
                    "paper_id": "paper-b",
                    "batch_number": 2,
                    "position_in_batch": 1,
                    "role": "conflict_interleave",
                    "anchor_paper_id": "paper-a",
                    "skeleton_similarity_ppm": 700_000,
                    "conflict_signal_overlap": 1,
                },
            ],
        },
    )
    _write_json(
        root / "run_manifest.json",
        {
            "papers": [
                {
                    "paper_id": "paper-a",
                    "batch_number": 1,
                    "position_in_batch": 1,
                    "status": "succeeded",
                    "quality_score": 0.93,
                    "quality_passed": True,
                    "warning_codes": [],
                },
                {
                    "paper_id": "paper-b",
                    "batch_number": 2,
                    "position_in_batch": 1,
                    "status": "failed",
                    "quality_score": None,
                    "quality_passed": None,
                    "failed_stage": "extraction",
                    "error_type": "RuntimeError",
                    "error_message": "provider unavailable",
                },
            ],
            "batches": [
                {
                    "batch_number": 1,
                    "succeeded": 1,
                    "failed": 0,
                    "extracted_finding_count": 2,
                },
                {
                    "batch_number": 2,
                    "succeeded": 0,
                    "failed": 1,
                    "extracted_finding_count": 0,
                },
            ],
        },
    )
    assertions = [
        {
            "assertion_id": "assertion-a",
            "preferred_statement": "Perturbation increases <response>.",
            "status": "supported",
        },
        {
            "assertion_id": "assertion-b",
            "preferred_statement": "Perturbation decreases response.",
            "status": "contested",
        },
    ]
    relations = [
        {
            "relation_id": "relation-1",
            "source_assertion_id": "assertion-a",
            "target_assertion_id": "assertion-b",
            "relation_type": "contradicts",
            "score_ppm": 960_000,
        }
    ]
    _write_json(
        root / "ledger/global_state_ledger.json",
        {"revision": 2, "assertions": assertions, "relations": relations},
    )
    _write_json(
        root / "assembly_manifest.json",
        {
            "final_revision": 2,
            "ledger_path": "ledger/global_state_ledger.json",
        },
    )


def _recovered_run(root: Path) -> Path:
    _completed_run(root)
    run_path = root / "run_manifest.json"
    run = json.loads(run_path.read_text(encoding="utf-8"))
    run["papers"] = [
        {
            "paper_id": "paper-a",
            "batch_number": 1,
            "position_in_batch": 1,
            "status": "succeeded",
            "quality_score": None,
            "quality_passed": True,
            "packet_status": None,
            "requires_reconciliation": None,
            "warning_codes": [],
        },
        {
            "paper_id": "paper-b",
            "batch_number": 8,
            "position_in_batch": 1,
            "status": "succeeded",
            "quality_score": None,
            "quality_passed": True,
            "packet_status": None,
            "requires_reconciliation": None,
            "warning_codes": [],
        },
    ]
    run["batches"] = [
        {
            "batch_number": batch,
            "succeeded": 1 if batch in {1, 8} else 0,
            "failed": 0,
            "extracted_finding_count": 1 if batch in {1, 8} else 0,
        }
        for batch in range(1, 9)
    ]

    assertions = [
        {
            "assertion_id": "assertion-a",
            "preferred_statement": "Perturbation increases response.",
            "status": "supported",
            "evidence": [
                {"admission_status": "accepted", "weight_ppm": 1_000_000}
            ],
        },
        {
            "assertion_id": "assertion-b",
            "preferred_statement": "Perturbation decreases response.",
            "status": "unresolved",
            "evidence": [
                {"admission_status": "provisional", "weight_ppm": 350_000}
            ],
        },
    ]
    relations = [
        {
            "relation_id": "relation-1",
            "source_assertion_id": "assertion-a",
            "target_assertion_id": "assertion-b",
            "relation_type": "conditioned_on",
            "score_ppm": 700_000,
        }
    ]
    snapshot_paths = []
    previous: dict[str, object] | None = None
    events: list[dict[str, object]] = []
    final_ledger: dict[str, object] | None = None
    for revision in range(9):
        if revision:
            events = [
                *events,
                {
                    "event_type": "batch_committed",
                    "revision": revision,
                    "subject_id": f"batch:{revision}",
                },
            ]
        snapshot: dict[str, object] = {
            "revision": revision,
            "parent_digest": None if previous is None else _digest(previous),
            "assertions": assertions if revision == 8 else [],
            "relations": relations if revision == 8 else [],
            "events": events,
        }
        path = root / "ledger" / "snapshots" / f"revision-{revision:04d}.json"
        _write_json(path, snapshot)
        snapshot_paths.append(str(path.relative_to(root)))
        previous = snapshot
        final_ledger = snapshot
    assert final_ledger is not None
    ledger_path = root / "ledger" / "global_state_ledger.json"
    _write_json(ledger_path, final_ledger)
    final_digest = _digest(final_ledger)

    delivery_paths = {}
    packet_specs = {
        "paper-a": ("accepted", False, 0.93, 1_000_000, "exact"),
        "paper-b": ("provisional", True, 0.71, 350_000, "new_assertion"),
    }
    for paper_id, (
        status,
        requires_reconciliation,
        quality_score,
        score_ppm,
        relation_type,
    ) in packet_specs.items():
        packet = {
            "paper_id": paper_id,
            "status": status,
            "requires_reconciliation": requires_reconciliation,
            "quality_score": quality_score,
        }
        delivery = {
            "packet": packet,
            "packet_digest": _digest(packet),
            "alignments": [
                {
                    "alignment_id": f"alignment-{paper_id}",
                    "relation_type": relation_type,
                    "score_ppm": score_ppm,
                    "output_ledger_digest": final_digest,
                }
            ],
        }
        relative = (
            Path("deliveries") / f"{paper_id}.json"
            if paper_id == "paper-a"
            else Path("recovery") / "deliveries" / f"{paper_id}.json"
        )
        _write_json(root / relative, delivery)
        delivery_paths[paper_id] = str(relative)

    assembly = {
        "final_revision": 8,
        "final_ledger_digest": final_digest,
        "ledger_path": str(ledger_path.relative_to(root)),
        "snapshot_paths": snapshot_paths,
        "delivery_paths": delivery_paths,
    }
    run["delivery_paths"] = delivery_paths
    run["corpus_manifest_path"] = str(
        (root / "recon" / "corpus_manifest.json").resolve()
    )
    run["strategic_batch_plan_path"] = str(
        (root / "scheduler" / "strategic_batch_plan.json").resolve()
    )
    run["assembly_manifest_path"] = str(
        (root / "assembly_manifest.json").resolve()
    )
    _write_json(run_path, run)
    _write_json(root / "assembly_manifest.json", assembly)
    recovery_path = root / "recovery" / "recovery_manifest.json"
    _write_json(
        recovery_path,
        {
            "status": "completed",
            "recovery_batch_number": 8,
            "attempted_paper_ids": ["paper-b"],
            "succeeded_paper_ids": ["paper-b"],
            "failed_paper_ids": [],
        },
    )
    return recovery_path


def test_generate_visualizations_writes_complete_programmatic_outputs(tmp_path: Path) -> None:
    root = tmp_path / "run"
    _completed_run(root)

    paths = generate_visualizations(root)

    assert set(paths) == {
        "batches_csv",
        "cluster_batch_map_svg",
        "ledger_relations_svg",
        "paper_profiles_csv",
        "quality_csv",
        "quality_scores_svg",
        "relations_csv",
        "summary_json",
    }
    assert all(Path(path).is_file() for path in paths.values())
    summary = json.loads(Path(paths["summary_json"]).read_text(encoding="utf-8"))
    assert summary["corpus"] == {
        "actual_batch_numbers": [1, 2],
        "batch_count": 2,
        "cluster_count": 2,
        "deduplicated_input_count": 0,
        "duplicate_group_count": 0,
        "execution_moved_count": 0,
        "max_batch_number": 2,
        "paper_count": 2,
        "planned_batch_count": 2,
        "seed_count": 1,
    }
    assert summary["run"]["succeeded"] == 1
    assert summary["run"]["failed"] == 1
    assert summary["run"]["quality_score_mean"] == 0.93
    assert summary["ledger"]["assertion_count"] == 2
    assert summary["ledger"]["relation_types"] == {"contradicts": 1}
    assert summary["deliveries"]["expected_count"] == 1
    assert summary["deliveries"]["missing_paper_ids"] == ["paper-a"]
    assert summary["recovery"] == {"present": False}
    with Path(paths["relations_csv"]).open(encoding="utf-8", newline="") as handle:
        relation_rows = list(csv.DictReader(handle))
    assert relation_rows[0]["source_statement"] == "Perturbation increases <response>."
    assert relation_rows[0]["score"] == "0.96"
    ledger_svg = Path(paths["ledger_relations_svg"]).read_text(encoding="utf-8")
    assert "&lt;response&gt;" in ledger_svg
    assert "contradicts" in ledger_svg
    assert Path(paths["cluster_batch_map_svg"]).read_text(encoding="utf-8").startswith(
        '<?xml version="1.0"'
    )


def test_recovery_uses_actual_batches_and_audits_deliveries_and_snapshots(
    tmp_path: Path,
) -> None:
    root = tmp_path / "recovered-run"
    recovery_path = _recovered_run(root)

    paths = generate_visualizations(root)
    summary = json.loads(Path(paths["summary_json"]).read_text(encoding="utf-8"))

    assert summary["corpus"]["batch_count"] == 8
    assert summary["corpus"]["actual_batch_numbers"] == list(range(1, 9))
    assert summary["corpus"]["planned_batch_count"] == 2
    assert summary["corpus"]["execution_moved_count"] == 1
    assert summary["ledger"]["revision"] == 8
    assert summary["ledger"]["revision_matches_run_batches"] is True
    assert summary["ledger"]["declared_digest_matches"] is True
    assert summary["ledger"]["snapshot_chain"]["chain_ok"] is True
    assert summary["ledger"]["snapshot_chain"]["revisions"] == list(range(9))
    assert summary["ledger"]["evidence_weights"] == {
        "admission_statuses": {"accepted": 1, "provisional": 1},
        "evidence_count": 2,
        "provisional_only_assertion_count": 1,
        "weight_ppm_histogram": {"1000000": 1, "350000": 1},
        "weight_violation_count": 0,
        "weight_violations": [],
    }
    assert summary["run"]["accepted_packets"] == 1
    assert summary["run"]["provisional_packets"] == 1
    assert summary["run"]["quality_score_mean"] == 0.82
    assert summary["deliveries"]["expected_count"] == 2
    assert summary["deliveries"]["found_count"] == 2
    assert summary["deliveries"]["valid_count"] == 2
    assert summary["deliveries"]["missing_count"] == 0
    assert summary["deliveries"]["invalid_count"] == 0
    assert summary["deliveries"]["alignment_relation_types"] == {
        "exact": 1,
        "new_assertion": 1,
    }
    assert summary["deliveries"]["alignment_score_ppm"]["histogram"] == {
        "1000000": 1,
        "350000": 1,
    }
    assert summary["deliveries"]["output_ledger_digest_mismatch_count"] == 0
    assert summary["recovery"]["present"] is True
    assert summary["recovery"]["manifest_path"] == str(recovery_path.resolve())
    assert summary["recovery"]["status"] == "completed"
    assert summary["recovery"]["recovery_batch_number"] == 8
    assert summary["recovery"]["recovery_batch_matches_final_revision"] is True

    with Path(paths["batches_csv"]).open(encoding="utf-8", newline="") as handle:
        batch_rows = {row["paper_id"]: row for row in csv.DictReader(handle)}
    assert batch_rows["paper-b"]["batch_number"] == "8"
    assert batch_rows["paper-b"]["position_in_batch"] == "1"
    assert batch_rows["paper-b"]["planned_batch_number"] == "2"
    assert batch_rows["paper-b"]["planned_position_in_batch"] == "1"
    assert batch_rows["paper-b"]["execution_moved"] == "true"
    cluster_svg = Path(paths["cluster_batch_map_svg"]).read_text(encoding="utf-8")
    assert "Batch 8" in cluster_svg

    with Path(paths["quality_csv"]).open(encoding="utf-8", newline="") as handle:
        quality_rows = {row["paper_id"]: row for row in csv.DictReader(handle)}
    assert quality_rows["paper-a"]["packet_status"] == "accepted"
    assert quality_rows["paper-a"]["quality_score"] == "0.93"
    assert quality_rows["paper-b"]["packet_status"] == "provisional"
    assert quality_rows["paper-b"]["quality_score"] == "0.71"

    _write_json(root / "recovery" / "deliveries" / "paper-b.json", {"broken": True})
    invalid_paths = generate_visualizations(root, root / "visualizations-invalid")
    invalid_summary = json.loads(
        Path(invalid_paths["summary_json"]).read_text(encoding="utf-8")
    )
    assert invalid_summary["deliveries"]["found_count"] == 2
    assert invalid_summary["deliveries"]["valid_count"] == 1
    assert invalid_summary["deliveries"]["invalid_count"] == 1
    assert "paper-b" in invalid_summary["deliveries"]["invalid"]


def test_recovered_view_resolves_static_manifests_from_run_pointers(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "original-run"
    source_recovery = _recovered_run(source_root)
    recovered_root = tmp_path / "recovered-view"
    recovered_root.mkdir()
    _write_json(
        recovered_root / "run_manifest.json",
        json.loads((source_root / "run_manifest.json").read_text(encoding="utf-8")),
    )
    _write_json(
        recovered_root / "recovery_manifest.json",
        json.loads(source_recovery.read_text(encoding="utf-8")),
    )
    assert not (recovered_root / "recon" / "corpus_manifest.json").exists()
    assert not (
        recovered_root / "scheduler" / "strategic_batch_plan.json"
    ).exists()
    assert not (recovered_root / "assembly_manifest.json").exists()

    paths = generate_visualizations(recovered_root)
    summary = json.loads(Path(paths["summary_json"]).read_text(encoding="utf-8"))

    assert summary["source_paths"]["corpus_manifest"] == str(
        (source_root / "recon" / "corpus_manifest.json").resolve()
    )
    assert summary["source_paths"]["strategic_batch_plan"] == str(
        (source_root / "scheduler" / "strategic_batch_plan.json").resolve()
    )
    assert summary["source_paths"]["assembly_manifest"] == str(
        (source_root / "assembly_manifest.json").resolve()
    )
    assert summary["corpus"]["batch_count"] == 8
    assert summary["deliveries"]["valid_count"] == 2
    assert summary["ledger"]["snapshot_chain"]["chain_ok"] is True
    assert summary["recovery"]["present"] is True


def test_generate_visualizations_fails_clearly_without_results(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "empty-run"
    root.mkdir()

    with pytest.raises(VisualizationError, match="Missing run_manifest"):
        generate_visualizations(root)

    assert main([str(root)]) == 2
    assert "Missing run_manifest" in capsys.readouterr().err
