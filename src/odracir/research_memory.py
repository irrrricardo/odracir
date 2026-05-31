"""Deterministic folder-level research memory built from audited local artifacts."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from odracir.research_folder import ResearchFolderHarness
from odracir.schemas import RESEARCH_CATALOG_SCHEMA_VERSION
from odracir.skills import ResearchSkillRegistry, get_builtin_skill_registry
from odracir.summary_evaluation import SummaryEvaluationHarness, SummaryEvaluationRecord
from odracir.time_utils import now_iso


DEFAULT_CATALOG_NAME = "research_catalog.json"


@dataclass(frozen=True)
class ResearchCatalogBuildResult:
    root: str
    index_path: str
    catalog_path: str | None
    cached: bool
    generated_at: str
    input_sha256: str
    total_papers: int
    quality_counts: dict[str, int]
    records: list[dict[str, Any]]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class ResearchCatalogBuilder:
    """Aggregate audited paper summaries into a visible folder-level catalog."""

    def __init__(
        self,
        root: str | Path,
        papers_dir: str | Path | None = None,
        *,
        skill_registry: ResearchSkillRegistry | None = None,
    ) -> None:
        self.harness = ResearchFolderHarness(root, papers_dir=papers_dir)
        self.root = self.harness.root
        self.catalog_path = self.root / DEFAULT_CATALOG_NAME
        self.skill_registry = skill_registry or get_builtin_skill_registry()

    def build(self, *, write_artifact: bool = True) -> ResearchCatalogBuildResult:
        index = self.harness.load_index()
        papers = [
            paper for paper in index.get("papers", []) if isinstance(paper, dict)
        ]
        evaluation = SummaryEvaluationHarness(
            self.root,
            papers_dir=self.harness.papers_dir,
            skill_registry=self.skill_registry,
        ).evaluate(write_artifact=False)
        evaluations = {record.paper_id: record for record in evaluation.records}
        input_sha256 = _input_sha256(
            self.root,
            self.harness.index_path,
            papers,
            evaluation_input_sha256=evaluation.input_sha256,
        )
        if write_artifact and self.catalog_path.is_file():
            artifact = _load_json(self.catalog_path)
            if _can_use_cached(artifact, input_sha256=input_sha256):
                return _result_from_artifact(
                    root=self.root,
                    index_path=self.harness.index_path,
                    catalog_path=self.catalog_path,
                    artifact=artifact,
                    cached=True,
                )

        records = [
            self._build_record(paper, evaluation=evaluations.get(str(paper.get("id", ""))))
            for paper in papers
        ]
        artifact = {
            "schema_version": RESEARCH_CATALOG_SCHEMA_VERSION,
            "generated_at": now_iso(),
            "input_sha256": input_sha256,
            "folder_name": str(index.get("folder_name", self.root.name)),
            "source_index": self.harness.index_path.name,
            "source_index_sha256": _optional_file_sha256(self.harness.index_path),
            "summary_evaluation_input_sha256": evaluation.input_sha256,
            "total_papers": len(records),
            "quality_counts": _quality_counts(records),
            "processing_counts": _processing_counts(records),
            "records": records,
        }
        if write_artifact:
            self.root.mkdir(parents=True, exist_ok=True)
            _write_json(self.catalog_path, artifact)
        return _result_from_artifact(
            root=self.root,
            index_path=self.harness.index_path,
            catalog_path=self.catalog_path if write_artifact else None,
            artifact=artifact,
            cached=False,
        )

    def _build_record(
        self,
        paper: dict[str, Any],
        *,
        evaluation: SummaryEvaluationRecord | None,
    ) -> dict[str, Any]:
        quality_status = _quality_status(paper, evaluation=evaluation)
        summary: dict[str, Any] | None = None
        summary_provenance: dict[str, Any] | None = None
        warnings = list(evaluation.warnings) if evaluation else []
        errors = list(evaluation.errors) if evaluation else []
        if quality_status in {"passed", "warning"} and evaluation:
            try:
                summary_artifact = _load_json(self.root / str(evaluation.summary_artifact))
                raw_summary = summary_artifact.get("summary")
                if not isinstance(raw_summary, dict):
                    raise ValueError("Summary artifact must contain a summary object.")
                summary = dict(raw_summary)
                summary_provenance = {
                    "artifact": evaluation.summary_artifact,
                    "artifact_sha256": _optional_file_sha256(
                        self.root / str(evaluation.summary_artifact)
                    ),
                    "provider": summary_artifact.get("provider"),
                    "model": summary_artifact.get("model"),
                    "prompt_version": summary_artifact.get("prompt_version"),
                    "skill": summary_artifact.get("skill"),
                    "summarized_at": summary_artifact.get("summarized_at"),
                }
            except Exception as exc:  # noqa: BLE001 - isolate one malformed artifact.
                quality_status = "failed"
                errors.append(str(exc))

        return {
            "paper_id": str(paper.get("id", "")),
            "title": str(paper.get("title", "")),
            "authors": _string_list(paper.get("authors")),
            "year": paper.get("year"),
            "source_file": str(paper.get("source_file", "")),
            "source_sha256": str(paper.get("sha256", "")),
            "file_type": str(paper.get("file_type", "")),
            "status": str(paper.get("status", "")),
            "processing": {
                "ocr": str(paper.get("ocr_status", "not_started")),
                "extraction": str(paper.get("text_extraction_status", "not_started")),
                "chunking": str(paper.get("chunking_status", "not_started")),
                "summary": str(paper.get("summary_status", "not_started")),
                "translation": str(paper.get("translation_status", "not_started")),
            },
            "artifacts": {
                "ocr": _optional_string(paper.get("ocr_artifact")),
                "text": _optional_string(paper.get("text_artifact")),
                "chunks": _optional_string(paper.get("chunk_artifact")),
                "summary": _optional_string(paper.get("summary_artifact")),
                "translation": _optional_string(paper.get("translation_artifact")),
            },
            "memory_quality": {
                "status": quality_status,
                "warnings": warnings,
                "errors": errors,
            },
            "summary": summary,
            "summary_provenance": summary_provenance,
            "notes": paper.get("notes", []),
        }


def format_research_catalog(result: ResearchCatalogBuildResult) -> str:
    lines = [
        f"Research folder: {result.root}",
        f"Index: {result.index_path}",
        (
            "Research memory: "
            f"{result.total_papers} papers, "
            f"cached={'yes' if result.cached else 'no'}, "
            f"{_format_counts(result.quality_counts)}"
        ),
    ]
    if result.catalog_path:
        lines.append(f"Catalog: {result.catalog_path}")
    else:
        lines.append("Read-only: research_catalog.json was not written.")
    for record in result.records:
        quality = record["memory_quality"]["status"]
        has_summary = "yes" if record["summary"] else "no"
        lines.append(f"- {record['paper_id']}: {quality}, summary={has_summary}")
    return "\n".join(lines)


def _quality_status(
    paper: dict[str, Any],
    *,
    evaluation: SummaryEvaluationRecord | None,
) -> str:
    if paper.get("status") == "missing":
        return "source_missing"
    if paper.get("file_type") != "pdf":
        return "unsupported_file_type"
    return evaluation.status if evaluation else "missing_summary"


def _quality_counts(records: list[dict[str, Any]]) -> dict[str, int]:
    return dict(
        sorted(Counter(record["memory_quality"]["status"] for record in records).items())
    )


def _processing_counts(records: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    stages = ("ocr", "extraction", "chunking", "summary", "translation")
    return {
        stage: dict(sorted(Counter(record["processing"][stage] for record in records).items()))
        for stage in stages
    }


def _input_sha256(
    root: Path,
    index_path: Path,
    papers: list[dict[str, Any]],
    *,
    evaluation_input_sha256: str,
) -> str:
    payload = {
        "schema_version": RESEARCH_CATALOG_SCHEMA_VERSION,
        "source_index_sha256": _optional_file_sha256(index_path),
        "summary_evaluation_input_sha256": evaluation_input_sha256,
        "artifacts": [
            {
                "paper_id": paper.get("id"),
                "summary_artifact": paper.get("summary_artifact"),
                "summary_artifact_sha256": _optional_file_sha256(
                    root / str(paper.get("summary_artifact") or "")
                ),
            }
            for paper in papers
        ],
    }
    return _sha256_json(payload)


def _can_use_cached(artifact: dict[str, Any], *, input_sha256: str) -> bool:
    return (
        artifact.get("schema_version") == RESEARCH_CATALOG_SCHEMA_VERSION
        and artifact.get("input_sha256") == input_sha256
        and isinstance(artifact.get("records"), list)
        and isinstance(artifact.get("quality_counts"), dict)
    )


def _result_from_artifact(
    *,
    root: Path,
    index_path: Path,
    catalog_path: Path | None,
    artifact: dict[str, Any],
    cached: bool,
) -> ResearchCatalogBuildResult:
    return ResearchCatalogBuildResult(
        root=str(root),
        index_path=str(index_path),
        catalog_path=str(catalog_path) if catalog_path else None,
        cached=cached,
        generated_at=str(artifact["generated_at"]),
        input_sha256=str(artifact["input_sha256"]),
        total_papers=int(artifact["total_papers"]),
        quality_counts={
            str(key): int(value) for key, value in dict(artifact["quality_counts"]).items()
        },
        records=[dict(record) for record in artifact["records"]],
    )


def _format_counts(counts: dict[str, int]) -> str:
    return ", ".join(f"{key}={value}" for key, value in sorted(counts.items())) or "none"


def _string_list(value: Any) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


def _optional_string(value: Any) -> str | None:
    return str(value) if isinstance(value, str) and value else None


def _optional_file_sha256(path: Path) -> str | None:
    return _sha256_file(path) if path.is_file() else None


def _sha256_json(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object.")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
        file.write("\n")
