"""Deterministic catalog of source-supported scientific figure evidence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from odracir.schemas import FIGURE_EVIDENCE_CATALOG_SCHEMA_VERSION
from odracir.time_utils import now_iso


ELIGIBLE_SUPPORT_LEVELS = {"direct_visual", "source_supported"}
MIN_EVIDENCE_CONFIDENCE = 0.7
DEFAULT_CATALOG_PATH = ".odracir/figure-evidence/catalog.json"


@dataclass(frozen=True)
class FigureEvidenceCatalogResult:
    root: str
    catalog_path: str
    analyzed_figures: int
    evidence_items: int
    excluded_items: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class FigureEvidenceCatalogBuilder:
    """Build a queryable catalog without promoting inference to evidence."""

    def __init__(
        self,
        root: str | Path,
        *,
        minimum_confidence: float = MIN_EVIDENCE_CONFIDENCE,
        require_consensus: bool = False,
    ) -> None:
        if not 0 <= minimum_confidence <= 1:
            raise ValueError("minimum_confidence must be between 0 and 1.")
        self.root = Path(root).expanduser().resolve()
        self.analysis_dir = self.root / ".odracir" / "figure-analyses"
        self.catalog_path = self.root / DEFAULT_CATALOG_PATH
        self.minimum_confidence = minimum_confidence
        self.require_consensus = require_consensus

    def build(self) -> FigureEvidenceCatalogResult:
        records: list[dict[str, Any]] = []
        excluded_items = 0
        analyzed_figures = 0
        source_artifacts: list[dict[str, str]] = []
        for path in sorted(self.analysis_dir.rglob("*.json")):
            artifact = _load_json(path)
            if artifact.get("status") != "completed":
                continue
            analysis = artifact.get("analysis")
            if not isinstance(analysis, dict):
                continue
            analyzed_figures += 1
            source_artifacts.append(
                {
                    "path": path.relative_to(self.root).as_posix(),
                    "sha256": _sha256_file(path),
                }
            )
            for ordinal, item in enumerate(analysis.get("evidence_items", []), start=1):
                if not isinstance(item, dict):
                    excluded_items += 1
                    continue
                if not _eligible_evidence_item(
                    item,
                    analysis,
                    minimum_confidence=self.minimum_confidence,
                    verification_mode=str(artifact.get("verification_mode", "unknown")),
                    require_consensus=self.require_consensus,
                ):
                    excluded_items += 1
                    continue
                records.append(
                    {
                        "evidence_id": f"{artifact['figure_id']}-e{ordinal:03d}",
                        "paper_id": artifact["paper_id"],
                        "figure_id": artifact["figure_id"],
                        "parent_figure_id": artifact.get("parent_figure_id"),
                        "subfigure_label": artifact.get("subfigure_label"),
                        "figure_type": analysis.get("figure_type"),
                        "scientific_question": analysis.get("scientific_question"),
                        "claim": item.get("claim"),
                        "support_level": item.get("support_level"),
                        "source": item.get("source"),
                        "evidence_detail": item.get("evidence_detail"),
                        "confidence": item.get("confidence"),
                        "verification_mode": artifact.get(
                            "verification_mode",
                            "unknown",
                        ),
                        "analysis_artifact": path.relative_to(self.root).as_posix(),
                        "image_path": artifact.get("analysis_image_path"),
                        "image_sha256": artifact.get("analysis_image_sha256"),
                    }
                )
        payload = {
            "schema_version": FIGURE_EVIDENCE_CATALOG_SCHEMA_VERSION,
            "generated_at": now_iso(),
            "input_sha256": _sha256_json(source_artifacts),
            "analyzed_figure_count": analyzed_figures,
            "evidence_item_count": len(records),
            "excluded_item_count": excluded_items,
            "eligible_support_levels": sorted(ELIGIBLE_SUPPORT_LEVELS),
            "minimum_confidence": self.minimum_confidence,
            "require_consensus": self.require_consensus,
            "records": records,
        }
        _write_json(self.catalog_path, payload)
        return FigureEvidenceCatalogResult(
            root=str(self.root),
            catalog_path=self.catalog_path.relative_to(self.root).as_posix(),
            analyzed_figures=analyzed_figures,
            evidence_items=len(records),
            excluded_items=excluded_items,
        )


def _eligible_evidence_item(
    item: dict[str, Any],
    analysis: dict[str, Any],
    *,
    minimum_confidence: float,
    verification_mode: str,
    require_consensus: bool,
) -> bool:
    support_level = item.get("support_level")
    source = item.get("source")
    confidence = item.get("confidence")
    if support_level not in ELIGIBLE_SUPPORT_LEVELS:
        return False
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        return False
    if float(confidence) < minimum_confidence:
        return False
    if require_consensus and verification_mode != "multi_model_consensus":
        return False
    if not isinstance(item.get("claim"), str) or not item["claim"].strip():
        return False
    if not isinstance(item.get("evidence_detail"), str) or not item["evidence_detail"].strip():
        return False
    if support_level == "direct_visual" and source not in {"image", "combined"}:
        return False
    if support_level == "source_supported":
        if source not in {"figure_text", "caption", "nearby_text", "combined"}:
            return False
        if analysis.get("text_image_consistency") == "conflicting":
            return False
    return True


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object.")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
        file.write("\n")
    temporary.replace(path)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_json(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
