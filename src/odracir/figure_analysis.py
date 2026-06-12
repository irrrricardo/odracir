"""Structured, review-first scientific figure analysis."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from odracir.research_folder import ResearchFolderHarness
from odracir.schemas import FIGURE_ANALYSIS_SCHEMA_VERSION
from odracir.time_utils import now_iso
from odracir.vision_providers import VisionAnalysisProvider


FIGURE_ANALYSIS_PROMPT_VERSION = "0.6"
FIGURE_ANALYSIS_MAX_TOKENS = 7000
CONSISTENCY_VALUES = {"consistent", "conflicting", "uncertain"}
SUPPORT_LEVELS = {"direct_visual", "source_supported", "inference", "unsupported"}
EVIDENCE_SOURCES = {"image", "figure_text", "caption", "nearby_text", "combined"}
FIGURE_TYPES = {
    "statistical_chart",
    "flow_diagram",
    "mechanism_diagram",
    "table",
    "microscopy",
    "pathology",
    "radiology",
    "medical_image",
    "photograph",
    "compound_figure",
    "other",
}
ANALYSIS_PROFILES = {
    "chart": "Recover axes, units, series, legible values, extrema, ordering, trends, and comparisons.",
    "table": "Recover headers, row/column relations, values, best/worst results, and significance symbols.",
    "diagram": "Recover nodes, directed edges, inputs, outputs, stages, mechanisms, and dependencies.",
    "biomedical": "Recover visible objects, regions, spatial relations, counts, measurements, and group differences without diagnosis.",
    "general": "Recover visible entities, relations, comparisons, measurements, and supported conclusions.",
}

FIGURE_ANALYSIS_SYSTEM_PROMPT = """You extract scientific evidence from one
figure candidate. Return one JSON object only. The goal is not to paraphrase the
caption. Recover the scientific question, entities, variables, comparisons,
quantitative findings, trends, and conclusions that the image can support.

First classify the figure. For statistical charts, recover axes, units, series,
relative ordering, extrema, trends, and legible values. For tables, recover
headers, row/column meaning, comparisons, best/worst results, and significance
symbols. For flow or mechanism diagrams, recover nodes, directed relations,
inputs, outputs, stages, and mechanisms. For biomedical images, report visible
objects, regions, spatial relations, counts, or measurements only when visible;
never make a clinical diagnosis. Never invent precise values or relations.

Every evidence item must state its support level:
- direct_visual: directly visible in the image.
- source_supported: explicitly supported by caption, figure text, or supplied
  paper context and consistent with the image.
- inference: plausible interpretation not directly established.
- unsupported: contradicted, illegible, or missing.

