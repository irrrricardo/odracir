"""Deterministic local quality audits for persisted summary artifacts."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from odracir.research_folder import ResearchFolderHarness
from odracir.schemas import SUMMARY_EVALUATION_SCHEMA_VERSION, SUMMARY_SCHEMA_VERSION
from odracir.skills import ResearchSkillManifest, ResearchSkillRegistry
from odracir.summarization import validate_summary
from odracir.time_utils import now_iso


@dataclass(frozen=True)
class SummaryEvaluationRecord:
    paper_id: str
    title: str
    status: str
    summary_artifact: str | None
    skill: str | None
    skill_version: str | None
    provider: str | None
    model: str | None
    metrics: dict[str, Any]
    warnings: list[str]
    errors: list[str]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SummaryEvaluationReport:
    root: str
    index_path: str
    artifact_path: str | None
    cached: bool
    generated_at: str
    input_sha256: str
    expected_skill: dict[str, Any] | None
    total_papers: int
    status_counts: dict[str, int]
    records: list[SummaryEvaluationRecord]

    def as_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "records": [record.as_dict() for record in self.records],
        }


class SummaryEvaluationHarness:
    """Audit summary artifacts without calling an LLM or mutating index state."""

    def __init__(
        self,
        root: str | Path,
        papers_dir: str | Path | None = None,
        *,
        skill_registry: ResearchSkillRegistry,
    ) -> None:
        self.harness = ResearchFolderHarness(root, papers_dir=papers_dir)
        self.root = self.harness.root
        self.skill_registry = skill_registry
        self.evaluations_dir = self.root / ".odracir" / "evaluations" / "summaries"

    def evaluate(
        self,
        *,
        paper_id: str | None = None,
        limit: int | None = None,
        expected_skill: ResearchSkillManifest | None = None,
        write_artifact: bool = True,
    ) -> SummaryEvaluationReport:
        if limit is not None and limit < 1:
            raise ValueError("Summary evaluation limit must be at least 1.")

        index = self.harness.load_index()
        papers = _select_papers(index, paper_id=paper_id, limit=limit)
        input_sha256 = _input_sha256(
            self.root,
            papers,
            expected_skill=expected_skill,
        )
        artifact_path = self.evaluations_dir / f"{input_sha256[:20]}.json"
        if write_artifact and artifact_path.is_file():
            artifact = _load_json(artifact_path)
            if _can_use_cached(artifact, input_sha256=input_sha256):
                return _report_from_artifact(
                    root=self.root,
                    index_path=self.harness.index_path,
                    artifact_path=artifact_path,
                    artifact=artifact,
                    cached=True,
                )

        records = [
            self._evaluate_paper(paper, expected_skill=expected_skill)
            for paper in papers
        ]
        generated_at = now_iso()
        artifact = {
            "schema_version": SUMMARY_EVALUATION_SCHEMA_VERSION,
            "generated_at": generated_at,
            "input_sha256": input_sha256,
            "expected_skill": expected_skill.as_dict() if expected_skill else None,
            "total_papers": len(records),
            "status_counts": _status_counts(records),
            "records": [record.as_dict() for record in records],
        }
        if write_artifact:
            self.evaluations_dir.mkdir(parents=True, exist_ok=True)
            _write_json(artifact_path, artifact)
        return _report_from_artifact(
            root=self.root,
            index_path=self.harness.index_path,
            artifact_path=artifact_path if write_artifact else None,
            artifact=artifact,
            cached=False,
        )

    def _evaluate_paper(
        self,
        paper: dict[str, Any],
        *,
        expected_skill: ResearchSkillManifest | None,
    ) -> SummaryEvaluationRecord:
        paper_id = str(paper.get("id", ""))
        title = str(paper.get("title", ""))
        summary_artifact_value = paper.get("summary_artifact")
        if paper.get("summary_status") != "summarized" or not summary_artifact_value:
            return SummaryEvaluationRecord(
                paper_id=paper_id,
                title=title,
                status="missing_summary",
                summary_artifact=None,
                skill=None,
                skill_version=None,
                provider=None,
                model=None,
                metrics={},
                warnings=[],
                errors=[],
            )

        summary_artifact = str(summary_artifact_value)
        artifact_path = self.root / summary_artifact
        errors: list[str] = []
        warnings: list[str] = []
        metrics: dict[str, Any] = {}
        artifact: dict[str, Any] = {}
        skill: ResearchSkillManifest | None = None

        try:
            artifact = _load_json(artifact_path)
        except Exception as exc:  # noqa: BLE001 - isolate one malformed artifact.
            errors.append(str(exc))

        if artifact:
            _validate_artifact_identity(
                artifact,
                paper=paper,
                artifact_path=artifact_path,
                root=self.root,
                errors=errors,
            )
            skill = self._resolve_skill(
                artifact,
                expected_skill=expected_skill,
                errors=errors,
            )
            summary = artifact.get("summary")
            chunk_artifact = self._load_current_chunk_artifact(
                artifact,
                paper=paper,
                errors=errors,
            )
            if isinstance(summary, dict) and chunk_artifact and skill:
                try:
                    citations = _allowed_citations(paper, chunk_artifact)
                    validate_summary(summary, citations, skill=skill)
                except Exception as exc:  # noqa: BLE001 - isolate malformed artifacts.
                    errors.append(str(exc))
                metrics = _summary_metrics(summary, skill=skill)
                warnings.extend(_summary_warnings(metrics, skill=skill))
            elif not isinstance(summary, dict):
                errors.append("Summary artifact must contain a summary object.")

        status = "failed" if errors else ("warning" if warnings else "passed")
        return SummaryEvaluationRecord(
            paper_id=paper_id,
            title=title,
            status=status,
            summary_artifact=summary_artifact,
            skill=_nested_string(artifact, "skill", "name"),
            skill_version=_nested_string(artifact, "skill", "version"),
            provider=_optional_string(artifact.get("provider")),
            model=_optional_string(artifact.get("model")),
            metrics=metrics,
            warnings=warnings,
            errors=errors,
        )

    def _resolve_skill(
        self,
        artifact: dict[str, Any],
        *,
        expected_skill: ResearchSkillManifest | None,
        errors: list[str],
    ) -> ResearchSkillManifest | None:
        skill_name = _nested_string(artifact, "skill", "name")
        skill_version = _nested_string(artifact, "skill", "version")
        if not skill_name or not skill_version:
            errors.append("Summary artifact must record skill name and version.")
            return None
        try:
            skill = self.skill_registry.get(skill_name)
        except ValueError as exc:
            errors.append(str(exc))
            return None
        if skill.version != skill_version:
            errors.append(
                f"Summary skill version is stale: artifact={skill_version}, "
                f"current={skill.version}."
            )
        if expected_skill and (
            skill.name != expected_skill.name or skill.version != expected_skill.version
        ):
            errors.append(
                f"Summary skill does not match expected {expected_skill.name}@"
                f"{expected_skill.version}: artifact={skill.name}@{skill.version}."
            )
        return skill

    def _load_current_chunk_artifact(
        self,
        artifact: dict[str, Any],
        *,
        paper: dict[str, Any],
        errors: list[str],
    ) -> dict[str, Any] | None:
        chunk_artifact_value = artifact.get("chunk_artifact")
        if not isinstance(chunk_artifact_value, str) or not chunk_artifact_value:
            errors.append("Summary artifact must record chunk_artifact.")
            return None
        if chunk_artifact_value != paper.get("chunk_artifact"):
            errors.append("Summary chunk_artifact does not match the current index.")
        chunk_artifact_path = self.root / chunk_artifact_value
        try:
            current_sha256 = _sha256_file(chunk_artifact_path)
            chunk_artifact = _load_json(chunk_artifact_path)
        except Exception as exc:  # noqa: BLE001 - report stale or missing inputs.
            errors.append(str(exc))
            return None
        if current_sha256 != artifact.get("chunk_artifact_sha256"):
            errors.append("Summary artifact is stale because chunk content changed.")
        return chunk_artifact


def format_summary_evaluation(report: SummaryEvaluationReport) -> str:
    lines = [
        f"Research folder: {report.root}",
        f"Index: {report.index_path}",
        (
            "Summary evaluation: "
            f"{report.total_papers} papers, "
            f"cached={'yes' if report.cached else 'no'}, "
            f"{_format_counts(report.status_counts)}"
        ),
    ]
    if report.expected_skill:
        lines.append(
            "Expected skill: "
            f"{report.expected_skill['name']}@{report.expected_skill['version']}"
        )
    if report.artifact_path:
        lines.append(f"Artifact: {report.artifact_path}")
    lines.append("Read-only: index and summary artifacts were not modified.")
    for record in report.records:
        skill = (
            f"{record.skill}@{record.skill_version}"
            if record.skill and record.skill_version
            else "none"
        )
        lines.append(f"- {record.paper_id}: {record.status}, skill={skill}")
        if record.metrics:
            lines.append(
                "  metrics: "
                f"findings={record.metrics.get('findings', 0)}, "
                f"citations={record.metrics.get('unique_citations', 0)}, "
                f"inferences={record.metrics.get('inferred_findings', 0)}, "
                f"limitations={record.metrics.get('limitations', 0)}"
            )
        for warning in record.warnings:
            lines.append(f"  warning: {warning}")
        for error in record.errors:
            lines.append(f"  error: {error}")
    return "\n".join(lines)


def _validate_artifact_identity(
    artifact: dict[str, Any],
    *,
    paper: dict[str, Any],
    artifact_path: Path,
    root: Path,
    errors: list[str],
) -> None:
    if artifact.get("schema_version") != SUMMARY_SCHEMA_VERSION:
        errors.append(
            f"Summary schema is stale: artifact={artifact.get('schema_version')}, "
            f"current={SUMMARY_SCHEMA_VERSION}."
        )
    if artifact.get("paper_id") != paper.get("id"):
        errors.append("Summary paper_id does not match the current index.")
    if artifact.get("source_sha256") != paper.get("sha256"):
        errors.append("Summary source_sha256 does not match the current PDF.")
    try:
        relative_path = artifact_path.relative_to(root).as_posix()
    except ValueError:
        relative_path = str(artifact_path)
    if relative_path != paper.get("summary_artifact"):
        errors.append("Summary artifact path does not match the current index.")


def _summary_metrics(
    summary: dict[str, Any],
    *,
    skill: ResearchSkillManifest,
) -> dict[str, Any]:
    raw_findings = summary.get("findings", [])
    findings = raw_findings if isinstance(raw_findings, list) else []
    raw_limitations = summary.get("limitations", [])
    limitations = raw_limitations if isinstance(raw_limitations, list) else []
    citation_values = {
        str(citation)
        for finding in findings
        if isinstance(finding, dict)
        for citation in (
            finding.get("citations", [])
            if isinstance(finding.get("citations", []), list)
            else []
        )
    }
    metrics: dict[str, Any] = {
        "findings": len(findings),
        "cited_findings": sum(
            bool(finding.get("citations"))
            for finding in findings
            if isinstance(finding, dict)
        ),
        "inferred_findings": sum(
            finding.get("inference") is True
            for finding in findings
            if isinstance(finding, dict)
        ),
        "unique_citations": len(citation_values),
        "limitations": len(limitations),
    }
    if skill.domain_namespace and skill.schema_extension:
        raw_extensions = summary.get("domain_extensions", {})
        extensions = raw_extensions if isinstance(raw_extensions, dict) else {}
        raw_extension = extensions.get(skill.domain_namespace, {})
        extension = raw_extension if isinstance(raw_extension, dict) else {}
        populated_fields = [
            field for field in skill.schema_extension if extension.get(field)
        ]
        metrics["domain_namespace"] = skill.domain_namespace
        metrics["domain_fields"] = len(skill.schema_extension)
        metrics["domain_populated_fields"] = len(populated_fields)
        metrics["domain_empty_fields"] = [
            field for field in skill.schema_extension if not extension.get(field)
        ]
        metrics["domain_items"] = sum(
            len(extension.get(field, []))
            for field in skill.schema_extension
            if isinstance(extension.get(field, []), list)
        )
    return metrics


def _summary_warnings(
    metrics: dict[str, Any],
    *,
    skill: ResearchSkillManifest,
) -> list[str]:
    warnings: list[str] = []
    if not metrics.get("findings"):
        warnings.append("Summary has no findings; review whether evidence was missed.")
    if not metrics.get("limitations"):
        warnings.append("Summary has no limitations; review the source manually.")
    if skill.domain_namespace and metrics.get("domain_empty_fields"):
        warnings.append(
            "Domain fields are empty and should be reviewed: "
            f"{', '.join(metrics['domain_empty_fields'])}."
        )
    return warnings


def _allowed_citations(
    paper: dict[str, Any],
    chunk_artifact: dict[str, Any],
) -> set[str]:
    chunks = chunk_artifact.get("chunks", [])
    if not isinstance(chunks, list):
        raise ValueError("Chunk artifact must contain a chunks list.")
    return {
        _citation(paper, chunk)
        for chunk in chunks
        if isinstance(chunk, dict) and chunk.get("id")
    }


def _citation(paper: dict[str, Any], chunk: dict[str, Any]) -> str:
    page_start = int(chunk.get("page_start", 0))
    page_end = int(chunk.get("page_end", page_start))
    pages = str(page_start) if page_start == page_end else f"{page_start}-{page_end}"
    return f"[{paper['id']} pp.{pages} chunk:{chunk.get('id', '')}]"


def _select_papers(
    index: dict[str, Any],
    *,
    paper_id: str | None,
    limit: int | None,
) -> list[dict[str, Any]]:
    papers = [
        paper
        for paper in index.get("papers", [])
        if isinstance(paper, dict)
        and paper.get("file_type") == "pdf"
        and paper.get("status") != "missing"
        and (paper_id is None or paper.get("id") == paper_id)
    ]
    return papers[:limit] if limit is not None else papers


def _input_sha256(
    root: Path,
    papers: list[dict[str, Any]],
    *,
    expected_skill: ResearchSkillManifest | None,
) -> str:
    payload = {
        "schema_version": SUMMARY_EVALUATION_SCHEMA_VERSION,
        "expected_skill": expected_skill.as_dict() if expected_skill else None,
        "papers": [
            {
                "id": paper.get("id"),
                "sha256": paper.get("sha256"),
                "chunk_artifact": paper.get("chunk_artifact"),
                "chunk_artifact_sha256": _optional_file_sha256(
                    root / str(paper.get("chunk_artifact") or "")
                ),
                "summary_status": paper.get("summary_status"),
                "summary_artifact": paper.get("summary_artifact"),
                "summary_artifact_sha256": _optional_file_sha256(
                    root / str(paper.get("summary_artifact") or "")
                ),
            }
            for paper in papers
        ],
    }
    return _sha256_json(payload)


def _status_counts(records: list[SummaryEvaluationRecord]) -> dict[str, int]:
    return dict(sorted(Counter(record.status for record in records).items()))


def _format_counts(counts: dict[str, int]) -> str:
    return ", ".join(f"{key}={value}" for key, value in sorted(counts.items())) or "none"


def _can_use_cached(artifact: dict[str, Any], *, input_sha256: str) -> bool:
    return (
        artifact.get("schema_version") == SUMMARY_EVALUATION_SCHEMA_VERSION
        and artifact.get("input_sha256") == input_sha256
        and isinstance(artifact.get("records"), list)
        and isinstance(artifact.get("status_counts"), dict)
    )


def _report_from_artifact(
    *,
    root: Path,
    index_path: Path,
    artifact_path: Path | None,
    artifact: dict[str, Any],
    cached: bool,
) -> SummaryEvaluationReport:
    return SummaryEvaluationReport(
        root=str(root),
        index_path=str(index_path),
        artifact_path=(
            artifact_path.relative_to(root).as_posix() if artifact_path else None
        ),
        cached=cached,
        generated_at=str(artifact["generated_at"]),
        input_sha256=str(artifact["input_sha256"]),
        expected_skill=(
            dict(artifact["expected_skill"]) if artifact.get("expected_skill") else None
        ),
        total_papers=int(artifact["total_papers"]),
        status_counts={
            str(key): int(value)
            for key, value in dict(artifact["status_counts"]).items()
        },
        records=[
            SummaryEvaluationRecord(**record) for record in artifact["records"]
        ],
    )


def _nested_string(payload: dict[str, Any], key: str, nested_key: str) -> str | None:
    nested = payload.get(key)
    if not isinstance(nested, dict):
        return None
    return _optional_string(nested.get(nested_key))


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
