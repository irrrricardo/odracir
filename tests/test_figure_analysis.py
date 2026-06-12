import json

import pytest

from odracir.figure_analysis import (
    FigureAnalysisHarness,
    _analysis_profile,
    _elements_in_bbox,
    _subfigure_caption_context,
    validate_figure_analysis,
)
from odracir.figure_extraction import PdfFigureExtractor
from odracir.providers import JsonCompletionResult


fitz = pytest.importorskip("fitz")


class VisionStub:
    provider_name = "vision-stub"
    model = "scientific-vision"

    def __init__(self, *, valid: bool = True) -> None:
        self.valid = valid
        self.calls = []

    def analyze_json(self, *, image_path, system_prompt, user_prompt, max_tokens):
        self.calls.append(
            {
                "image_path": image_path,
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "max_tokens": max_tokens,
            }
        )
        payload = {
            "figure_type": "pathology",
            "scientific_question": "Do the visible tissue patterns differ between groups?",
            "entities": [{"name": "tissue regions", "role": "compared groups"}],
            "variables": [{"name": "staining pattern", "role": "metric", "unit": ""}],
            "comparisons": [
                {
                    "subjects": ["treatment", "control"],
                    "basis": "visible staining",
                    "result": "patterns differ",
                }
            ],
            "quantitative_findings": [],
            "trends": [],
            "observations": ["Two differently stained tissue regions are visible."],
            "caption_supported_findings": ["The caption identifies a tissue comparison."],
            "inferences": ["The staining pattern may differ between groups."],
            "supported_conclusions": ["The visible groups have different staining patterns."],
            "evidence_items": [
                {
                    "claim": "Two tissue regions have visibly different staining patterns.",
                    "support_level": "direct_visual",
                    "source": "image",
                    "evidence_detail": "Contrasting stain distribution in the two regions.",
                    "confidence": 0.7,
                }
            ],
            "uncertainties": ["The paper figure is insufficient for diagnosis."],
            "limitations": ["No clinical diagnosis can be established."],
            "text_image_consistency": "consistent",
            "confidence": 0.7,
            "safety_flags": ["Specialist review is required."],
        }
        if not self.valid:
            payload.pop("uncertainties")
        return JsonCompletionResult(payload=payload, usage={"total_tokens": 123})


def _prepare_figure(root) -> None:
    papers = root / "papers"
    papers.mkdir(parents=True)
    pdf_path = papers / "paper.pdf"
    pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 120, 90), False)
    pixmap.clear_with(0x669933)

    document = fitz.open()
    page = document.new_page(width=600, height=800)
    page.insert_image(fitz.Rect(80, 120, 440, 390), stream=pixmap.tobytes("png"))
    page.insert_text((80, 430), "Figure 1. Representative pathology tissue.")
    page.insert_text((80, 470), "Treatment and control tissue are compared.")
    page.insert_text((80, 510), "Figure 1 shows a visible difference between groups.")
    document.save(pdf_path)
    document.close()
    PdfFigureExtractor(root).extract_index()


def _prepare_compound_figure(root) -> None:
    papers = root / "papers"
    papers.mkdir(parents=True)
    pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 120, 90), False)
    pixmap.clear_with(0x669933)
    document = fitz.open()
    page = document.new_page(width=600, height=800)
    page.insert_image(fitz.Rect(60, 100, 280, 330), stream=pixmap.tobytes("png"))
    page.insert_image(fitz.Rect(320, 100, 540, 330), stream=pixmap.tobytes("png"))
    page.insert_text((60, 380), "Figure 2. Compound tissue comparison.")
    document.save(papers / "compound.pdf")
    document.close()
    PdfFigureExtractor(root).extract_index()