Only direct_visual and source_supported items are eligible for the downstream
evidence catalog. Keep uncertainty explicit.
Use this shape:
{
  "figure_type": "statistical_chart|flow_diagram|mechanism_diagram|table|microscopy|pathology|radiology|medical_image|photograph|compound_figure|other",
  "scientific_question": "question addressed by the figure",
  "entities": [{"name": "string", "role": "string"}],
  "variables": [{"name": "string", "role": "independent|dependent|control|metric|unknown", "unit": "string"}],
  "comparisons": [{"subjects": ["string"], "basis": "string", "result": "string"}],
  "quantitative_findings": [{"subject": "string", "metric": "string", "value": "string", "condition": "string"}],
  "trends": [{"subject": "string", "trend": "string", "condition": "string"}],
  "observations": ["directly visible statement"],
  "caption_supported_findings": ["finding explicitly supported by caption or nearby text"],
  "inferences": ["clearly marked model inference"],
  "supported_conclusions": ["conclusion supported by direct_visual or source_supported evidence"],
  "evidence_items": [
    {
      "claim": "atomic scientific fact or conclusion",
      "support_level": "direct_visual|source_supported|inference|unsupported",
      "source": "image|figure_text|caption|nearby_text|combined",
      "evidence_detail": "specific visual feature, value, row, curve, region, or source phrase",
      "confidence": 0.0
    }
  ],
  "uncertainties": ["uncertainty or missing information"],
  "limitations": ["what the figure cannot establish"],
  "text_image_consistency": "consistent|conflicting|uncertain",
  "confidence": 0.0,
  "safety_flags": ["string"]
}
"""


@dataclass(frozen=True)
class FigureAnalysisSummary:
    root: str
    total_figures: int
    analyzed: int
    skipped: int
    failed: int
    usage: dict[str, int]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class FigureAnalysisHarness:
    """Analyze extracted figure candidates without promoting them to evidence."""

    def __init__(
        self,
        root: str | Path,
        provider: VisionAnalysisProvider,
        papers_dir: str | Path | None = None,
    ) -> None:
        self.harness = ResearchFolderHarness(root, papers_dir=papers_dir)
        self.root = self.harness.root
        self.provider = provider
        self.analysis_dir = self.root / ".odracir" / "figure-analyses"

    def analyze(
        self,
        *,
        force: bool = False,
        limit: int | None = None,
        paper_id: str | None = None,
        include_subfigures: bool = False,
    ) -> FigureAnalysisSummary:
        self.harness.sync_index()
        index = self.harness.load_index()
        candidates = self._candidates(
            index,
            paper_id=paper_id,
            include_subfigures=include_subfigures,
        )
        if limit is not None:
            candidates = candidates[:limit]

        analyzed = skipped = failed = 0
        usage: dict[str, int] = {}
        for paper, figure in candidates:
            artifact_path = self._artifact_path(paper, figure)
            input_sha256 = _analysis_input_sha256(figure, self.provider)
            if not force and _current_artifact(artifact_path, input_sha256):
                skipped += 1
                continue
            try:
                analysis_image = figure.get("region_render_path") or figure["image_path"]
                image_path = self.root / str(analysis_image)
                response = self.provider.analyze_json(
                    image_path=image_path,
                    system_prompt=FIGURE_ANALYSIS_SYSTEM_PROMPT,
                    user_prompt=_user_prompt(paper, figure),
                    max_tokens=FIGURE_ANALYSIS_MAX_TOKENS,
                )
                analysis = validate_figure_analysis(response.payload)
                artifact = {
                    "schema_version": FIGURE_ANALYSIS_SCHEMA_VERSION,
                    "prompt_version": FIGURE_ANALYSIS_PROMPT_VERSION,
                    "generated_at": now_iso(),
                    "input_sha256": input_sha256,
                    "paper_id": paper["id"],
                    "figure_id": figure["figure_id"],
                    "parent_figure_id": figure.get("parent_figure_id"),
                    "subfigure_label": figure.get("subfigure_label"),
                    "figure_artifact": paper["figure_artifact"],
                    "image_path": figure["image_path"],
                    "image_sha256": figure["image_sha256"],
                    "analysis_image_path": str(analysis_image),
                    "analysis_image_sha256": figure.get(
                        "region_render_sha256",
                        figure["image_sha256"],
                    ),
                    "provider": self.provider.provider_name,
                    "model": self.provider.model,
                    "verification_mode": getattr(
                        self.provider,
                        "verification_mode",
                        "single_model",
                    ),
                    "usage": response.usage,
                    "provider_trace": response.metadata,
                    "status": "completed",
                    "analysis": analysis,
                }
                _write_json(artifact_path, artifact)
                analyzed += 1
                _merge_usage(usage, response.usage)
            except Exception as exc:  # noqa: BLE001 - isolate per-figure failures.
                _write_json(
                    artifact_path,
                    {
                        "schema_version": FIGURE_ANALYSIS_SCHEMA_VERSION,
                        "prompt_version": FIGURE_ANALYSIS_PROMPT_VERSION,
                        "generated_at": now_iso(),
                        "input_sha256": input_sha256,
                        "paper_id": paper.get("id"),
                        "figure_id": figure.get("figure_id"),
                        "parent_figure_id": figure.get("parent_figure_id"),
                        "subfigure_label": figure.get("subfigure_label"),
                        "image_path": figure.get("image_path"),
                        "image_sha256": figure.get("image_sha256"),
                        "provider": self.provider.provider_name,
                        "model": self.provider.model,
                        "verification_mode": getattr(
                            self.provider,
                            "verification_mode",
                            "single_model",
                        ),
                        "status": "failed",
                        "error": str(exc),
                    },
                )
                failed += 1
        return FigureAnalysisSummary(
            root=str(self.root),
            total_figures=len(candidates),
            analyzed=analyzed,
            skipped=skipped,
            failed=failed,
            usage=usage,
        )

    def _candidates(
        self,
        index: dict[str, Any],
        *,
        paper_id: str | None,
        include_subfigures: bool,
    ) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        candidates: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for paper in index.get("papers", []):
            if not isinstance(paper, dict) or (
                paper_id is not None and paper.get("id") != paper_id
            ):
                continue
            manifest_path = paper.get("figure_artifact")
            if not isinstance(manifest_path, str):
                continue
            manifest = _load_json(self.root / manifest_path)
            for figure in manifest.get("figures", []):
                if isinstance(figure, dict):
                    candidates.append((paper, figure))
                    if include_subfigures:
                        candidates.extend(
                            (paper, subfigure)
                            for subfigure in _subfigure_candidates(figure)
                        )
        return candidates

    def _artifact_path(
        self,
        paper: dict[str, Any],
        figure: dict[str, Any],
    ) -> Path:
        return (
            self.analysis_dir
            / str(paper["id"])
            / f"{figure['figure_id']}.json"
        )


def validate_figure_analysis(payload: dict[str, Any]) -> dict[str, Any]:
    for field in (
        "figure_type",
        "scientific_question",
        "entities",
        "variables",
        "comparisons",
        "quantitative_findings",
        "trends",
        "observations",
        "caption_supported_findings",
        "inferences",
        "supported_conclusions",
        "evidence_items",
        "uncertainties",
        "limitations",
        "text_image_consistency",
        "confidence",
        "safety_flags",
    ):
        if field not in payload:
            raise ValueError(f"Figure analysis is missing field: {field}.")
    if payload["figure_type"] not in FIGURE_TYPES:
        raise ValueError("Figure analysis figure_type is invalid.")
    if not isinstance(payload["scientific_question"], str):
        raise ValueError("Figure analysis scientific_question must be a string.")
    for field in (
        "observations",
        "caption_supported_findings",
        "inferences",
        "supported_conclusions",
        "uncertainties",
        "limitations",
        "safety_flags",
    ):
        if not isinstance(payload[field], list) or not all(
            isinstance(item, str) for item in payload[field]
        ):
            raise ValueError(f"Figure analysis field {field} must be a string list.")
    for field in (
        "entities",
        "variables",
        "comparisons",
        "quantitative_findings",
        "trends",
    ):
        if not isinstance(payload[field], list) or not all(
            isinstance(item, dict) for item in payload[field]
        ):
            raise ValueError(f"Figure analysis field {field} must be an object list.")
    _validate_object_list(payload["entities"], "entities", ("name", "role"))
    _validate_object_list(payload["variables"], "variables", ("name", "role", "unit"))
    _validate_comparisons(payload["comparisons"])
    _validate_object_list(
        payload["quantitative_findings"],
        "quantitative_findings",
        ("subject", "metric", "value", "condition"),
    )
    _validate_object_list(payload["trends"], "trends", ("subject", "trend", "condition"))
    _validate_evidence_items(payload["evidence_items"])
    if payload["text_image_consistency"] not in CONSISTENCY_VALUES:
        raise ValueError("Figure analysis text_image_consistency is invalid.")
    confidence = payload["confidence"]
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        raise ValueError("Figure analysis confidence must be numeric.")
    if not 0 <= float(confidence) <= 1:
        raise ValueError("Figure analysis confidence must be between 0 and 1.")
    return payload


def _validate_evidence_items(value: Any) -> None:
    if not isinstance(value, list):
        raise ValueError("Figure analysis evidence_items must be an object list.")
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("Each figure evidence item must be an object.")
        for field in ("claim", "support_level", "source", "evidence_detail", "confidence"):
            if field not in item:
                raise ValueError(f"Figure evidence item is missing field: {field}.")
        if not isinstance(item["claim"], str) or not item["claim"].strip():
            raise ValueError("Figure evidence item claim must be a non-empty string.")
        if item["support_level"] not in SUPPORT_LEVELS:
            raise ValueError("Figure evidence item support_level is invalid.")
        if not isinstance(item["source"], str) or not isinstance(
            item["evidence_detail"], str
        ):
            raise ValueError("Figure evidence item source and detail must be strings.")
        if item["source"] not in EVIDENCE_SOURCES:
            raise ValueError("Figure evidence item source is invalid.")
        if not item["evidence_detail"].strip():
            raise ValueError("Figure evidence item detail must be non-empty.")
        if (
            item["support_level"] == "direct_visual"
            and item["source"] not in {"image", "combined"}
        ):
            raise ValueError("Direct visual evidence must cite image or combined source.")
        if (
            item["support_level"] == "source_supported"
            and item["source"] not in {"figure_text", "caption", "nearby_text", "combined"}
        ):
            raise ValueError("Source-supported evidence must cite supplied source context.")
        confidence = item["confidence"]
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
            raise ValueError("Figure evidence item confidence must be numeric.")
        if not 0 <= float(confidence) <= 1:
            raise ValueError("Figure evidence item confidence must be between 0 and 1.")


def _validate_object_list(
    value: list[dict[str, Any]],
    name: str,
    required_fields: tuple[str, ...],
) -> None:
    for item in value:
        for field in required_fields:
            if field not in item or not isinstance(item[field], str):
                raise ValueError(f"Figure analysis {name} item requires string {field}.")


def _validate_comparisons(value: list[dict[str, Any]]) -> None:
    for item in value:
        subjects = item.get("subjects")
        if not isinstance(subjects, list) or not all(
            isinstance(subject, str) and subject.strip() for subject in subjects
        ):
            raise ValueError("Figure analysis comparison subjects must be strings.")
        for field in ("basis", "result"):
            if not isinstance(item.get(field), str):
                raise ValueError(f"Figure analysis comparison requires string {field}.")


def _user_prompt(paper: dict[str, Any], figure: dict[str, Any]) -> str:
    profile = _analysis_profile(figure)
    context = {
        "paper_id": paper.get("id"),
        "paper_title": paper.get("title"),
        "page_number": figure.get("page_number"),
        "figure_label": figure.get("figure_label"),
        "parent_figure_id": figure.get("parent_figure_id"),
        "subfigure_label": figure.get("subfigure_label"),
        "subfigure_caption": figure.get("subfigure_caption"),
        "caption": figure.get("caption"),
        "figure_text": _bounded_list(figure.get("figure_text", [])),
        "figure_text_elements": _bounded_list(
            figure.get("figure_text_elements", []),
            max_items=200,
            max_chars=20_000,
        ),
        "subfigure_hints": _bounded_list(figure.get("subfigures", []), max_items=30),
        "nearby_text": _bounded_list(figure.get("nearby_text", [])),
        "inline_references": _bounded_list(figure.get("inline_references", [])),
        "analysis_profile": profile,
        "profile_requirements": ANALYSIS_PROFILES[profile],
    }
    return (
        "Analyze the image pixels first. Use context only to identify labels and "
        "check consistency; do not copy context into evidence unless the image "
        "supports it.\n"
        f"Figure analysis request JSON:\n{json.dumps(context, ensure_ascii=False)}"
    )


def _bounded_list(value: Any, *, max_items: int = 30, max_chars: int = 30_000) -> list[Any]:
    if not isinstance(value, list):
        return []
    result: list[Any] = []
    size = 0
    for item in value[:max_items]:
        encoded = json.dumps(item, ensure_ascii=False)
        if size + len(encoded) > max_chars:
            break
        result.append(item)
        size += len(encoded)
    return result


def _subfigure_candidates(figure: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for ordinal, subfigure in enumerate(figure.get("subfigures", []), start=1):
        if not isinstance(subfigure, dict) or not isinstance(
            subfigure.get("image_path"),
            str,
        ):
            continue
        candidate = dict(figure)
        label = str(subfigure.get("label") or f"panel-{ordinal}")
        bbox = subfigure.get("bbox", [])
        candidate.update(
            {
                "figure_id": f"{figure['figure_id']}-s{ordinal:03d}",
                "parent_figure_id": figure["figure_id"],
                "subfigure_label": label,
                "figure_label": f"{figure.get('figure_label', '')} {label}".strip(),
                "subfigure_caption": _subfigure_caption_context(
                    str(figure.get("caption", "")),
                    label,
                ),
                "kind": "subfigure",
                "image_path": subfigure["image_path"],
                "region_render_path": subfigure["image_path"],
                "image_sha256": subfigure.get("image_sha256", ""),
                "region_render_sha256": subfigure.get("image_sha256", ""),
                "bounding_box": bbox,
                "figure_text_elements": _elements_in_bbox(
                    figure.get("figure_text_elements", []),
                    bbox,
                ),
                "figure_text": [
                    str(element.get("text", ""))
                    for element in _elements_in_bbox(
                        figure.get("figure_text_elements", []),
                        bbox,
                    )
                    if str(element.get("text", "")).strip()
                ],
                "subfigures": [],
            }
        )
        candidates.append(candidate)
    return candidates


def _elements_in_bbox(elements: Any, bbox: Any) -> list[dict[str, Any]]:
    if not isinstance(elements, list) or not isinstance(bbox, list) or len(bbox) != 4:
        return []
    selected: list[dict[str, Any]] = []
    for element in elements:
        element_bbox = element.get("bbox") if isinstance(element, dict) else None
        if not isinstance(element_bbox, list) or len(element_bbox) != 4:
            continue
        center_x = (float(element_bbox[0]) + float(element_bbox[2])) / 2
        center_y = (float(element_bbox[1]) + float(element_bbox[3])) / 2
        if bbox[0] <= center_x <= bbox[2] and bbox[1] <= center_y <= bbox[3]:
            selected.append(element)
    return selected


def _subfigure_caption_context(caption: str, label: str) -> str:
    match = re.fullmatch(r"\(([a-z])\)", label.lower())
    if not match:
        return ""
    key = match.group(1)
    pattern = re.compile(
        rf"(?:\({key}\)|\b{key}[.)])\s*(.*?)(?=\s*(?:\([a-z]\)|\b[a-z][.)])\s|$)",
        flags=re.IGNORECASE | re.DOTALL,
    )
    context = pattern.search(caption)
    return context.group(1).strip(" ;,.") if context else ""


def _analysis_profile(figure: dict[str, Any]) -> str:
    label = str(figure.get("figure_label", "")).lower()
    caption = str(figure.get("caption", "")).lower()
    kind = str(figure.get("kind", "")).lower()
    figure_text = " ".join(str(item) for item in figure.get("figure_text", []))
    combined = f"{label} {caption} {kind} {figure_text.lower()}"
    if label.startswith("table") or "table" in kind:
        return "table"
    if any(term in combined for term in ("convergence", "curve", "plot", "chart", "bar ")):
        return "chart"
    if any(term in combined for term in ("workflow", "procedure", "mechanism", "diagram")):
        return "diagram"
    if any(
        term in combined
        for term in (
            "cell",
            "tissue",
            "microscopy",
            "pathology",
            "radiology",
            "medical",
            "mri",
            "ct ",
        )
    ):
        return "biomedical"
    return "general"


def _analysis_input_sha256(
    figure: dict[str, Any],
    provider: VisionAnalysisProvider,
) -> str:
    payload = {
        "prompt_version": FIGURE_ANALYSIS_PROMPT_VERSION,
        "provider": provider.provider_name,
        "model": provider.model,
        "figure_id": figure.get("figure_id"),
        "image_sha256": figure.get("image_sha256"),
        "region_render_sha256": figure.get("region_render_sha256"),
        "caption": figure.get("caption"),
        "figure_text": figure.get("figure_text", []),
        "figure_text_elements": figure.get("figure_text_elements", []),
        "subfigures": figure.get("subfigures", []),
        "subfigure_caption": figure.get("subfigure_caption"),
        "nearby_text": figure.get("nearby_text", []),
        "inline_references": figure.get("inline_references", []),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _current_artifact(path: Path, input_sha256: str) -> bool:
    if not path.is_file():
        return False
    try:
        artifact = _load_json(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    return (
        artifact.get("status") == "completed"
        and artifact.get("input_sha256") == input_sha256
    )


def _merge_usage(total: dict[str, int], usage: dict[str, int]) -> None:
    for key, value in usage.items():
        total[key] = total.get(key, 0) + value


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
