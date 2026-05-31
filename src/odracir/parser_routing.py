"""Auditable parser recommendations over read-only benchmark evidence."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import asdict, dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from odracir.parser_benchmark import (
    ParserBenchmarkHarness,
    ParserBenchmarkRecord,
    ParserBenchmarkReport,
)
from odracir.parsers import ParserRegistry
from odracir.research_folder import ResearchFolderHarness
from odracir.schemas import PARSER_ROUTING_SCHEMA_VERSION
from odracir.time_utils import now_iso


PARSER_ROUTING_POLICY_VERSION = "0.1"
DEFAULT_BASELINE_PARSER = "pymupdf"
DEFAULT_CANDIDATE_PARSER = "pymupdf4llm"
MIN_CANDIDATE_GAIN_CHARS = 1000
MIN_CANDIDATE_GAIN_RATIO = 0.03


@dataclass(frozen=True)
class ParserRecommendation:
    paper_id: str
    source_file: str
    source_sha256: str
    selected_parser: str | None
    recommended_parser: str | None
    action: str
    review_required: bool
    reasons: list[str]
    baseline: dict[str, Any]
    candidate: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ParserRoutingReport:
    root: str
    artifact_path: str
    cached: bool
    policy_version: str
    baseline_parser: str
    candidate_parser: str
    thresholds: dict[str, int | float]
    papers: int
    action_counts: dict[str, int]
    recommendations: list[ParserRecommendation]
    benchmark: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "artifact_path": self.artifact_path,
            "cached": self.cached,
            "policy_version": self.policy_version,
            "baseline_parser": self.baseline_parser,
            "candidate_parser": self.candidate_parser,
            "thresholds": self.thresholds,
            "papers": self.papers,
            "action_counts": self.action_counts,
            "recommendations": [
                recommendation.as_dict() for recommendation in self.recommendations
            ],
            "benchmark": self.benchmark,
        }


class ParserRoutingAdvisor:
    """Generate cached parser recommendations without mutating extraction state."""

    def __init__(
        self,
        root: str | Path,
        papers_dir: str | Path | None = None,
        *,
        parser_registry: ParserRegistry | None = None,
        benchmark_harness: ParserBenchmarkHarness | None = None,
    ) -> None:
        self.harness = ResearchFolderHarness(root, papers_dir=papers_dir)
        self.root = self.harness.root
        self.routing_dir = self.root / ".odracir" / "parser-routing"
        self.benchmark_harness = benchmark_harness or ParserBenchmarkHarness(
            root,
            papers_dir=papers_dir,
            parser_registry=parser_registry,
        )

    def recommend(
        self,
        *,
        paper_id: str | None = None,
        limit: int | None = None,
        force: bool = False,
        baseline_parser: str = DEFAULT_BASELINE_PARSER,
        candidate_parser: str = DEFAULT_CANDIDATE_PARSER,
    ) -> ParserRoutingReport:
        if limit is not None and limit < 1:
            raise ValueError("Recommendation limit must be at least 1.")
        if baseline_parser == candidate_parser:
            raise ValueError("Baseline and candidate parsers must differ.")

        index = self.harness.load_index()
        papers = _select_papers(index, paper_id=paper_id, limit=limit)
        if not papers:
            raise ValueError("No indexed PDF papers matched. Run `odracir scan` first.")

        input_sha256 = _input_sha256(
            papers,
            baseline_parser=baseline_parser,
            candidate_parser=candidate_parser,
        )
        self.routing_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = self.routing_dir / f"{input_sha256[:20]}.json"
        if not force and artifact_path.is_file():
            artifact = _load_json(artifact_path)
            if _can_use_cached(artifact, input_sha256=input_sha256):
                return _report_from_artifact(
                    root=self.root,
                    artifact_path=artifact_path,
                    artifact=artifact,
                    cached=True,
                )

        benchmark = self.benchmark_harness.run(
            parser_names=(baseline_parser, candidate_parser),
            paper_id=paper_id,
            limit=limit,
        )
        paper_by_id = {str(paper["id"]): paper for paper in papers}
        recommendations = _build_recommendations(
            benchmark,
            paper_by_id=paper_by_id,
            baseline_parser=baseline_parser,
            candidate_parser=candidate_parser,
        )
        artifact = {
            "schema_version": PARSER_ROUTING_SCHEMA_VERSION,
            "policy_version": PARSER_ROUTING_POLICY_VERSION,
            "generated_at": now_iso(),
            "input_sha256": input_sha256,
            "baseline_parser": baseline_parser,
            "candidate_parser": candidate_parser,
            "thresholds": {
                "min_candidate_gain_chars": MIN_CANDIDATE_GAIN_CHARS,
                "min_candidate_gain_ratio": MIN_CANDIDATE_GAIN_RATIO,
            },
            "papers": len(papers),
            "action_counts": _action_counts(recommendations),
            "recommendations": [
                recommendation.as_dict() for recommendation in recommendations
            ],
            "benchmark": benchmark.as_dict(),
        }
        _write_json(artifact_path, artifact)
        return _report_from_artifact(
            root=self.root,
            artifact_path=artifact_path,
            artifact=artifact,
            cached=False,
        )


def format_parser_routing(report: ParserRoutingReport) -> str:
    lines = [
        f"Research folder: {report.root}",
        f"Parser recommendations: {report.papers} papers, cached={'yes' if report.cached else 'no'}",
        f"Policy: {report.policy_version}, baseline={report.baseline_parser}, candidate={report.candidate_parser}",
        (
            "Thresholds: "
            f"chars>={report.thresholds['min_candidate_gain_chars']}, "
            f"ratio>={report.thresholds['min_candidate_gain_ratio']:.0%}"
        ),
        f"Artifact: {report.artifact_path}",
        "Recommendations are advisory; extraction artifacts were not modified.",
    ]
    for action, count in sorted(report.action_counts.items()):
        lines.append(f"- {action}: {count}")
    for recommendation in report.recommendations:
        lines.append(
            f"- {recommendation.paper_id}: {recommendation.action}, "
            f"selected={recommendation.selected_parser or 'none'}, "
            f"recommended={recommendation.recommended_parser or 'none'}, "
            f"review={'yes' if recommendation.review_required else 'no'}"
        )
        for reason in recommendation.reasons:
            lines.append(f"  {reason}")
    return "\n".join(lines)


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
    papers: list[dict[str, Any]],
    *,
    baseline_parser: str,
    candidate_parser: str,
) -> str:
    payload = {
        "schema_version": PARSER_ROUTING_SCHEMA_VERSION,
        "policy_version": PARSER_ROUTING_POLICY_VERSION,
        "baseline_parser": baseline_parser,
        "candidate_parser": candidate_parser,
        "thresholds": {
            "min_candidate_gain_chars": MIN_CANDIDATE_GAIN_CHARS,
            "min_candidate_gain_ratio": MIN_CANDIDATE_GAIN_RATIO,
        },
        "parser_versions": {
            baseline_parser: _parser_package_version(baseline_parser),
            candidate_parser: _parser_package_version(candidate_parser),
        },
        "papers": [
            {
                "id": paper["id"],
                "source_file": paper["source_file"],
                "sha256": paper["sha256"],
            }
            for paper in papers
        ],
    }
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _build_recommendations(
    benchmark: ParserBenchmarkReport,
    *,
    paper_by_id: dict[str, dict[str, Any]],
    baseline_parser: str,
    candidate_parser: str,
) -> list[ParserRecommendation]:
    records = {
        (record.paper_id, record.parser): record
        for record in benchmark.records
    }
    return [
        _recommend_one(
            paper=paper,
            baseline=records[(paper_id, baseline_parser)],
            candidate=records[(paper_id, candidate_parser)],
            baseline_parser=baseline_parser,
            candidate_parser=candidate_parser,
        )
        for paper_id, paper in paper_by_id.items()
    ]


def _recommend_one(
    *,
    paper: dict[str, Any],
    baseline: ParserBenchmarkRecord,
    candidate: ParserBenchmarkRecord,
    baseline_parser: str,
    candidate_parser: str,
) -> ParserRecommendation:
    reasons: list[str] = []
    selected_parser: str | None = baseline_parser if baseline.status == "succeeded" else None
    recommended_parser: str | None = selected_parser
    action = "keep_baseline"
    review_required = False

    if baseline.status != "succeeded" and candidate.status != "succeeded":
        action = "review_manually"
        recommended_parser = None
        review_required = True
        reasons.append(f"Both parser backends failed: {baseline.error}; {candidate.error}")
    elif baseline.status != "succeeded":
        action = "review_candidate"
        recommended_parser = candidate_parser
        review_required = True
        reasons.append(f"Baseline parser failed: {baseline.error}")
        reasons.append("Candidate parser succeeded; inspect its output before extraction.")
    elif baseline.needs_ocr:
        action = "run_ocr_preprocessing"
        recommended_parser = baseline_parser
        review_required = True
        reasons.append(
            f"Baseline parser reported OCR need: {baseline.ocr_reason or 'unspecified'}."
        )
        reasons.append("Use the explicit OCRmyPDF derivative route before parser upgrades.")
    elif candidate.status != "succeeded":
        reasons.append(f"Candidate parser failed; retain baseline: {candidate.error}")
    elif baseline.page_count != candidate.page_count:
        action = "review_manually"
        recommended_parser = None
        review_required = True
        reasons.append(
            f"Page-count mismatch: baseline={baseline.page_count}, candidate={candidate.page_count}."
        )
    else:
        baseline_chars = baseline.text_char_count or 0
        candidate_chars = candidate.text_char_count or 0
        gain_chars = candidate_chars - baseline_chars
        gain_ratio = gain_chars / max(1, baseline_chars)
        reasons.append(
            f"Candidate text delta: {gain_chars:+d} chars ({gain_ratio * 100:.2f}%)."
        )
        if (
            gain_chars >= MIN_CANDIDATE_GAIN_CHARS
            and gain_ratio >= MIN_CANDIDATE_GAIN_RATIO
        ):
            action = "review_candidate"
            recommended_parser = candidate_parser
            review_required = True
            reasons.append(
                "Candidate crossed the conservative text-gain threshold; inspect layout "
                "quality before explicit extraction."
            )
        else:
            reasons.append(
                "Candidate did not cross the conservative text-gain threshold; retain baseline."
            )

    return ParserRecommendation(
        paper_id=str(paper["id"]),
        source_file=str(paper["source_file"]),
        source_sha256=str(paper["sha256"]),
        selected_parser=selected_parser,
        recommended_parser=recommended_parser,
        action=action,
        review_required=review_required,
        reasons=reasons,
        baseline=baseline.as_dict(),
        candidate=candidate.as_dict(),
    )


def _action_counts(recommendations: list[ParserRecommendation]) -> dict[str, int]:
    return dict(sorted(Counter(item.action for item in recommendations).items()))


def _can_use_cached(artifact: dict[str, Any], *, input_sha256: str) -> bool:
    return (
        artifact.get("schema_version") == PARSER_ROUTING_SCHEMA_VERSION
        and artifact.get("policy_version") == PARSER_ROUTING_POLICY_VERSION
        and artifact.get("input_sha256") == input_sha256
        and isinstance(artifact.get("thresholds"), dict)
        and isinstance(artifact.get("action_counts"), dict)
        and isinstance(artifact.get("recommendations"), list)
        and isinstance(artifact.get("benchmark"), dict)
    )


def _report_from_artifact(
    *,
    root: Path,
    artifact_path: Path,
    artifact: dict[str, Any],
    cached: bool,
) -> ParserRoutingReport:
    return ParserRoutingReport(
        root=str(root),
        artifact_path=artifact_path.relative_to(root).as_posix(),
        cached=cached,
        policy_version=str(artifact["policy_version"]),
        baseline_parser=str(artifact["baseline_parser"]),
        candidate_parser=str(artifact["candidate_parser"]),
        thresholds={
            str(key): value for key, value in dict(artifact["thresholds"]).items()
        },
        papers=int(artifact["papers"]),
        action_counts={
            str(key): int(value)
            for key, value in dict(artifact["action_counts"]).items()
        },
        recommendations=[
            ParserRecommendation(**recommendation)
            for recommendation in artifact["recommendations"]
        ],
        benchmark=dict(artifact["benchmark"]),
    )


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


def _parser_package_version(parser_name: str) -> str:
    package_name = {
        "pymupdf": "pymupdf",
        "pymupdf4llm": "pymupdf4llm",
        "docling": "docling",
    }.get(parser_name)
    if package_name is None:
        return "unregistered-package"
    try:
        return version(package_name)
    except PackageNotFoundError:
        return "not-installed"
