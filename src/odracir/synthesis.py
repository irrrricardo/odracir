"""Cross-paper synthesis over audited research catalog memory."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from odracir.providers import JsonCompletionProvider
from odracir.research_memory import ResearchCatalogBuilder
from odracir.schemas import SYNTHESIS_SCHEMA_VERSION
from odracir.time_utils import now_iso


SYNTHESIS_PROMPT_VERSION = "0.1"
SYNTHESIS_MAX_TOKENS = 12000
DEFAULT_SYNTHESIS_NAME = "research_synthesis.md"

SYNTHESIS_SYSTEM_PROMPT = """You synthesize a small research paper library from
audited local paper summaries. Return one json object only. Treat summaries as
secondary evidence, not as ground truth. Use only paper_id values supplied by
the user. Keep claims grounded in the supplied papers and mark uncertainty when
coverage is weak. Use this json shape:
{
  "overview": "string",
  "topic_groups": [
    {
      "name": "string",
      "description": "string",
      "paper_ids": ["paper-id"],
      "key_takeaways": ["string"]
    }
  ],
  "method_comparison": [
    {
      "method": "string",
      "paper_ids": ["paper-id"],
      "problem_addressed": "string",
      "core_idea": "string",
      "strengths": ["string"],
      "limitations": ["string"]
    }
  ],
  "evidence_matrix": [
    {
      "claim": "string",
      "supporting_papers": ["paper-id"],
      "contradicting_papers": ["paper-id"],
      "evidence_strength": "weak|moderate|strong",
      "notes": "string"
    }
  ],
  "claim_evidence_matrix": [
    {
      "claim": "string",
      "supporting_evidence": [
        {
          "paper_id": "paper-id",
          "evidence_type": "benchmark|experiment|theory|review|inference",
          "summary_finding": "string",
          "original_citations": ["[paper pp.1 chunk:id]"]
        }
      ],
      "contradicting_evidence": [
        {
          "paper_id": "paper-id",
          "evidence_type": "benchmark|experiment|theory|review|inference",
          "summary_finding": "string",
          "original_citations": ["[paper pp.1 chunk:id]"]
        }
      ],
      "evidence_strength": "weak|moderate|strong",
      "uncertainty": "string"
    }
  ],
  "method_family_tree": [
    {
      "family": "string",
      "description": "string",
      "methods": [
        {
          "name": "string",
          "paper_ids": ["paper-id"],
          "role": "string",
          "related_methods": ["string"]
        }
      ]
    }
  ],
  "benchmark_matrix": [
    {
      "paper_id": "paper-id",
      "benchmarks_or_datasets": ["string"],
      "metrics": ["string"],
      "baselines": ["string"],
      "reported_result": "string",
      "comparability_notes": "string"
    }
  ],
  "reading_reproduction_priority": [
    {
      "paper_id": "paper-id",
      "reading_priority": "low|medium|high",
      "reproduction_priority": "low|medium|high",
      "reason": "string",
      "suggested_action": "string"
    }
  ],
  "conflicts_or_tensions": [
    {
      "issue": "string",
      "paper_ids": ["paper-id"],
      "explanation": "string"
    }
  ],
  "research_gaps": ["string"],
  "recommended_next_steps": ["string"]
}
"""


@dataclass(frozen=True)
class SynthesisResult:
    root: str
    catalog_path: str | None
    artifact_path: str | None
    markdown_path: str | None
    cached: bool
    paper_count: int
    usage: dict[str, int]
    synthesis: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class ResearchSynthesizer:
    """Build reusable cross-paper synthesis artifacts from catalog summaries."""

    def __init__(
        self,
        root: str | Path,
        provider: JsonCompletionProvider,
        papers_dir: str | Path | None = None,
        *,
        output_name: str = DEFAULT_SYNTHESIS_NAME,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.papers_dir = papers_dir
        self.provider = provider
        self.synthesis_dir = self.root / ".odracir" / "synthesis"
        self.markdown_path = _root_child_path(self.root, output_name, "output_name")

    def synthesize(
        self,
        *,
        force: bool = False,
        write_markdown: bool = True,
    ) -> SynthesisResult:
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
        if not records:
            raise ValueError("Synthesis requires at least one audited paper summary.")

        input_payload = _synthesis_input(records)
        input_sha256 = _sha256_json(
            {
                "schema_version": SYNTHESIS_SCHEMA_VERSION,
                "prompt_version": SYNTHESIS_PROMPT_VERSION,
                "provider": self.provider.provider_name,
                "model": self.provider.model,
                "papers": input_payload,
            }
        )
        artifact_path = self.synthesis_dir / f"{input_sha256[:16]}.json"
        if not force and artifact_path.is_file():
            artifact = _load_json(artifact_path)
            if _can_use_cached_artifact(
                artifact,
                input_sha256=input_sha256,
                provider=self.provider,
            ):
                try:
                    synthesis = validate_synthesis(
                        dict(artifact["synthesis"]),
                        {str(record["paper_id"]) for record in records},
                    )
                except ValueError:
                    synthesis = None
                if synthesis is not None:
                    markdown = render_synthesis_markdown(synthesis, records=records)
                    if write_markdown:
                        _write_text(self.markdown_path, markdown)
                    return SynthesisResult(
                        root=str(self.root),
                        catalog_path=catalog.catalog_path,
                        artifact_path=artifact_path.relative_to(self.root).as_posix(),
                        markdown_path=str(self.markdown_path) if write_markdown else None,
                        cached=True,
                        paper_count=len(records),
                        usage=dict(artifact.get("usage", {})),
                        synthesis=synthesis,
                    )

        response = self.provider.complete_json(
            system_prompt=SYNTHESIS_SYSTEM_PROMPT,
            user_prompt=(
                "Paper summaries json:\n"
                f"{json.dumps(input_payload, ensure_ascii=False)}"
            ),
            max_tokens=SYNTHESIS_MAX_TOKENS,
        )
        synthesis = validate_synthesis(
            response.payload,
            {str(record["paper_id"]) for record in records},
        )
        artifact = {
            "schema_version": SYNTHESIS_SCHEMA_VERSION,
            "prompt_version": SYNTHESIS_PROMPT_VERSION,
            "generated_at": now_iso(),
            "input_sha256": input_sha256,
            "catalog_path": catalog.catalog_path,
            "provider": self.provider.provider_name,
            "model": self.provider.model,
            "usage": response.usage,
            "paper_count": len(records),
            "papers": input_payload,
            "synthesis": synthesis,
        }
        _write_json(artifact_path, artifact)
        markdown = render_synthesis_markdown(synthesis, records=records)
        if write_markdown:
            _write_text(self.markdown_path, markdown)
        return SynthesisResult(
            root=str(self.root),
            catalog_path=catalog.catalog_path,
            artifact_path=artifact_path.relative_to(self.root).as_posix(),
            markdown_path=str(self.markdown_path) if write_markdown else None,
            cached=False,
            paper_count=len(records),
            usage=response.usage,
            synthesis=synthesis,
        )


def validate_synthesis(
    synthesis: dict[str, Any],
    allowed_paper_ids: set[str],
) -> dict[str, Any]:
    if not allowed_paper_ids:
        raise ValueError("Synthesis validation requires at least one allowed paper id.")
    for field in (
        "overview",
        "topic_groups",
        "method_comparison",
        "evidence_matrix",
        "claim_evidence_matrix",
        "method_family_tree",
        "benchmark_matrix",
        "reading_reproduction_priority",
        "conflicts_or_tensions",
        "research_gaps",
        "recommended_next_steps",
    ):
        if field not in synthesis:
            raise ValueError(f"Synthesis is missing field: {field}.")
    if not isinstance(synthesis.get("overview"), str):
        raise ValueError("Synthesis field overview must be a string.")
    for field in ("research_gaps", "recommended_next_steps"):
        _string_list_required(synthesis.get(field), field)

    for group in _object_list(synthesis.get("topic_groups"), "topic_groups"):
        _string_list_required(group.get("key_takeaways", []), "topic_groups.key_takeaways")
        _validate_paper_ids(group.get("paper_ids"), allowed_paper_ids, "topic_groups")
    for method in _object_list(
        synthesis.get("method_comparison"),
        "method_comparison",
    ):
        _validate_paper_ids(
            method.get("paper_ids"),
            allowed_paper_ids,
            "method_comparison",
        )
        _string_list_required(method.get("strengths", []), "method_comparison.strengths")
        _string_list_required(method.get("limitations", []), "method_comparison.limitations")
    for evidence in _object_list(synthesis.get("evidence_matrix"), "evidence_matrix"):
        _validate_paper_ids(
            evidence.get("supporting_papers"),
            allowed_paper_ids,
            "evidence_matrix.supporting_papers",
        )
        _validate_paper_ids(
            evidence.get("contradicting_papers"),
            allowed_paper_ids,
            "evidence_matrix.contradicting_papers",
        )
        if evidence.get("evidence_strength") not in {"weak", "moderate", "strong"}:
            raise ValueError("Evidence strength must be weak, moderate, or strong.")
    for claim in _object_list(
        synthesis.get("claim_evidence_matrix"),
        "claim_evidence_matrix",
    ):
        for field in ("supporting_evidence", "contradicting_evidence"):
            for evidence in _object_list(claim.get(field), f"claim_evidence_matrix.{field}"):
                _validate_paper_ids(
                    [evidence.get("paper_id")],
                    allowed_paper_ids,
                    f"claim_evidence_matrix.{field}.paper_id",
                )
                if evidence.get("evidence_type") not in {
                    "benchmark",
                    "experiment",
                    "theory",
                    "review",
                    "inference",
                }:
                    raise ValueError(
                        "Claim evidence type must be benchmark, experiment, theory, review, or inference."
                    )
                citations = evidence.get("original_citations", [])
                if not isinstance(citations, list):
                    raise ValueError("Claim evidence original_citations must be a list.")
                _string_list_required(
                    citations,
                    "claim_evidence_matrix.original_citations",
                )
        if claim.get("evidence_strength") not in {"weak", "moderate", "strong"}:
            raise ValueError("Claim evidence strength must be weak, moderate, or strong.")
    for family in _object_list(synthesis.get("method_family_tree"), "method_family_tree"):
        for method in _object_list(family.get("methods"), "method_family_tree.methods"):
            _validate_paper_ids(
                method.get("paper_ids"),
                allowed_paper_ids,
                "method_family_tree.methods.paper_ids",
            )
            if not isinstance(method.get("related_methods", []), list):
                raise ValueError("Related methods must be a list.")
    for benchmark in _object_list(synthesis.get("benchmark_matrix"), "benchmark_matrix"):
        _validate_paper_ids(
            [benchmark.get("paper_id")],
            allowed_paper_ids,
            "benchmark_matrix.paper_id",
        )
        for field in ("benchmarks_or_datasets", "metrics", "baselines"):
            _string_list_required(benchmark.get(field), f"benchmark_matrix.{field}")
    for priority in _object_list(
        synthesis.get("reading_reproduction_priority"),
        "reading_reproduction_priority",
    ):
        _validate_paper_ids(
            [priority.get("paper_id")],
            allowed_paper_ids,
            "reading_reproduction_priority.paper_id",
        )
        for field in ("reading_priority", "reproduction_priority"):
            if priority.get(field) not in {"low", "medium", "high"}:
                raise ValueError(f"{field} must be low, medium, or high.")
    for tension in _object_list(
        synthesis.get("conflicts_or_tensions"),
        "conflicts_or_tensions",
    ):
        _validate_paper_ids(
            tension.get("paper_ids"),
            allowed_paper_ids,
            "conflicts_or_tensions",
        )
    return synthesis


def render_synthesis_markdown(
    synthesis: dict[str, Any],
    *,
    records: list[dict[str, Any]],
) -> str:
    titles = {str(record["paper_id"]): str(record.get("title", "")) for record in records}
    lines = [
        "# Research Synthesis",
        "",
        "## Overview",
        "",
        _clean_text(synthesis.get("overview")) or "No overview generated.",
        "",
        "## Topic Groups",
        "",
    ]
    for group in _object_list(synthesis.get("topic_groups"), "topic_groups"):
        lines.extend(
            [
                f"### {_clean_text(group.get('name')) or 'Unnamed group'}",
                "",
                _clean_text(group.get("description")),
                "",
                f"Papers: {_format_papers(group.get('paper_ids'), titles)}",
                "",
            ]
        )
        takeaways = _string_list(group.get("key_takeaways"))
        if takeaways:
            lines.append("Key takeaways:")
            lines.extend(f"- {item}" for item in takeaways)
            lines.append("")

    lines.extend(["## Method Comparison", ""])
    for method in _object_list(
        synthesis.get("method_comparison"),
        "method_comparison",
    ):
        lines.extend(
            [
                f"### {_clean_text(method.get('method')) or 'Unnamed method'}",
                "",
                f"Papers: {_format_papers(method.get('paper_ids'), titles)}",
                "",
                f"Problem addressed: {_clean_text(method.get('problem_addressed'))}",
                "",
                f"Core idea: {_clean_text(method.get('core_idea'))}",
                "",
            ]
        )
        strengths = _string_list(method.get("strengths"))
        if strengths:
            lines.append("Strengths:")
            lines.extend(f"- {item}" for item in strengths)
            lines.append("")
        limitations = _string_list(method.get("limitations"))
        if limitations:
            lines.append("Limitations:")
            lines.extend(f"- {item}" for item in limitations)
            lines.append("")

    lines.extend(["## Evidence Matrix", ""])
    for evidence in _object_list(synthesis.get("evidence_matrix"), "evidence_matrix"):
        lines.extend(
            [
                f"- {_clean_text(evidence.get('claim'))}",
                f"  Strength: {_clean_text(evidence.get('evidence_strength'))}",
                f"  Supporting: {_format_papers(evidence.get('supporting_papers'), titles)}",
                f"  Contradicting: {_format_papers(evidence.get('contradicting_papers'), titles)}",
                f"  Notes: {_clean_text(evidence.get('notes'))}",
            ]
        )

    lines.extend(["", "## Claim-Level Evidence Matrix", ""])
    for claim in _object_list(
        synthesis.get("claim_evidence_matrix"),
        "claim_evidence_matrix",
    ):
        lines.extend(
            [
                f"### {_clean_text(claim.get('claim'))}",
                "",
                f"Strength: {_clean_text(claim.get('evidence_strength'))}",
                "",
                f"Uncertainty: {_clean_text(claim.get('uncertainty'))}",
                "",
            ]
        )
        supporting = _object_list(
            claim.get("supporting_evidence"),
            "claim_evidence_matrix.supporting_evidence",
        )
        if supporting:
            lines.append("Supporting evidence:")
            lines.extend(f"- {_format_claim_evidence(item, titles)}" for item in supporting)
            lines.append("")
        contradicting = _object_list(
            claim.get("contradicting_evidence"),
            "claim_evidence_matrix.contradicting_evidence",
        )
        if contradicting:
            lines.append("Contradicting evidence:")
            lines.extend(f"- {_format_claim_evidence(item, titles)}" for item in contradicting)
            lines.append("")

    lines.extend(["## Method Family Tree", ""])
    for family in _object_list(synthesis.get("method_family_tree"), "method_family_tree"):
        lines.extend(
            [
                f"### {_clean_text(family.get('family')) or 'Unnamed family'}",
                "",
                _clean_text(family.get("description")),
                "",
            ]
        )
        for method in _object_list(family.get("methods"), "method_family_tree.methods"):
            lines.append(
                f"- {_clean_text(method.get('name'))}: {_clean_text(method.get('role'))}"
            )
            lines.append(f"  Papers: {_format_papers(method.get('paper_ids'), titles)}")
            related = _string_list(method.get("related_methods"))
            if related:
                lines.append(f"  Related methods: {', '.join(related)}")
        lines.append("")

    lines.extend(["## Benchmark Matrix", ""])
    for benchmark in _object_list(synthesis.get("benchmark_matrix"), "benchmark_matrix"):
        lines.extend(
            [
                f"### {_format_papers([benchmark.get('paper_id')], titles)}",
                "",
                f"- Benchmarks/datasets: {', '.join(_string_list(benchmark.get('benchmarks_or_datasets'))) or 'not specified'}",
                f"- Metrics: {', '.join(_string_list(benchmark.get('metrics'))) or 'not specified'}",
                f"- Baselines: {', '.join(_string_list(benchmark.get('baselines'))) or 'not specified'}",
                f"- Reported result: {_clean_text(benchmark.get('reported_result'))}",
                f"- Comparability notes: {_clean_text(benchmark.get('comparability_notes'))}",
                "",
            ]
        )

    lines.extend(["## Reading And Reproduction Priority", ""])
    priority_order = {"high": 0, "medium": 1, "low": 2}
    priorities = sorted(
        _object_list(
            synthesis.get("reading_reproduction_priority"),
            "reading_reproduction_priority",
        ),
        key=lambda item: (
            priority_order.get(str(item.get("reading_priority")), 9),
            priority_order.get(str(item.get("reproduction_priority")), 9),
            str(item.get("paper_id")),
        ),
    )
    for priority in priorities:
        lines.extend(
            [
                f"### {_format_papers([priority.get('paper_id')], titles)}",
                "",
                f"- Reading priority: {_clean_text(priority.get('reading_priority'))}",
                f"- Reproduction priority: {_clean_text(priority.get('reproduction_priority'))}",
                f"- Reason: {_clean_text(priority.get('reason'))}",
                f"- Suggested action: {_clean_text(priority.get('suggested_action'))}",
                "",
            ]
        )

    lines.extend(["", "## Conflicts Or Tensions", ""])
    tensions = _object_list(synthesis.get("conflicts_or_tensions"), "conflicts_or_tensions")
    if tensions:
        for tension in tensions:
            lines.extend(
                [
                    f"- {_clean_text(tension.get('issue'))}",
                    f"  Papers: {_format_papers(tension.get('paper_ids'), titles)}",
                    f"  Explanation: {_clean_text(tension.get('explanation'))}",
                ]
            )
    else:
        lines.append("No explicit conflicts or tensions were generated.")

    lines.extend(["", "## Research Gaps", ""])
    lines.extend(f"- {item}" for item in _string_list(synthesis.get("research_gaps")))
    lines.extend(["", "## Recommended Next Steps", ""])
    lines.extend(
        f"- {item}" for item in _string_list(synthesis.get("recommended_next_steps"))
    )
    return "\n".join(lines).rstrip() + "\n"


def format_synthesis_result(result: SynthesisResult) -> str:
    return "\n".join(
        [
            f"Research folder: {result.root}",
            f"Catalog: {result.catalog_path or 'not written'}",
            f"Synthesis artifact: {result.artifact_path or 'not written'}",
            f"Markdown: {result.markdown_path or 'not written'}",
            (
                "Research synthesis: "
                f"{result.paper_count} papers, "
                f"cached={'yes' if result.cached else 'no'}, "
                f"usage={_format_usage(result.usage)}"
            ),
        ]
    )


def _synthesis_input(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    payload = []
    for record in records:
        summary = record.get("summary")
        if not isinstance(summary, dict):
            continue
        payload.append(
            {
                "paper_id": record.get("paper_id"),
                "title": record.get("title"),
                "source_file": record.get("source_file"),
                "summary_short": summary.get("summary_short"),
                "research_question": summary.get("research_question"),
                "methods": _string_list(summary.get("methods"))[:8],
                "findings": _finding_claims(summary.get("findings"))[:8],
                "limitations": _string_list(summary.get("limitations"))[:6],
                "key_terms": _string_list(summary.get("key_terms"))[:10],
                "implementation_notes": _string_list(
                    summary.get("implementation_notes")
                )[:6],
                "summary_findings": _summary_findings(summary.get("findings"))[:10],
            }
        )
    return payload


def _can_use_cached_artifact(
    artifact: dict[str, Any],
    *,
    input_sha256: str,
    provider: JsonCompletionProvider,
) -> bool:
    return (
        artifact.get("schema_version") == SYNTHESIS_SCHEMA_VERSION
        and artifact.get("prompt_version") == SYNTHESIS_PROMPT_VERSION
        and artifact.get("input_sha256") == input_sha256
        and artifact.get("provider") == provider.provider_name
        and artifact.get("model") == provider.model
        and isinstance(artifact.get("synthesis"), dict)
    )


def _object_list(value: Any, field: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError(f"Synthesis field {field} must be a list.")
    objects = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError(f"Synthesis field {field} items must be objects.")
        objects.append(item)
    return objects


def _validate_paper_ids(value: Any, allowed_paper_ids: set[str], field: str) -> None:
    if not isinstance(value, list):
        raise ValueError(f"Synthesis field {field} must be a list.")
    if any(item is None or str(item).strip() == "" for item in value):
        raise ValueError(f"Synthesis field {field} contains empty paper ids.")
    invalid = [str(item) for item in value if str(item) not in allowed_paper_ids]
    if invalid:
        raise ValueError(f"Synthesis field {field} contains unknown paper ids.")


def _string_list_required(value: Any, field: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"Synthesis field {field} must be a list.")
    strings = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"Synthesis field {field} items must be strings.")
        text = item.strip()
        if text:
            strings.append(text)
    return strings


def _finding_claims(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    claims = []
    for item in value:
        claim = item.get("claim") if isinstance(item, dict) else item
        text = _clean_text(claim)
        if text:
            claims.append(text)
    return claims


def _summary_findings(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    findings = []
    for item in value:
        if not isinstance(item, dict):
            continue
        claim = _clean_text(item.get("claim"))
        if not claim:
            continue
        citations = item.get("citations", [])
        findings.append(
            {
                "claim": claim,
                "citations": [str(citation) for citation in citations]
                if isinstance(citations, list)
                else [],
                "inference": item.get("inference") is True,
            }
        )
    return findings


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_clean_text(item) for item in value if _clean_text(item)]


def _clean_text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _format_papers(value: Any, titles: dict[str, str]) -> str:
    if not isinstance(value, list) or not value:
        return "none"
    parts = []
    for item in value:
        paper_id = str(item)
        title = titles.get(paper_id, "")
        parts.append(f"`{paper_id}`" + (f" ({title})" if title else ""))
    return ", ".join(parts)


def _format_claim_evidence(evidence: dict[str, Any], titles: dict[str, str]) -> str:
    paper = _format_papers([evidence.get("paper_id")], titles)
    evidence_type = _clean_text(evidence.get("evidence_type"))
    finding = _clean_text(evidence.get("summary_finding"))
    citations = _string_list(evidence.get("original_citations"))
    citation_text = f" Citations: {', '.join(citations)}." if citations else ""
    return f"{paper} [{evidence_type}] {finding}.{citation_text}"


def _format_usage(usage: dict[str, int]) -> str:
    return ", ".join(f"{key}={value}" for key, value in sorted(usage.items())) or "none"


def _sha256_json(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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
