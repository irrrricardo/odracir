"""Human-readable project briefs built from research catalog memory."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from odracir.research_memory import ResearchCatalogBuilder, ResearchCatalogBuildResult


DEFAULT_BRIEF_NAME = "project_summary.md"


@dataclass(frozen=True)
class ProjectBriefResult:
    root: str
    catalog_path: str | None
    brief_path: str | None
    total_papers: int
    quality_counts: dict[str, int]
    written: bool
    markdown: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class ProjectBriefBuilder:
    """Render the folder-level catalog as a compact Markdown reading brief."""

    def __init__(
        self,
        root: str | Path,
        papers_dir: str | Path | None = None,
        *,
        output_name: str = DEFAULT_BRIEF_NAME,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.papers_dir = papers_dir
        self.output_path = self.root / output_name

    def build(
        self,
        *,
        write_artifact: bool = True,
        rebuild_catalog: bool = True,
    ) -> ProjectBriefResult:
        catalog = ResearchCatalogBuilder(
            self.root,
            papers_dir=self.papers_dir,
        ).build(write_artifact=rebuild_catalog)
        markdown = render_project_brief(catalog)
        if write_artifact:
            self.output_path.parent.mkdir(parents=True, exist_ok=True)
            self.output_path.write_text(markdown, encoding="utf-8", newline="\n")
        return ProjectBriefResult(
            root=str(self.root),
            catalog_path=catalog.catalog_path,
            brief_path=str(self.output_path) if write_artifact else None,
            total_papers=catalog.total_papers,
            quality_counts=catalog.quality_counts,
            written=write_artifact,
            markdown=markdown,
        )


def render_project_brief(catalog: ResearchCatalogBuildResult) -> str:
    lines = [
        f"# Research Brief: {Path(catalog.root).name}",
        "",
        "## Overview",
        "",
        f"- Papers: {catalog.total_papers}",
        f"- Memory quality: {_format_counts(catalog.quality_counts)}",
        f"- Catalog: {catalog.catalog_path or 'not written'}",
        f"- Generated at: {catalog.generated_at}",
        "",
        "## Papers",
        "",
    ]
    if not catalog.records:
        lines.append("No papers are currently recorded.")
        lines.append("")
        return "\n".join(lines)

    for index, record in enumerate(catalog.records, start=1):
        summary = record.get("summary") if isinstance(record, dict) else None
        title = str(record.get("title") or record.get("paper_id") or "Untitled")
        quality = _nested_string(record, "memory_quality", "status", default="unknown")
        source_file = str(record.get("source_file") or "")
        lines.extend(
            [
                f"### {index}. {title}",
                "",
                f"- Paper id: `{record.get('paper_id', '')}`",
                f"- Source: `{source_file}`",
                f"- Quality: {quality}",
            ]
        )
        if not isinstance(summary, dict):
            errors = _nested_list(record, "memory_quality", "errors")
            lines.append("- Summary: unavailable")
            if errors:
                lines.append(f"- Blocking issue: {errors[0]}")
            lines.append("")
            continue

        short = _clean_text(summary.get("summary_short"))
        question = _clean_text(summary.get("research_question"))
        detailed = _clean_text(summary.get("summary_detailed"))
        if short:
            lines.extend(["", short])
        if question:
            lines.extend(["", f"Research question: {question}"])
        methods = _string_list(summary.get("methods"))
        if methods:
            lines.extend(["", "Methods:"])
            lines.extend(f"- {item}" for item in methods[:5])
        findings = _finding_claims(summary.get("findings"))
        if findings:
            lines.extend(["", "Key findings:"])
            lines.extend(f"- {item}" for item in findings[:5])
        limitations = _string_list(summary.get("limitations"))
        if limitations:
            lines.extend(["", "Limitations:"])
            lines.extend(f"- {item}" for item in limitations[:4])
        if detailed and detailed != short:
            lines.extend(["", "Detailed note:", "", detailed])
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def format_project_brief(result: ProjectBriefResult) -> str:
    lines = [
        f"Research folder: {result.root}",
        f"Catalog: {result.catalog_path or 'not written'}",
        f"Brief: {result.brief_path or 'not written'}",
        (
            "Project brief: "
            f"{result.total_papers} papers, "
            f"{_format_counts(result.quality_counts)}"
        ),
    ]
    if not result.written:
        lines.extend(["", result.markdown])
    return "\n".join(lines)


def _format_counts(counts: dict[str, int]) -> str:
    return ", ".join(f"{key}={value}" for key, value in sorted(counts.items())) or "none"


def _clean_text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_clean_text(item) for item in value if _clean_text(item)]


def _finding_claims(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    claims: list[str] = []
    for item in value:
        if isinstance(item, dict):
            claim = _clean_text(item.get("claim"))
        else:
            claim = _clean_text(item)
        if claim:
            claims.append(claim)
    return claims


def _nested_string(
    value: dict[str, Any],
    parent: str,
    child: str,
    *,
    default: str,
) -> str:
    nested = value.get(parent)
    if not isinstance(nested, dict):
        return default
    return str(nested.get(child) or default)


def _nested_list(value: dict[str, Any], parent: str, child: str) -> list[str]:
    nested = value.get(parent)
    if not isinstance(nested, dict):
        return []
    return _string_list(nested.get(child))
