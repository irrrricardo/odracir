#!/usr/bin/env python3
"""Materialize deterministic Stage 3 reconciliation and SciEngram inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Sequence

from pydantic import TypeAdapter


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from odracir.paper_study.assembly import load_corpus_assembly  # noqa: E402
from odracir.paper_study.conflict_review import (  # noqa: E402
    ConflictSpec,
    generate_critical_conflicts,
)
from odracir.paper_study.reconciliation import (  # noqa: E402
    load_reconciliation,
    reconcile_corpus,
    write_reconciliation,
)
from odracir.paper_study.sciengram_export import (  # noqa: E402
    export_sciengram_packets,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Derive the accepted-only core, export all source evidence as "
            "SciEngramPacket 0.1, and resolve an explicit human-review conflict set."
        )
    )
    parser.add_argument("--assembly-manifest", required=True)
    parser.add_argument("--conflict-specs", required=True)
    parser.add_argument("--output-folder", required=True)
    args = parser.parse_args(list(argv) if argv is not None else None)

    assembly_path = Path(args.assembly_manifest).expanduser().resolve()
    specs_path = Path(args.conflict_specs).expanduser().resolve()
    output_root = Path(args.output_folder).expanduser().resolve()
    if output_root.exists() and any(output_root.iterdir()):
        raise SystemExit(f"output folder must be empty: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)

    assembly = load_corpus_assembly(assembly_path)
    specs = TypeAdapter(list[ConflictSpec]).validate_json(
        specs_path.read_text(encoding="utf-8")
    )

    reconciliation = reconcile_corpus(assembly)
    reconciliation_paths = write_reconciliation(
        reconciliation,
        output_root / "odracir",
    )
    # Re-read from disk and re-bind every input digest before exporting it.
    verified_reconciliation = load_reconciliation(
        reconciliation_paths["manifest"],
        assembly=assembly,
    )
    sciengram_export = export_sciengram_packets(
        assembly,
        output_root / "sciengram_export",
        reconciliation=verified_reconciliation,
    )
    conflict_report, conflict_paths = generate_critical_conflicts(
        assembly,
        specs,
        output_root / "human_review",
    )

    evidence_counts = Counter(
        item.disposition
        for item in verified_reconciliation.decision_log.evidence_decisions
    )
    assertion_counts = Counter(
        item.disposition
        for item in verified_reconciliation.decision_log.assertion_decisions
    )
    manifest = {
        "schema_version": "stage3-finalization/1",
        "corpus_id": assembly.corpus_id,
        "source_assembly_manifest": str(assembly_path),
        "source_assembly_manifest_sha256": _file_digest(assembly_path),
        "source_ledger_revision": assembly.final_ledger.revision,
        "source_ledger_digest": assembly.final_ledger.digest(),
        "delivery_count": len(assembly.deliveries),
        "reconciliation": {
            "manifest": reconciliation_paths["manifest"],
            "manifest_sha256": _file_digest(Path(reconciliation_paths["manifest"])),
            "policy_digest": verified_reconciliation.policy.digest(),
            "core_snapshot_digest": verified_reconciliation.core_snapshot.digest(),
            "core_assertion_count": len(
                verified_reconciliation.core_snapshot.assertions
            ),
            "core_relation_count": len(verified_reconciliation.core_snapshot.relations),
            "evidence_disposition_counts": dict(sorted(evidence_counts.items())),
            "assertion_disposition_counts": dict(sorted(assertion_counts.items())),
        },
        "sciengram_export": {
            "manifest": sciengram_export.manifest_path,
            "manifest_sha256": _file_digest(Path(sciengram_export.manifest_path)),
            "packet_count": len(sciengram_export.packet_paths),
            "quality_report": sciengram_export.quality_report_path,
            "quality_report_sha256": _file_digest(
                Path(sciengram_export.quality_report_path)
            ),
        },
        "human_review": {
            "report_digest": conflict_report.report_digest,
            "critical_conflict_count": len(conflict_report.conflicts),
            "json": conflict_paths.json_path,
            "csv": conflict_paths.csv_path,
            "markdown": conflict_paths.markdown_path,
            "checksums": conflict_paths.checksum_path,
        },
    }
    manifest_path = output_root / "finalization_manifest.json"
    _write_json(manifest, manifest_path)
    checksum_path = output_root / "finalization_manifest.sha256"
    checksum_path.write_text(
        f"{_file_digest(manifest_path)}  {manifest_path.name}\n",
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "status": "completed",
                "output_root": str(output_root),
                "manifest": str(manifest_path),
                "ledger_digest": assembly.final_ledger.digest(),
                "core_assertions": len(
                    verified_reconciliation.core_snapshot.assertions
                ),
                "evidence_dispositions": dict(sorted(evidence_counts.items())),
                "sciengram_packets": len(sciengram_export.packet_paths),
                "critical_conflicts": len(conflict_report.conflicts),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def _file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(payload: object, path: Path) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
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
    temporary.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())
