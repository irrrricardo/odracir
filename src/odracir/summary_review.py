"""Human-review workflow for persisted paper summaries."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from odracir.research_folder import ResearchFolderHarness
from odracir.schemas import SUMMARY_REVIEW_SCHEMA_VERSION
from odracir.skills import ResearchSkillManifest, ResearchSkillRegistry
from odracir.summary_evaluation import SummaryEvaluationHarness
from odracir.time_utils import now_iso


SUMMARY_REVIEW_POLICY_VERSION = "0.1"
SUMMARY_REVIEW_DECISIONS = ("accepted", "needs_revision")


@dataclass(frozen=True)
class SummaryEvidenceSnippet:
    citation: str
    chunk_id: str
    page_start: int
    page_end: int
    section_hint: str
    snippet: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SummaryReviewReport:
    root: str
    index_path: str
    paper_id: str
    title: str
    summary_artifact: str
    summary_artifact_sha256: str
    evaluation_status: str
    evaluation_metrics: dict[str, Any]
    evaluation_warnings: list[str]
    evaluation_errors: list[str]
    review_status: str
    review_artifact: str | None
    review: dict[str, Any] | None
    review_error: str | None
    provenance: dict[str, Any]
    summary: dict[str, Any]
    evidence: list[SummaryEvidenceSnippet]

    def as_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "evidence": [item.as_dict() for item in self.evidence],
        }


class SummaryReviewHarness:
    """Inspect one summary and persist explicit human review decisions."""

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

    def inspect(
        self,
        paper_id: str,
        *,
        expected_skill: ResearchSkillManifest | None = None,
        snippet_chars: int = 500,
    ) -> SummaryReviewReport:
        if snippet_chars < 80:
            raise ValueError("Summary review snippet_chars must be at least 80.")
        paper = _find_paper(self.harness.load_index(), paper_id)
        summary_artifact = _required_string(
            paper.get("summary_artifact"),
            f"Paper {paper_id} does not have a persisted summary artifact.",
        )
        summary_path = self.root / summary_artifact
        artifact = _load_json(summary_path)
        summary = artifact.get("summary")
        if not isinstance(summary, dict):
            raise ValueError("Summary artifact must contain a summary object.")
        evaluation = SummaryEvaluationHarness(
            self.root,
            papers_dir=self.harness.papers_dir,
            skill_registry=self.skill_registry,
        ).evaluate(
            paper_id=paper_id,
            expected_skill=expected_skill,
            write_artifact=False,
        )
        if len(evaluation.records) != 1:
            raise ValueError(f"Paper not found in summary evaluation: {paper_id}")
        evaluation_record = evaluation.records[0]
        chunk_artifact_path = self.root / _required_string(
            artifact.get("chunk_artifact"),
            "Summary artifact must record chunk_artifact.",
        )
        chunk_artifact = _load_json(chunk_artifact_path)
        chunks = chunk_artifact.get("chunks")
        if not isinstance(chunks, list):
            raise ValueError("Chunk artifact must contain a chunks list.")
        summary_sha256 = _sha256_file(summary_path)
        review_state = load_persisted_summary_review(self.root, paper)
        return SummaryReviewReport(
            root=str(self.root),
            index_path=str(self.harness.index_path),
            paper_id=paper_id,
            title=str(paper.get("title", "")),
            summary_artifact=summary_artifact,
            summary_artifact_sha256=summary_sha256,
            evaluation_status=evaluation_record.status,
            evaluation_metrics=evaluation_record.metrics,
            evaluation_warnings=evaluation_record.warnings,
            evaluation_errors=evaluation_record.errors,
            review_status=str(review_state["status"]),
            review_artifact=_optional_string(review_state.get("artifact")),
            review=(
                dict(review_state["review"])
                if isinstance(review_state.get("review"), dict)
                else None
            ),
            review_error=_optional_string(review_state.get("error")),
            provenance=_provenance(artifact),
            summary=dict(summary),
            evidence=_evidence_snippets(
                summary,
                paper=paper,
                chunks=chunks,
                snippet_chars=snippet_chars,
            ),
        )

    def record(
        self,
        paper_id: str,
        *,
        decision: str,
        note: str = "",
        reviewer: str = "local-user",
        expected_skill: ResearchSkillManifest | None = None,
        snippet_chars: int = 500,
    ) -> SummaryReviewReport:
        decision = decision.strip().replace("-", "_")
        if decision not in SUMMARY_REVIEW_DECISIONS:
            raise ValueError(
                "Summary review decision must be accepted or needs_revision."
            )
        note = note.strip()
        if decision == "needs_revision" and not note:
            raise ValueError("needs_revision summary reviews require a note.")
        reviewer = reviewer.strip()
        if not reviewer:
            raise ValueError("Summary review reviewer must not be empty.")
        current = self.inspect(
            paper_id,
            expected_skill=expected_skill,
            snippet_chars=snippet_chars,
        )
        if current.evaluation_status == "failed":
            raise ValueError(
                "Cannot record a human review for a summary that failed deterministic audit."
            )
        reviewed_at = now_iso()
        review_id = _review_id(reviewed_at)
        artifact = {
            "schema_version": SUMMARY_REVIEW_SCHEMA_VERSION,
            "policy_version": SUMMARY_REVIEW_POLICY_VERSION,
            "review_id": review_id,
            "paper_id": paper_id,
            "summary_artifact": current.summary_artifact,
            "summary_artifact_sha256": current.summary_artifact_sha256,
            "decision": decision,
            "reviewer": reviewer,
            "note": note,
            "reviewed_at": reviewed_at,
            "evaluation_status": current.evaluation_status,
            "evaluation_metrics": current.evaluation_metrics,
            "evaluation_warnings": current.evaluation_warnings,
        }
        review_dir = _review_dir(self.root, paper_id)
        _write_json_atomic(review_dir / f"{review_id}.json", artifact)
        _write_json_atomic(review_dir / "latest.json", artifact)
        return self.inspect(
            paper_id,
            expected_skill=expected_skill,
            snippet_chars=snippet_chars,
        )


def load_persisted_summary_review(
    root: str | Path,
    paper: dict[str, Any],
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    paper_id = str(paper.get("id", ""))
    latest_path = _review_dir(root_path, paper_id) / "latest.json"
    if not latest_path.is_file():
        return {"status": "unreviewed", "artifact": None, "review": None}
    relative_path = latest_path.relative_to(root_path).as_posix()
    try:
        review = _load_json(latest_path)
        if review.get("schema_version") != SUMMARY_REVIEW_SCHEMA_VERSION:
            raise ValueError("Summary review schema version is stale.")
        if review.get("paper_id") != paper_id:
            raise ValueError("Summary review paper_id does not match the current paper.")
        summary_artifact = _optional_string(paper.get("summary_artifact"))
        current_sha256 = (
            _sha256_file(root_path / summary_artifact)
            if summary_artifact and (root_path / summary_artifact).is_file()
            else None
        )
        if current_sha256 != review.get("summary_artifact_sha256"):
            return {
                "status": "stale",
                "artifact": relative_path,
                "review": review,
                "error": "Human review is stale because the current summary artifact changed.",
            }
        decision = str(review.get("decision", ""))
        if decision not in SUMMARY_REVIEW_DECISIONS:
            raise ValueError("Summary review decision is invalid.")
        return {
            "status": decision,
            "artifact": relative_path,
            "review": review,
        }
    except Exception as exc:  # noqa: BLE001 - preserve catalog availability.
        return {
            "status": "invalid",
            "artifact": relative_path,
            "review": None,
            "error": str(exc),
        }


def format_summary_review(report: SummaryReviewReport) -> str:
    lines = [
        f"Research folder: {report.root}",
        f"Paper: {report.paper_id}",
        f"Title: {report.title}",
        f"Summary artifact: {report.summary_artifact}",
        f"Machine audit: {report.evaluation_status}",
        f"Human review: {report.review_status}",
        (
            "Provenance: "
            f"provider={report.provenance.get('provider')}, "
            f"model={report.provenance.get('model')}, "
            f"prompt={report.provenance.get('prompt_version')}, "
            f"skill={_skill_label(report.provenance.get('skill'))}, "
            f"strategy={report.provenance.get('summary_strategy')}, "
            f"requests={report.provenance.get('request_count')}"
        ),
    ]
    if report.review_artifact:
        lines.append(f"Review artifact: {report.review_artifact}")
    if report.review_error:
        lines.append(f"Review error: {report.review_error}")
    for warning in report.evaluation_warnings:
        lines.append(f"Audit warning: {warning}")
    for error in report.evaluation_errors:
        lines.append(f"Audit error: {error}")
    lines.extend(
        [
            "",
            "Short summary:",
            str(report.summary.get("summary_short", "")),
            "",
            "Detailed summary:",
            str(report.summary.get("summary_detailed", "")),
            "",
            "Research question:",
            str(report.summary.get("research_question", "")),
            "",
            "Methods:",
        ]
    )
    lines.extend(f"- {item}" for item in _string_list(report.summary.get("methods")))
    lines.append("")
    lines.append("Findings:")
    for finding in _dict_list(report.summary.get("findings")):
        lines.append(f"- {finding.get('claim', '')}")
        lines.append(
            "  citations: "
            + ", ".join(_string_list(finding.get("citations")))
        )
        if finding.get("inference") is True:
            lines.append("  inference: true")
    lines.append("")
    lines.append("Limitations:")
    lines.extend(f"- {item}" for item in _string_list(report.summary.get("limitations")))
    extensions = report.summary.get("domain_extensions")
    if isinstance(extensions, dict) and extensions:
        lines.extend(
            [
                "",
                "Domain extensions:",
                json.dumps(extensions, ensure_ascii=False, indent=2),
            ]
        )
    lines.append("")
    lines.append("Cited evidence:")
    for evidence in report.evidence:
        lines.append(f"- {evidence.citation}")
        lines.append(f"  {evidence.snippet}")
    return "\n".join(lines)


def _find_paper(index: dict[str, Any], paper_id: str) -> dict[str, Any]:
    matches = [
        paper
        for paper in index.get("papers", [])
        if isinstance(paper, dict) and paper.get("id") == paper_id
    ]
    if not matches:
        raise ValueError(f"Unknown paper id: {paper_id}")
    return matches[0]


def _evidence_snippets(
    summary: dict[str, Any],
    *,
    paper: dict[str, Any],
    chunks: list[Any],
    snippet_chars: int,
) -> list[SummaryEvidenceSnippet]:
    by_citation = {
        _citation(paper, chunk): chunk
        for chunk in chunks
        if isinstance(chunk, dict) and chunk.get("id")
    }
    seen: set[str] = set()
    snippets: list[SummaryEvidenceSnippet] = []
    for citation in _iter_citations(summary):
        if citation in seen:
            continue
        seen.add(citation)
        chunk = by_citation.get(citation)
        if not chunk:
            continue
        snippets.append(
            SummaryEvidenceSnippet(
                citation=citation,
                chunk_id=str(chunk.get("id", "")),
                page_start=int(chunk.get("page_start", 0)),
                page_end=int(chunk.get("page_end", chunk.get("page_start", 0))),
                section_hint=str(chunk.get("section_hint", "")),
                snippet=_snippet(str(chunk.get("text", "")), snippet_chars),
            )
        )
    return snippets


def _iter_citations(value: Any):
    if isinstance(value, dict):
        for key, nested in value.items():
            if key == "citations" and isinstance(nested, list):
                for citation in nested:
                    if isinstance(citation, str):
                        yield citation
            else:
                yield from _iter_citations(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _iter_citations(nested)


def _citation(paper: dict[str, Any], chunk: dict[str, Any]) -> str:
    page_start = int(chunk.get("page_start", 0))
    page_end = int(chunk.get("page_end", page_start))
    pages = str(page_start) if page_start == page_end else f"{page_start}-{page_end}"
    return f"[{paper['id']} pp.{pages} chunk:{chunk.get('id', '')}]"


def _snippet(text: str, limit: int) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    return normalized if len(normalized) <= limit else f"{normalized[: limit - 3].rstrip()}..."


def _provenance(artifact: dict[str, Any]) -> dict[str, Any]:
    return {
        key: artifact.get(key)
        for key in (
            "provider",
            "model",
            "prompt_version",
            "skill",
            "summarized_at",
            "usage",
            "summary_strategy",
            "request_count",
            "input_char_count",
            "fallback_reason",
        )
    }


def _review_dir(root: Path, paper_id: str) -> Path:
    return root / ".odracir" / "reviews" / "summaries" / _safe_name(paper_id)


def _review_id(reviewed_at: str) -> str:
    timestamp = re.sub(r"[^0-9A-Za-z]+", "", reviewed_at)
    return f"{timestamp}-{uuid4().hex[:8]}"


def _safe_name(value: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value).strip("-")
    return safe or "paper"


def _required_string(value: Any, error: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(error)
    return value


def _optional_string(value: Any) -> str | None:
    return str(value) if isinstance(value, str) and value else None


def _string_list(value: Any) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


def _dict_list(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _skill_label(value: Any) -> str:
    if not isinstance(value, dict):
        return "none"
    return f"{value.get('name', 'none')}@{value.get('version', 'none')}"


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


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(f"{path.suffix}.{uuid4().hex}.tmp")
    with temporary_path.open("w", encoding="utf-8", newline="\n") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
        file.write("\n")
    temporary_path.replace(path)