def test_figure_analysis_writes_structured_artifact_and_uses_cache(tmp_path) -> None:
    root = tmp_path / "field"
    _prepare_figure(root)
    provider = VisionStub()

    first = FigureAnalysisHarness(root, provider).analyze()
    second = FigureAnalysisHarness(root, provider).analyze()

    assert first.analyzed == 1
    assert first.usage == {"total_tokens": 123}
    assert second.skipped == 1
    assert len(provider.calls) == 1
    assert "Representative pathology tissue" in provider.calls[0]["user_prompt"]
    assert "visible difference between groups" in provider.calls[0]["user_prompt"]
    assert "figure_text_elements" in provider.calls[0]["user_prompt"]
    assert "figure-" in provider.calls[0]["image_path"].name
    artifacts = list((root / ".odracir" / "figure-analyses").rglob("*.json"))
    artifact = json.loads(artifacts[0].read_text(encoding="utf-8"))
    assert artifact["analysis"]["figure_type"] == "pathology"
    assert artifact["analysis"]["inferences"]
    assert artifact["analysis"]["safety_flags"]
    assert artifact["analysis_image_path"].endswith(".png")
    assert artifact["verification_mode"] == "single_model"
    assert artifact["provider_trace"] == {}


def test_figure_analysis_isolates_invalid_model_output(tmp_path) -> None:
    root = tmp_path / "field"
    _prepare_figure(root)

    result = FigureAnalysisHarness(root, VisionStub(valid=False)).analyze()

    assert result.analyzed == 0
    assert result.failed == 1
    artifacts = list((root / ".odracir" / "figure-analyses").rglob("*.json"))
    artifact = json.loads(artifacts[0].read_text(encoding="utf-8"))
    assert artifact["status"] == "failed"
    assert "missing field" in artifact["error"]


def test_figure_analysis_can_include_reliably_cropped_subfigures(tmp_path) -> None:
    root = tmp_path / "field"
    _prepare_compound_figure(root)
    provider = VisionStub()

    result = FigureAnalysisHarness(root, provider).analyze(include_subfigures=True)

    assert result.total_figures == 3
    assert result.analyzed == 3
    artifacts = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in (root / ".odracir" / "figure-analyses").rglob("*.json")
    ]
    subfigure_artifacts = [
        artifact for artifact in artifacts if artifact.get("parent_figure_id")
    ]
    assert len(subfigure_artifacts) == 2
    assert all(artifact["subfigure_label"].startswith("panel-") for artifact in subfigure_artifacts)


def test_validate_figure_analysis_rejects_invalid_confidence() -> None:
    with pytest.raises(ValueError, match="between 0 and 1"):
        validate_figure_analysis(
            {
                "figure_type": "other",
                "scientific_question": "",
                "entities": [],
                "variables": [],
                "comparisons": [],
                "quantitative_findings": [],
                "trends": [],
                "observations": [],
                "caption_supported_findings": [],
                "inferences": [],
                "supported_conclusions": [],
                "evidence_items": [],
                "uncertainties": [],
                "limitations": [],
                "text_image_consistency": "uncertain",
                "confidence": 2,
                "safety_flags": [],
            }
        )


def test_validate_figure_analysis_rejects_visual_claim_without_image_source() -> None:
    payload = VisionStub().analyze_json(
        image_path=None,
        system_prompt="",
        user_prompt="",
        max_tokens=1,
    ).payload
    payload["evidence_items"][0]["source"] = "caption"

    with pytest.raises(ValueError, match="Direct visual evidence"):
        validate_figure_analysis(payload)


def test_analysis_profile_routes_tables_charts_diagrams_and_biomedical() -> None:
    assert _analysis_profile({"figure_label": "Table 2"}) == "table"
    assert _analysis_profile({"caption": "Convergence curves for all methods"}) == "chart"
    assert _analysis_profile({"caption": "General workflow of the method"}) == "diagram"
    assert _analysis_profile({"caption": "Representative tissue microscopy"}) == "biomedical"
    assert _analysis_profile({"figure_text": ["Accuracy", "bar chart"]}) == "chart"


def test_subfigure_context_filters_text_and_caption() -> None:
    elements = [
        {"text": "(a)", "bbox": [0.0, 0.0, 10.0, 10.0]},
        {"text": "left result", "bbox": [20.0, 20.0, 40.0, 30.0]},
        {"text": "right result", "bbox": [120.0, 20.0, 150.0, 30.0]},
    ]

    selected = _elements_in_bbox(elements, [0.0, 0.0, 100.0, 100.0])

    assert [item["text"] for item in selected] == ["(a)", "left result"]
    assert (
        _subfigure_caption_context(
            "Fig. 1. (a) Control tissue; (b) Treated tissue.",
            "(b)",
        )
        == "Treated tissue"
    )
