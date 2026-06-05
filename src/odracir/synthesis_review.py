"""Deterministic quality review for cross-paper synthesis artifacts."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from odracir.research_memory import ResearchCatalogBuilder
from odracir.schemas import SYNTHESIS_REVIEW_SCHEMA_VERSION, SYNTHESIS_SCHEMA_VERSION
from odracir.synthesis import validate_synthesis
from odracir.time_utils import now_iso


SYNTHESIS_REVIEW_POLICY_VERSION = "0.1"
DEFAULT_SYNTHESIS_REVIEW_NAME = "synthesis_review.md"


@dataclass(frozen=True)
class SynthesisReviewIssue:
    severity: str
    category: str
    message: str
    location: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SynthesisReviewReport:
    root: str
    synthesis_artifact: str
    synthesis_artifact_sha256: str
    review_artifact: str | None
    markdown_path: str | None
    status: str
    issue_counts: dict[str, int]
    coverage: dict[str, Any]
    issues: list[SynthesisReviewIssue]

    def as_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "issues": [issue.as_dict() for issue in self.issues],
        }


class SynthesisReviewHarness:
    """Review synthesis quality without calling an LLM."""

    def __init__(
        self,
        root: str | Path,
        papers_dir: str | Path | None = None,
        *,
        markdown_name: str = DEFAULT_SYNTHESIS_REVIEW_NAME,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.papers_dir = papers_dir
        self.synthesis_dir = self.root / ".odracir" / "synthesis"
        self.reviews_dir = self.synthesis_dir / "reviews"
        self.markdown_path = _root_child_path(self.root, markdown_name, "markdown_name")

    def review(
        self,
        *,
        synthesis_artifact: str | Path | None = None,
        write_artifact: bool = True,
        write_markdown: bool = True,
    ) -> SynthesisReviewReport:
        artifact_path = self._resolve_artifact(synthesis_artifact)
        artifact = _load_json(artifact_path)
        if artifact.get("schema_version") != SYNTHESIS_SCHEMA_VERSION:
            raise ValueError("Synthesis artifact has an unsupported schema version.")
        synthesis = artifact.get("synthesis")
        if not isinstance(synthesis, dict):
            raise ValueError("Synthesis artifact must contain a synthesis object.")

        catalog = ResearchCatalogBuilder(
            self.root,
            papers_dir=self.papers_dir,
        ).build()
        records = [
            record
            for record in catalog.records
            if isinstance(record.get("summary"), dict)
            and record.get("memory_quality", {}).get("status") in {"passed", "warning"}
        ]
        paper_ids = {str(record["paper_id"]) for record in records}
        issues: list[SynthesisReviewIssue] = []
        try:
            validate_synthesis(synthesis, paper_ids)
        except Exception as exc:  # noqa: BLE001 - report malformed artifacts.
            issues.append(
                SynthesisReviewIssue(
                    severity="error",
                    category="schema",
                    message=str(exc),
                    location="synthesis",
                )
            )

        coverage = _coverage(synthesis, paper_ids)
        issues.extend(_coverage_issues(coverage))
        issues.extend(_claim_evidence_issues(synthesis))
        issues.extend(_benchmark_issues(synthesis))
        issues.extend(_priority_issues(synthesis, paper_ids))
        status = _status(issues)
        synthesis_sha256 = _sha256_file(artifact_path)
        review_payload = {
            "schema_version": SYNTHESIS_REVIEW_SCHEMA_VERSION,
            "policy_version": SYNTHESIS_REVIEW_POLICY_VERSION,
            "generated_at": now_iso(),
            "synthesis_artifact": artifact_path.relative_to(self.root).as_posix(),
            "synthesis_artifact_sha256": synthesis_sha256,
            "status": status,
            "issue_counts": _issue_counts(issues),
            "coverage": coverage,
            "issues": [issue.as_dict() for issue in issues],
        }
        review_artifact = self.reviews_dir / f"{synthesis_sha256[:20]}.json"
        if write_artifact:
            _write_json(review_artifact, review_payload)
        if write_markdown:
            _write_text(self.markdown_path, render_synthesis_review_markdown(review_payload))
        return SynthesisReviewReport(
            root=str(self.root),
            synthesis_artifact=artifact_path.relative_to(self.root).as_posix(),
            synthesis_artifact_sha256=synthesis_sha256,
            review_artifact=(
                review_artifact.relative_to(self.root).as_posix()
                if write_artifact
                else None
            ),
            markdown_path=str(self.markdown_path) if write_markdown else None,
            status=status,
            issue_counts=_issue_counts(issues),
            coverage=coverage,
            issues=issues,
        )

    def _resolve_artifact(self, synthesis_artifact: str | Path | None) -> Path:
        if synthesis_artifact:
            path = Path(synthesis_artifact)
            resolved = path.expanduser().resolve() if path.is_absolute() else (self.root / path).resolve()
            try:
                resolved.relative_to(self.root)
            except ValueError as exc:
                raise ValueError("Synthesis artifact must be inside the research folder.") from exc
            if not resolved.is_file():
                raise ValueError(f"Synthesis artifact does not exist: {resolved}")
            return resolved
        candidates = [
            path
            for path in self.synthesis_dir.glob("*.json")
            if path.parent == self.synthesis_dir
        ]
        if not candidates:
            raise ValueError("No synthesis artifact found. Run `odracir synthesize` first.")
        return max(candidates, key=lambda path: path.stat().st_mtime)


def render_synthesis_review_markdown(review: dict[str, Any]) -> str:
    coverage = review.get("coverage", {})
    lines = [
        "# Synthesis Review",
        "",
        f"Status: {review.get('status', 'unknown')}",
        "",
        "## Coverage",
        "",
        f"- Papers total: {coverage.get('papers_total', 0)}",
        f"- Topic group coverage: {coverage.get('topic_group_coverage', 0)}/{coverage.get('papers_total', 0)}",
        f"- Method comparison coverage: {coverage.get('method_comparison_coverage', 0)}/{coverage.get('papers_total', 0)}",
        f"- Benchmark matrix coverage: {coverage.get('benchmark_matrix_coverage', 0)}/{coverage.get('papers_total', 0)}",
        f"- Reading priority coverage: {coverage.get('priority_coverage', 0)}/{coverage.get('papers_total', 0)}",
        f"- Claims total: {coverage.get('claims_total', 0)}",
        f"- Claims with citations: {coverage.get('claims_with_citations', 0)}",
        f"- Strong claims: {coverage.get('strong_claims', 0)}",
        "",
        "## Issues",
        "",
    ]
    issues = review.get("issues", [])
    if not issues:
        lines.append("No deterministic review issues found.")
    else:
        for issue in issues:
            lines.append(
                "- "
                f"[{issue.get('severity', 'unknown')}] "
                f"{issue.get('category', 'unknown')} at {issue.get('location', '')}: "
                f"{issue.get('message', '')}"
            )
    return "\n".join(lines).rstrip() + "\n"


def format_synthesis_review(report: SynthesisReviewReport) -> str:
    return "\n".join(
        [
            f"Research folder: {report.root}",
            f"Synthesis artifact: {report.synthesis_artifact}",
            f"Review artifact: {report.review_artifact or 'not written'}",
            f"Markdown: {report.markdown_path or 'not written'}",
            (
                "Synthesis review: "
                f"status={report.status}, "
                f"issues={_format_counts(report.issue_counts)}"
            ),
        ]
    )


def _coverage(synthesis: dict[str, Any], paper_ids: set[str]) -> dict[str, Any]:
    topic_ids = _ids_from_items(synthesis.get("topic_groups"), "paper_ids")
    method_ids = _ids_from_items(synthesis.get("method_comparison"), "paper_ids")
    benchmark_ids = _ids_from_items(synthesis.get("benchmark_matrix"), "paper_id")
    priority_ids = _ids_from_items(
        synthesis.get("reading_reproduction_priority"),
        "paper_id",
    )
    claims = synthesis.get("claim_evidence_matrix", [])
    claim_items = claims if isinstance(claims, list) else []
    claims_with_citations = 0
    strong_claims = 0
    for claim in claim_items:
        if not isinstance(claim, dict):
            continue
        if claim.get("evidence_strength") == "strong":
            strong_claims += 1
        evidence = []
        for field in ("supporting_evidence", "contradicting_evidence"):
            values = claim.get(field, [])
            if isinstance(values, list):
                evidence.extend(item for item in values if isinstance(item, dict))
        if any(item.get("original_citations") for item in evidence):
            claims_with_citations += 1
    return {
        "papers_total": len(paper_ids),
        "topic_group_coverage": len(topic_ids & paper_ids),
        "method_comparison_coverage": len(method_ids & paper_ids),
        "benchmark_matrix_coverage": len(benchmark_ids & paper_ids),
        "priority_coverage": len(priority_ids & paper_ids),
        "unused_papers": sorted(paper_ids - (topic_ids | method_ids | benchmark_ids | priority_ids)),
        "missing_benchmark_papers": sorted(paper_ids - benchmark_ids),
        "missing_priority_papers": sorted(paper_ids - priority_ids),
        "claims_total": sum(isinstance(item, dict) for item in claim_items),
        "claims_with_citations": claims_with_citations,
        "strong_claims": strong_claims,
    }


def _coverage_issues(coverage: dict[str, Any]) -> list[SynthesisReviewIssue]:
    issues = []
    papers_total = int(coverage.get("papers_total", 0))
    if papers_total == 0:
        issues.append(
            SynthesisReviewIssue(
                "error",
                "coverage",
                "No audited papers are available for synthesis review.",
                "coverage.papers_total",
            )
        )
        return issues
    for key, label in (
        ("topic_group_coverage", "topic groups"),
        ("benchmark_matrix_coverage", "benchmark matrix"),
        ("priority_coverage", "reading/reproduction priority"),
    ):
        if int(coverage.get(key, 0)) < papers_total:
            issues.append(
                SynthesisReviewIssue(
                    "warning",
                    "coverage",
                    f"Not every paper is represented in {label}.",
                    f"coverage.{key}",
                )
            )
    if coverage.get("unused_papers"):
        issues.append(
            SynthesisReviewIssue(
                "warning",
                "coverage",
                "Some papers are not used by any major synthesis section.",
                "coverage.unused_papers",
            )
        )
    return issues


def _claim_evidence_issues(synthesis: dict[str, Any]) -> list[SynthesisReviewIssue]:
    issues = []
    claims = synthesis.get("claim_evidence_matrix", [])
    if not isinstance(claims, list):
        return issues
    for index, claim in enumerate(claims):
        if not isinstance(claim, dict):
            continue
        supporting = [
            item
            for item in claim.get("supporting_evidence", [])
            if isinstance(item, dict)
        ]
        location = f"claim_evidence_matrix[{index}]"
        if not supporting:
            issues.append(
                SynthesisReviewIssue(
                    "error",
                    "claim_evidence",
                    "Claim has no supporting evidence.",
                    location,
                )
            )
            continue
        if not any(item.get("original_citations") for item in supporting):
            issues.append(
                SynthesisReviewIssue(
                    "warning",
                    "claim_evidence",
                    "Claim supporting evidence lacks original citations.",
                    location,
                )
            )
        if claim.get("evidence_strength") == "strong":
            supporting_papers = {str(item.get("paper_id")) for item in supporting}
            has_empirical = any(
                item.get("evidence_type") in {"benchmark", "experiment"}
                for item in supporting
            )
            if len(supporting_papers) < 2 and not has_empirical:
                issues.append(
                    SynthesisReviewIssue(
                        "warning",
                        "evidence_strength",
                        "Strong claim has limited paper support and no empirical evidence type.",
                        location,
                    )
                )
    return issues


def _benchmark_issues(synthesis: dict[str, Any]) -> list[SynthesisReviewIssue]:
    issues = []
    benchmarks = synthesis.get("benchmark_matrix", [])
    if not isinstance(benchmarks, list):
        return issues
    for index, benchmark in enumerate(benchmarks):
        if not isinstance(benchmark, dict):
            continue
        location = f"benchmark_matrix[{index}]"
        if not benchmark.get("comparability_notes"):
            issues.append(
                SynthesisReviewIssue(
                    "warning",
                    "benchmark_matrix",
                    "Benchmark row lacks comparability notes.",
                    location,
                )
            )
        if not benchmark.get("metrics"):
            issues.append(
                SynthesisReviewIssue(
                    "warning",
                    "benchmark_matrix",
                    "Benchmark row lacks metrics.",
                    location,
                )
            )
    return issues


def _priority_issues(
    synthesis: dict[str, Any],
    paper_ids: set[str],
) -> list[SynthesisReviewIssue]:
    priorities = synthesis.get("reading_reproduction_priority", [])
    if not isinstance(priorities, list):
        return []
    seen = {
        str(item.get("paper_id"))
        for item in priorities
        if isinstance(item, dict) and item.get("paper_id") in paper_ids
    }
    missing = sorted(paper_ids - seen)
    if not missing:
        return []
    return [
        SynthesisReviewIssue(
            "warning",
            "priority",
            f"Missing reading/reproduction priority for {len(missing)} papers.",
            "reading_reproduction_priority",
        )
    ]


def _ids_from_items(value: Any, field: str) -> set[str]:
    if not isinstance(value, list):
        return set()
    ids = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        raw = item.get(field)
        if isinstance(raw, list):
            ids.update(str(entry) for entry in raw)
        elif raw:
            ids.add(str(raw))
    return ids


def _status(issues: list[SynthesisReviewIssue]) -> str:
    severities = {issue.severity for issue in issues}
    if "error" in severities:
        return "fail"
    if "warning" in severities:
        return "warning"
    return "pass"


def _issue_counts(issues: list[SynthesisReviewIssue]) -> dict[str, int]:
    return dict(sorted(Counter(issue.severity for issue in issues).items()))


def _format_counts(counts: dict[str, int]) -> str:
    return ", ".join(f"{key}={value}" for key, value in sorted(counts.items())) or "none"


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object.")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(f"{path.suffix}.{uuid4().hex}.tmp")
    with temporary_path.open("w", encoding="utf-8", newline="\n") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
        file.write("\n")
    temporary_path.replace(path)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(f"{path.suffix}.{uuid4().hex}.tmp")
    temporary_path.write_text(text, encoding="utf-8", newline="\n")
    temporary_path.replace(path)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _root_child_path(root: Path, value: str | Path, field: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        raise ValueError(f"{field} must be a relative path inside the research folder.")
    if path.parts and path.parts[0] == ".odracir":
        raise ValueError(f"{field} must not point inside the .odracir state directory.")
    resolved = (root / path).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{field} must stay inside the research folder.") from exc
    if resolved == root:
        raise ValueError(f"{field} must be a file path inside the research folder.")
    return resolved
