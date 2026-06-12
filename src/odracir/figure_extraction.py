"""Traceable figure extraction from research PDFs."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from odracir.processing_state import invalidate_figure_extraction
from odracir.research_folder import ResearchFolderHarness
from odracir.schemas import FIGURE_ARTIFACT_SCHEMA_VERSION
from odracir.time_utils import now_iso


FIGURE_EXTRACTOR_NAME = "pymupdf"
FIGURE_EXTRACTOR_VERSION = "0.9"
MIN_FIGURE_WIDTH = 80
MIN_FIGURE_HEIGHT = 80
MIN_GRAPHIC_COMPONENT_SIZE = 20
MAX_CAPTION_GRAPHIC_DISTANCE = 360
MAX_ADJACENT_COMPONENT_GAP = 90
MAX_FIGURE_TEXT_GAP = 28
MAX_CAPTION_COLUMN_GAP = 140
CAPTION_LABEL_PATTERN = re.compile(
    r"^\s*((?:(?:supplementary\s+)?fig(?:ure)?|table)\.?\s*[A-Z]?\d+[A-Z]?)"
    r"[\s:.\-]*(.*)$",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True)
class FigureExtractionSummary:
    root: str
    index_path: str
    total_pdf_papers: int
    extracted: int
    skipped: int
    failed: int
    figures: int
    page_render_fallbacks: int
    missing_labels: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class PdfFigureExtractor:
    """Extract caption-matched figures with traceable page renders."""

    def __init__(
        self,
        root: str | Path,
        papers_dir: str | Path | None = None,
        *,
        render_scale: float = 2.0,
    ) -> None:
        if render_scale <= 0:
            raise ValueError("render_scale must be positive.")
        self.harness = ResearchFolderHarness(root, papers_dir=papers_dir)
        self.root = self.harness.root
        self.figures_dir = self.root / ".odracir" / "figures"
        self.render_scale = render_scale

    def extract_index(
        self,
        *,
        force: bool = False,
        limit: int | None = None,
        paper_id: str | None = None,
    ) -> FigureExtractionSummary:
        self.harness.sync_index()
        self.figures_dir.mkdir(parents=True, exist_ok=True)
        index = self.harness.load_index()
        pdf_records = [
            paper
            for paper in index.get("papers", [])
            if isinstance(paper, dict)
            and paper.get("file_type") == "pdf"
            and paper.get("status") != "missing"
            and (paper_id is None or paper.get("id") == paper_id)
        ]
        if limit is not None:
            pdf_records = pdf_records[:limit]

        extracted = skipped = failed = figures = page_render_fallbacks = missing_labels = 0
        for paper in pdf_records:
            artifact_path = self._artifact_path(paper)
            try:
                source_path = self.root / str(paper["source_file"])
                source_sha256 = _sha256_file(source_path)
                if self._can_skip(paper, artifact_path, source_sha256, force):
                    artifact = _read_json(artifact_path)
                    skipped += 1
                    figures += int(artifact["figure_count"])
                    page_render_fallbacks += int(artifact["page_render_fallback_count"])
                    missing_labels += len(artifact["missing_figure_labels"])
                    continue
                artifact = extract_pdf_figures(
                    source_path,
                    output_dir=self._paper_dir(paper),
                    root=self.root,
                    paper_id=str(paper["id"]),
                    source_file=str(paper["source_file"]),
                    source_sha256=source_sha256,
                    render_scale=self.render_scale,
                )
                _write_json(artifact_path, artifact)
                _mark_extracted(paper, artifact_path, artifact, self.root)
                extracted += 1
                figures += int(artifact["figure_count"])
                page_render_fallbacks += int(artifact["page_render_fallback_count"])
                missing_labels += len(artifact["missing_figure_labels"])
            except Exception as exc:  # noqa: BLE001 - isolate per-paper failures.
                failed += 1
                _mark_failed(paper, exc)

        index["updated_at"] = now_iso()
        self.harness.write_index(index)
        return FigureExtractionSummary(
            root=str(self.root),
            index_path=str(self.harness.index_path),
            total_pdf_papers=len(pdf_records),
            extracted=extracted,
            skipped=skipped,
            failed=failed,
            figures=figures,
            page_render_fallbacks=page_render_fallbacks,
            missing_labels=missing_labels,
        )

    def _paper_dir(self, paper: dict[str, Any]) -> Path:
        return self.figures_dir / _safe_name(str(paper.get("id") or "paper"))

    def _artifact_path(self, paper: dict[str, Any]) -> Path:
        return self._paper_dir(paper) / "manifest.json"

    def _can_skip(
        self,
        paper: dict[str, Any],
        artifact_path: Path,
        source_sha256: str,
        force: bool,
    ) -> bool:
        return (
            not force
            and artifact_path.is_file()
            and paper.get("figure_extraction_status") == "extracted"
            and paper.get("figure_extraction_input_sha256") == source_sha256
            and paper.get("figure_extractor") == FIGURE_EXTRACTOR_NAME
            and paper.get("figure_extractor_version") == FIGURE_EXTRACTOR_VERSION
        )


def extract_pdf_figures(
    source_path: Path,
    *,
    output_dir: Path,
    root: Path,
    paper_id: str,
    source_file: str,
    source_sha256: str,
    render_scale: float = 2.0,
) -> dict[str, Any]:
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("PyMuPDF is required. Install with `pip install pymupdf`.") from exc

    output_dir.mkdir(parents=True, exist_ok=True)
    figures: list[dict[str, Any]] = []
    page_render_fallback_count = 0
    detected_figure_labels: list[str] = []
    extracted_figure_labels: list[str] = []
    missing_figure_labels: list[str] = []
    with fitz.open(source_path) as document:
        for page_number, page in enumerate(document, start=1):
            blocks = _text_blocks(page)
            image_infos = _image_infos(page)
            accepted_infos = [
                info
                for info in image_infos
                if int(info.get("width", 0)) >= MIN_FIGURE_WIDTH
                and int(info.get("height", 0)) >= MIN_FIGURE_HEIGHT
            ]
            page_render_path: Path | None = None
            claimed_component_ids: set[str] = set()
            ordinal = 0
            graphic_components = _graphic_components(page, accepted_infos)
            captions = _caption_blocks(blocks)
            detected_figure_labels.extend(caption["label"] for caption in captions)
            for caption in captions:
                (
                    region,
                    components,
                    figure_text,
                    figure_text_elements,
                    body_text_excluded,
                ) = _propose_figure_region(
                    caption_bbox=caption["bbox"],
                    components=[
                        component
                        for component in _components_for_caption(
                            caption,
                            captions,
                            graphic_components,
                        )
                        if component["component_id"] not in claimed_component_ids
                    ],
                    blocks=blocks,
                    page_bbox=_bbox_list(page.rect),
                )
                if region is None:
                    missing_figure_labels.append(caption["label"])
                    continue
                claimed_component_ids.update(
                    str(component["component_id"]) for component in components
                )
                extracted_figure_labels.append(caption["label"])
                ordinal += 1
                page_render_path = page_render_path or _render_page(
                    page,
                    output_dir / f"page-{page_number:04d}.png",
                    scale=render_scale,
                )
                region_render_path = _render_region(
                    page,
                    output_dir / f"page-{page_number:04d}-figure-{ordinal:03d}.png",
                    region,
                    scale=render_scale,
                )
                source_image_paths: list[str] = []
                for component in components:
                    image_index = component.get("image_index")
                    if not isinstance(image_index, int):
                        continue
                    image_path = _write_image_candidate(
                        document,
                        page,
                        accepted_infos[image_index],
                        output_dir
                        / f"page-{page_number:04d}-figure-{ordinal:03d}-source-{image_index + 1:03d}",
                        scale=render_scale,
                    )
                    source_image_paths.append(image_path.relative_to(root).as_posix())
                subfigures = _render_subfigures(
                    page=page,
                    output_dir=output_dir,
                    page_number=page_number,
                    figure_ordinal=ordinal,
                    figure_bbox=region,
                    components=components,
                    figure_text_elements=figure_text_elements,
                    root=root,
                    scale=render_scale,
                )
                figures.append(
                    _figure_record(
                        paper_id=paper_id,
                        page_number=page_number,
                        ordinal=ordinal,
                        kind=(
                            "caption_anchored_region"
                            if components
                            else "caption_anchored_text_region"
                        ),
                        image_path=region_render_path,
                        region_render_path=region_render_path,
                        page_render_path=page_render_path,
                        bbox=region,
                        caption=caption,
                        nearby_text=_nearby_text(blocks, region),
                        inline_references=_inline_references(
                            blocks,
                            caption["label"],
                            caption["text"],
                        ),
                        source_image_paths=source_image_paths,
                        source_component_count=len(components),
                        caption_bbox=caption["bbox"],
                        figure_text=figure_text,
                        figure_text_elements=figure_text_elements,
                        subfigures=subfigures,
                        body_text_excluded=body_text_excluded,
                        completeness_status="caption_matched",
                        root=root,
                    )
                )

    detected_figure_labels, extracted_figure_labels, missing_figure_labels = (
        _label_coverage(detected_figure_labels, extracted_figure_labels)
    )
    return {
        "schema_version": FIGURE_ARTIFACT_SCHEMA_VERSION,
        "paper_id": paper_id,
        "source_file": source_file,
        "source_sha256": source_sha256,
        "extractor": FIGURE_EXTRACTOR_NAME,
        "extractor_version": FIGURE_EXTRACTOR_VERSION,
        "extracted_at": now_iso(),
        "figure_count": len(figures),
        "page_render_fallback_count": page_render_fallback_count,
        "detected_figure_labels": detected_figure_labels,
        "extracted_figure_labels": extracted_figure_labels,
        "missing_figure_labels": missing_figure_labels,
        "figures": figures,
    }


def _image_infos(page: Any) -> list[dict[str, Any]]:
    return [dict(info) for info in page.get_image_info(xrefs=True)]


def _text_blocks(page: Any) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    page_width = float(page.rect.width)
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 0:
            continue
        lines = block.get("lines", [])
        line_records = [
            {
                "text": "".join(
                    str(span.get("text", "")) for span in line.get("spans", [])
                ).strip(),
                "bbox": _bbox_list(line.get("bbox")),
            }
            for line in lines
        ]
        line_texts = [line["text"] for line in line_records]
        text = "\n".join(line for line in line_texts if line).strip()
        if text:
            bbox = _bbox_list(block.get("bbox"))
            blocks.append(
                {
                    "bbox": bbox,
                    "text": text,
                    "line_count": len([line for line in line_texts if line]),
                    "lines": [line for line in line_records if line["text"]],
                    "is_body_text": _is_body_text(text, bbox, page_width),
                }
            )
    return blocks


def _graphic_components(
    page: Any,
    image_infos: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    components = [
        {
            "component_id": f"image-{index}",
            "kind": "image",
            "bbox": _bbox_list(info.get("bbox")),
            "image_index": index,
        }
        for index, info in enumerate(image_infos)
    ]
    for drawing_index, drawing in enumerate(page.get_drawings()):
        bbox = _bbox_list(drawing.get("rect"))
        if (
            bbox[2] - bbox[0] >= MIN_GRAPHIC_COMPONENT_SIZE
            and bbox[3] - bbox[1] >= MIN_GRAPHIC_COMPONENT_SIZE
        ):
            components.append(
                {
                    "component_id": f"vector-{drawing_index}",
                    "kind": "vector",
                    "bbox": bbox,
                }
            )
    return components


def _components_for_caption(
    caption: dict[str, Any],
    captions: list[dict[str, Any]],
    components: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    assigned: list[dict[str, Any]] = []
    current_is_table = str(caption.get("label", "")).lower().startswith("table")
    for component in components:
        candidates = [
            candidate
            for candidate in captions
            if _component_caption_distance(component["bbox"], candidate["bbox"])
            <= MAX_CAPTION_GRAPHIC_DISTANCE
            and _horizontal_gap(component["bbox"], candidate["bbox"])
            <= MAX_CAPTION_COLUMN_GAP
        ]
        if not candidates:
            continue
        if caption not in candidates:
            continue
        if component.get("kind") == "image" and current_is_table:
            if any(
                not str(candidate.get("label", "")).lower().startswith("table")
                for candidate in candidates
            ):
                continue
        if component.get("kind") == "image" and not current_is_table:
            figure_candidates = [
                candidate
                for candidate in candidates
                if not str(candidate.get("label", "")).lower().startswith("table")
            ]
            minimum_horizontal_gap = min(
                _horizontal_gap(component["bbox"], candidate["bbox"])
                for candidate in figure_candidates
            )
            if (
                _horizontal_gap(component["bbox"], caption["bbox"])
                > minimum_horizontal_gap
            ):
                continue
        assigned.append(component)
    return assigned


def _component_caption_distance(
    component_bbox: list[float],
    caption_bbox: list[float],
) -> float:
    if component_bbox[3] < caption_bbox[1]:
        return caption_bbox[1] - component_bbox[3]
    if caption_bbox[3] < component_bbox[1]:
        return component_bbox[1] - caption_bbox[3]
    return 0.0


def _write_image_candidate(
    document: Any,
    page: Any,
    info: dict[str, Any],
    base_path: Path,
    *,
    scale: float,
) -> Path:
    xref = int(info.get("xref", 0))
    if xref > 0:
        extracted = document.extract_image(xref)
        extension = str(extracted.get("ext") or "png").lower()
        image_path = base_path.with_suffix(f".{extension}")
        image_path.write_bytes(extracted["image"])
        return image_path

    import fitz

    image_path = base_path.with_suffix(".png")
    clip = fitz.Rect(info["bbox"])
    pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=clip, alpha=False)
    pixmap.save(image_path)
    return image_path


def _render_page(page: Any, path: Path, *, scale: float) -> Path:
    import fitz

    pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
    pixmap.save(path)
    return path


def _render_region(page: Any, path: Path, bbox: list[float], *, scale: float) -> Path:
    import fitz

    clip = fitz.Rect(bbox) & page.rect
    pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=clip, alpha=False)
    pixmap.save(path)
    return path


def _figure_record(
    *,
    paper_id: str,
    page_number: int,
    ordinal: int,
    kind: str,
    image_path: Path,
    region_render_path: Path,
    page_render_path: Path,
    bbox: list[float],
    caption: dict[str, str],
    nearby_text: list[str],
    inline_references: list[str],
    source_image_paths: list[str],
    source_component_count: int,
    caption_bbox: list[float],
    figure_text: list[str],
    figure_text_elements: list[dict[str, Any]],
    subfigures: list[dict[str, Any]],
    body_text_excluded: int,
    completeness_status: str,
    root: Path,
) -> dict[str, Any]:
    figure_id = f"{paper_id}-p{page_number:04d}-f{ordinal:03d}"
    return {
        "figure_id": figure_id,
        "paper_id": paper_id,
        "page_number": page_number,
        "figure_label": caption["label"],
        "caption": caption["text"],
        "kind": kind,
        "image_path": image_path.relative_to(root).as_posix(),
        "region_render_path": region_render_path.relative_to(root).as_posix(),
        "page_render_path": page_render_path.relative_to(root).as_posix(),
        "bounding_box": bbox,
        "image_sha256": _sha256_file(image_path),
        "region_render_sha256": _sha256_file(region_render_path),
        "nearby_text": nearby_text,
        "inline_references": inline_references,
        "source_image_paths": source_image_paths,
        "source_component_count": source_component_count,
        "subfigures": subfigures or _subfigure_hints(figure_text_elements, bbox),
        "caption_bbox": caption_bbox,
        "figure_text": figure_text,
        "figure_text_elements": figure_text_elements,
        "body_text_excluded": body_text_excluded,
        "completeness_status": completeness_status,
    }


def _render_subfigures(
    *,
    page: Any,
    output_dir: Path,
    page_number: int,
    figure_ordinal: int,
    figure_bbox: list[float],
    components: list[dict[str, Any]],
    figure_text_elements: list[dict[str, Any]],
    root: Path,
    scale: float,
) -> list[dict[str, Any]]:
    panels = _independent_image_panels(components, figure_bbox)
    if len(panels) < 2:
        return []
    hints = _subfigure_hints(figure_text_elements, figure_bbox)
    records: list[dict[str, Any]] = []
    for ordinal, panel in enumerate(panels, start=1):
        bbox = panel["bbox"]
        label = _nearest_subfigure_label(bbox, hints) or f"panel-{ordinal}"
        path = _render_region(
            page,
            output_dir
            / f"page-{page_number:04d}-figure-{figure_ordinal:03d}-subfigure-{ordinal:03d}.png",
            bbox,
            scale=scale,
        )
        records.append(
            {
                "subfigure_id": f"subfigure-{ordinal:03d}",
                "label": label,
                "bbox": bbox,
                "relative_bbox": _relative_bbox(bbox, figure_bbox),
                "image_path": path.relative_to(root).as_posix(),
                "image_sha256": _sha256_file(path),
                "detection_method": "independent_image_component",
            }
        )
    return records


def _independent_image_panels(
    components: list[dict[str, Any]],
    figure_bbox: list[float],
) -> list[dict[str, Any]]:
    figure_area = max(
        (figure_bbox[2] - figure_bbox[0]) * (figure_bbox[3] - figure_bbox[1]),
        1.0,
    )
    panels: list[dict[str, Any]] = []
    seen: set[tuple[float, ...]] = set()
    for component in components:
        bbox = component.get("bbox")
        if component.get("kind") != "image" or not isinstance(bbox, list):
            continue
        area = max((bbox[2] - bbox[0]) * (bbox[3] - bbox[1]), 0.0)
        key = tuple(round(float(value), 2) for value in bbox)
        if area / figure_area < 0.05 or key in seen:
            continue
        panels.append(component)
        seen.add(key)
    return sorted(panels, key=lambda item: (item["bbox"][1], item["bbox"][0]))[:12]


def _nearest_subfigure_label(
    panel_bbox: list[float],
    hints: list[dict[str, Any]],
) -> str | None:
    candidates = [
        hint
        for hint in hints
        if _bboxes_overlap(panel_bbox, hint["bbox"])
        or (
            panel_bbox[0] - 20 <= hint["bbox"][0] <= panel_bbox[2] + 20
            and panel_bbox[1] - 20 <= hint["bbox"][1] <= panel_bbox[3] + 20
        )
    ]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda hint: abs(hint["bbox"][0] - panel_bbox[0])
        + abs(hint["bbox"][1] - panel_bbox[1]),
    )["label"]


def _relative_bbox(bbox: list[float], outer: list[float]) -> list[float]:
    width = max(outer[2] - outer[0], 1.0)
    height = max(outer[3] - outer[1], 1.0)
    return [
        round((bbox[0] - outer[0]) / width, 6),
        round((bbox[1] - outer[1]) / height, 6),
        round((bbox[2] - outer[0]) / width, 6),
        round((bbox[3] - outer[1]) / height, 6),
    ]


def _subfigure_hints(
    figure_text_elements: list[dict[str, Any]],
    figure_bbox: list[float],
) -> list[dict[str, Any]]:
    hints: list[dict[str, Any]] = []
    seen: set[str] = set()
    for element in figure_text_elements:
        text = str(element.get("text", "")).strip()
        match = re.fullmatch(r"\(?([a-z])\)?[.:]?", text, flags=re.IGNORECASE)
        bbox = element.get("bbox")
        if not match or not isinstance(bbox, list) or len(bbox) != 4:
            continue
        label = f"({match.group(1).lower()})"
        if label in seen:
            continue
        hints.append(
            {
                "label": label,
                "bbox": bbox,
                "relative_bbox": _relative_bbox(bbox, figure_bbox),
                "detection_method": "text_label_hint",
            }
        )
        seen.add(label)
    return hints


def _caption_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    captions: list[dict[str, Any]] = []
    for block in blocks:
        if block.get("is_body_text"):
            continue
        lines = block.get("lines", [])
        for index, line in enumerate(lines):
            match = CAPTION_LABEL_PATTERN.match(line["text"])
            remainder = match.group(2).lstrip() if match else ""
            if match and not remainder.startswith(","):
                caption_lines = lines[index:]
                captions.append(
                    {
                        "label": match.group(1).strip(),
                        "text": "\n".join(
                            caption_line["text"] for caption_line in caption_lines
                        ),
                        "bbox": _union_bboxes(
                            [caption_line["bbox"] for caption_line in caption_lines]
                        ),
                    }
                )
                break
    return captions


def _label_coverage(
    detected_labels: list[str],
    extracted_labels: list[str],
) -> tuple[list[str], list[str], list[str]]:
    detected = _unique_labels(detected_labels)
    extracted = _unique_labels(extracted_labels)
    extracted_keys = {_normalized_label(label) for label in extracted}
    missing = [
        label for label in detected if _normalized_label(label) not in extracted_keys
    ]
    return detected, extracted, missing


def _unique_labels(labels: list[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for label in labels:
        key = _normalized_label(label)
        if key and key not in seen:
            unique.append(label)
            seen.add(key)
    return unique


def _normalized_label(label: str) -> str:
    return re.sub(r"[^a-z0-9]", "", label.lower().replace("figure", "fig"))


def _propose_figure_region(
    *,
    caption_bbox: list[float],
    components: list[dict[str, Any]],
    blocks: list[dict[str, Any]],
    page_bbox: list[float],
) -> tuple[
    list[float] | None,
    list[dict[str, Any]],
    list[str],
    list[dict[str, Any]],
    int,
]:
    above_limit = _body_text_boundary(
        blocks,
        caption_bbox,
        direction="above",
        page_edge=page_bbox[1],
    )
    above_eligible = [
        component
        for component in components
        if component["bbox"][3] <= caption_bbox[1] + 8
        and caption_bbox[1] - component["bbox"][3] <= MAX_CAPTION_GRAPHIC_DISTANCE
        and component["bbox"][1] >= above_limit
        and _horizontal_gap(component["bbox"], caption_bbox) <= MAX_CAPTION_COLUMN_GAP
    ]
    selected = [
        component
        for component in above_eligible
        if _horizontal_overlap_ratio(component["bbox"], caption_bbox) > 0.02
        or _horizontal_gap(component["bbox"], caption_bbox) <= MAX_FIGURE_TEXT_GAP
    ]
    eligible = above_eligible
    if not selected:
        below_limit = _body_text_boundary(
            blocks,
            caption_bbox,
            direction="below",
            page_edge=page_bbox[3],
        )
        below_eligible = [
            component
            for component in components
            if component["bbox"][1] >= caption_bbox[3] - 8
            and component["bbox"][1] - caption_bbox[3] <= MAX_CAPTION_GRAPHIC_DISTANCE
            and component["bbox"][3] <= below_limit
            and _horizontal_gap(component["bbox"], caption_bbox) <= MAX_CAPTION_COLUMN_GAP
        ]
        selected = [
            component
            for component in below_eligible
            if _horizontal_overlap_ratio(component["bbox"], caption_bbox) > 0.02
            or _horizontal_gap(component["bbox"], caption_bbox) <= MAX_FIGURE_TEXT_GAP
        ]
        eligible = below_eligible
    if not selected:
        text_region = _text_only_region(blocks, caption_bbox, page_bbox)
        if not text_region:
            return None, [], [], [], 0
        bbox = _union_bboxes([block["bbox"] for block in text_region])
        figure_text = [
            line.strip()
            for block in text_region
            for line in block["text"].splitlines()
            if line.strip()
        ]
        return bbox, [], figure_text, _text_elements(text_region), 0
    selected = _expand_adjacent_components(selected, eligible)
    graphic_bbox = _union_bboxes([component["bbox"] for component in selected])
    figure_blocks = _figure_text_blocks(blocks, graphic_bbox, caption_bbox)
    bbox = _union_bboxes(
        [component["bbox"] for component in selected]
        + [block["bbox"] for block in figure_blocks]
    )
    body_text_excluded = sum(
        1
        for block in blocks
        if block.get("is_body_text")
        and _bboxes_overlap(block["bbox"], bbox)
        and not _bbox_contains(graphic_bbox, block["bbox"])
    )
    figure_text = [
        line.strip()
        for block in figure_blocks
        for line in block["text"].splitlines()
        if line.strip()
    ]
    return bbox, selected, figure_text, _text_elements(figure_blocks), body_text_excluded


def _text_elements(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"text": line["text"], "bbox": line["bbox"]}
        for block in blocks
        for line in block.get("lines", [])
        if line.get("text")
    ]


def _is_body_text(text: str, bbox: list[float], page_width: float) -> bool:
    if CAPTION_LABEL_PATTERN.match(text.splitlines()[0].strip()):
        return False
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    average_line_length = sum(len(line) for line in lines) / max(len(lines), 1)
    width_ratio = (bbox[2] - bbox[0]) / max(page_width, 1.0)
    return (
        len(text) >= 70
        and average_line_length >= 32
        and width_ratio >= 0.32
    )


def _body_text_boundary(
    blocks: list[dict[str, Any]],
    caption_bbox: list[float],
    *,
    direction: str,
    page_edge: float,
) -> float:
    boundary_blocks = _layout_boundary_blocks(blocks)
    if direction == "above":
        boundaries = [
            block["bbox"][3]
            for block in boundary_blocks
            if block.get("is_boundary")
            and block["bbox"][3] <= caption_bbox[1]
            and caption_bbox[1] - block["bbox"][3] <= MAX_CAPTION_GRAPHIC_DISTANCE
            and _horizontal_overlap_ratio(block["bbox"], caption_bbox) > 0.1
        ]
        return max(boundaries, default=page_edge)
    boundaries = [
        block["bbox"][1]
        for block in boundary_blocks
        if block.get("is_boundary")
        and block["bbox"][1] >= caption_bbox[3]
        and block["bbox"][1] - caption_bbox[3] <= MAX_CAPTION_GRAPHIC_DISTANCE
        and _horizontal_overlap_ratio(block["bbox"], caption_bbox) > 0.1
    ]
    return min(boundaries, default=page_edge)


def _layout_boundary_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    boundaries = [
        {"bbox": block["bbox"], "is_boundary": True}
        for block in blocks
        if block.get("is_body_text")
    ]
    boundaries.extend(
        {"bbox": line["bbox"], "is_boundary": True}
        for block in blocks
        for line in block.get("lines", [])
        if CAPTION_LABEL_PATTERN.match(line["text"])
    )
    return boundaries


def _figure_text_blocks(
    blocks: list[dict[str, Any]],
    graphic_bbox: list[float],
    caption_bbox: list[float],
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    region = graphic_bbox
    changed = True
    while changed:
        changed = False
        for block in blocks:
            if block in selected or block.get("is_body_text"):
                continue
            if CAPTION_LABEL_PATTERN.match(block["text"].splitlines()[0].strip()):
                continue
            if _bboxes_overlap(block["bbox"], caption_bbox):
                continue
            if _bbox_contains(region, block["bbox"]) or _bbox_gap(region, block["bbox"]) <= MAX_FIGURE_TEXT_GAP:
                selected.append(block)
                region = _union_bboxes([region, block["bbox"]])
                changed = True
    return selected


def _text_only_region(
    blocks: list[dict[str, Any]],
    caption_bbox: list[float],
    page_bbox: list[float],
) -> list[dict[str, Any]]:
    above_limit = _body_text_boundary(
        blocks,
        caption_bbox,
        direction="above",
        page_edge=page_bbox[1],
    )
    below_limit = _body_text_boundary(
        blocks,
        caption_bbox,
        direction="below",
        page_edge=page_bbox[3],
    )
    candidates = [
        block
        for block in blocks
        if not block.get("is_body_text")
        and not CAPTION_LABEL_PATTERN.match(block["text"].splitlines()[0].strip())
        and _horizontal_overlap_ratio(block["bbox"], caption_bbox) > 0.05
        and (
            (
                block["bbox"][3] <= caption_bbox[1]
                and block["bbox"][1] >= above_limit
                and caption_bbox[1] - block["bbox"][3] <= MAX_CAPTION_GRAPHIC_DISTANCE
            )
            or (
                block["bbox"][1] >= caption_bbox[3]
                and block["bbox"][3] <= below_limit
                and block["bbox"][1] - caption_bbox[3] <= MAX_CAPTION_GRAPHIC_DISTANCE
            )
        )
    ]
    line_count = sum(len(block["text"].splitlines()) for block in candidates)
    return candidates if line_count >= 2 else []


def _expand_adjacent_components(
    selected: list[dict[str, Any]],
    components: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    expanded = list(selected)
    changed = True
    while changed:
        changed = False
        for component in components:
            if component in expanded:
                continue
            if any(
                _vertical_overlap_ratio(component["bbox"], current["bbox"]) >= 0.5
                and _horizontal_gap(component["bbox"], current["bbox"])
                <= MAX_ADJACENT_COMPONENT_GAP
                for current in expanded
            ):
                expanded.append(component)
                changed = True
    return expanded


def _horizontal_overlap_ratio(first: list[float], second: list[float]) -> float:
    overlap = max(0.0, min(first[2], second[2]) - max(first[0], second[0]))
    width = max(min(first[2] - first[0], second[2] - second[0]), 1.0)
    return overlap / width


def _vertical_overlap_ratio(first: list[float], second: list[float]) -> float:
    overlap = max(0.0, min(first[3], second[3]) - max(first[1], second[1]))
    height = max(min(first[3] - first[1], second[3] - second[1]), 1.0)
    return overlap / height


def _horizontal_gap(first: list[float], second: list[float]) -> float:
    if first[2] < second[0]:
        return second[0] - first[2]
    if second[2] < first[0]:
        return first[0] - second[2]
    return 0.0


def _bbox_gap(first: list[float], second: list[float]) -> float:
    horizontal = _horizontal_gap(first, second)
    if first[3] < second[1]:
        vertical = second[1] - first[3]
    elif second[3] < first[1]:
        vertical = first[1] - second[3]
    else:
        vertical = 0.0
    return max(horizontal, vertical)


def _bbox_contains(outer: list[float], inner: list[float]) -> bool:
    return (
        outer[0] <= inner[0]
        and outer[1] <= inner[1]
        and outer[2] >= inner[2]
        and outer[3] >= inner[3]
    )


def _bboxes_overlap(first: list[float], second: list[float]) -> bool:
    return not (
        first[2] <= second[0]
        or second[2] <= first[0]
        or first[3] <= second[1]
        or second[3] <= first[1]
    )


def _union_bboxes(bboxes: list[list[float]]) -> list[float]:
    return [
        min(bbox[0] for bbox in bboxes),
        min(bbox[1] for bbox in bboxes),
        max(bbox[2] for bbox in bboxes),
        max(bbox[3] for bbox in bboxes),
    ]


def _nearby_text(blocks: list[dict[str, Any]], bbox: list[float]) -> list[str]:
    ranked = sorted(
        blocks,
        key=lambda block: min(
            abs(block["bbox"][1] - bbox[3]),
            abs(bbox[1] - block["bbox"][3]),
        ),
    )
    return [block["text"] for block in ranked[:6]]


def _inline_references(
    blocks: list[dict[str, Any]],
    figure_label: str,
    caption_text: str,
) -> list[str]:
    number_match = re.search(r"(\d+[A-Z]?)", figure_label, flags=re.IGNORECASE)
    if not number_match:
        return []
    figure_number = re.escape(number_match.group(1))
    label_prefix = "table" if figure_label.lower().startswith("table") else r"fig(?:ure)?"
    pattern = re.compile(
        rf"\b{label_prefix}\.?\s*{figure_number}\b",
        flags=re.IGNORECASE,
    )
    references: list[str] = []
    for block in blocks:
        text = block["text"]
        if text == caption_text or CAPTION_LABEL_PATTERN.match(text.splitlines()[0].strip()):
            continue
        if pattern.search(text):
            references.append(text)
    return references


def _bbox_list(value: Any) -> list[float]:
    if value is None:
        return [0.0, 0.0, 0.0, 0.0]
    return [float(item) for item in value]


def _mark_extracted(
    paper: dict[str, Any],
    artifact_path: Path,
    artifact: dict[str, Any],
    root: Path,
) -> None:
    paper["figure_extraction_status"] = "extracted"
    paper["figure_artifact"] = artifact_path.relative_to(root).as_posix()
    paper["figure_extraction_input_sha256"] = artifact["source_sha256"]
    paper["figure_extractor"] = artifact["extractor"]
    paper["figure_extractor_version"] = artifact["extractor_version"]
    paper["figure_count"] = artifact["figure_count"]
    paper["figure_page_render_fallback_count"] = artifact["page_render_fallback_count"]
    paper["figures_extracted_at"] = artifact["extracted_at"]
    paper.pop("figure_extraction_error", None)
    paper["updated_at"] = now_iso()


def _mark_failed(paper: dict[str, Any], exc: Exception) -> None:
    invalidate_figure_extraction(paper)
    paper["figure_extraction_status"] = "failed"
    paper["figure_extraction_error"] = str(exc)
    paper["updated_at"] = now_iso()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
        file.write("\n")
    temporary.replace(path)


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object.")
    return payload


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_name(value: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value).strip("-")
    return safe or "paper"
