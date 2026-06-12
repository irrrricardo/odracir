import json

import pytest

import odracir.figure_extraction as figure_extraction
from odracir.figure_extraction import (
    PdfFigureExtractor,
    _caption_blocks,
    _components_for_caption,
    _label_coverage,
    _subfigure_hints,
)


fitz = pytest.importorskip("fitz")


def test_label_coverage_does_not_report_duplicate_detected_label_as_missing() -> None:
    detected, extracted, missing = _label_coverage(
        ["Fig. 1", "Figure 1", "Table 2", "Table 2"],
        ["Fig. 1", "Table 2"],
    )

    assert detected == ["Fig. 1", "Table 2"]
    assert extracted == ["Fig. 1", "Table 2"]
    assert missing == []


def test_caption_blocks_preserve_multiline_caption() -> None:
    blocks = [
        {
            "is_body_text": False,
            "lines": [
                {"text": "Fig. 1. First line", "bbox": [10.0, 10.0, 100.0, 20.0]},
                {"text": "continued explanation", "bbox": [10.0, 21.0, 120.0, 30.0]},
            ],
        }
    ]

    captions = _caption_blocks(blocks)

    assert captions[0]["text"] == "Fig. 1. First line\ncontinued explanation"
    assert captions[0]["bbox"] == [10.0, 10.0, 120.0, 30.0]


def test_subfigure_hints_preserve_label_position() -> None:
    hints = _subfigure_hints(
        [
            {"text": "(a)", "bbox": [10.0, 20.0, 20.0, 30.0]},
            {"text": "measurement", "bbox": [30.0, 20.0, 90.0, 30.0]},
            {"text": "b.", "bbox": [60.0, 60.0, 70.0, 70.0]},
        ],
        [0.0, 0.0, 100.0, 100.0],
    )

    assert [hint["label"] for hint in hints] == ["(a)", "(b)"]
    assert hints[0]["relative_bbox"] == [0.1, 0.2, 0.2, 0.3]


def test_raster_component_prefers_nearby_figure_caption_over_table_caption() -> None:
    table = {"label": "Table 1", "bbox": [10.0, 90.0, 190.0, 100.0]}
    figure = {"label": "Figure 1", "bbox": [10.0, 310.0, 190.0, 320.0]}
    component = {
        "component_id": "image-0",
        "kind": "image",
        "bbox": [10.0, 105.0, 190.0, 300.0],
    }

    assert _components_for_caption(table, [table, figure], [component]) == []
    assert _components_for_caption(figure, [table, figure], [component]) == [component]


def test_raster_component_prefers_figure_caption_in_same_column() -> None:
    left = {"label": "Figure 1", "bbox": [10.0, 310.0, 190.0, 320.0]}
    right = {"label": "Figure 2", "bbox": [210.0, 310.0, 390.0, 320.0]}
    component = {
        "component_id": "image-0",
        "kind": "image",
        "bbox": [210.0, 100.0, 390.0, 300.0],
    }

    assert _components_for_caption(left, [left, right], [component]) == []
    assert _components_for_caption(right, [left, right], [component]) == [component]


def _png_bytes() -> bytes:
    pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 120, 90), False)
    pixmap.clear_with(0x336699)
    return pixmap.tobytes("png")


def test_figure_extractor_writes_traceable_embedded_image(tmp_path) -> None:
    root = tmp_path / "field"
    papers = root / "papers"
    papers.mkdir(parents=True)
    pdf_path = papers / "paper.pdf"

    document = fitz.open()
    page = document.new_page(width=600, height=800)
    page.insert_image(fitz.Rect(80, 120, 440, 390), stream=_png_bytes())
    page.insert_text((80, 430), "Figure 1. Representative tissue structure.")
    page.insert_text((80, 470), "The tissue image supports the reported observation.")
    page.insert_text((80, 510), "As shown in Fig. 1, the tissue regions differ.")
    document.save(pdf_path)
    document.close()

    result = PdfFigureExtractor(root).extract_index()

    assert result.extracted == 1
    assert result.figures == 1
    assert result.missing_labels == 0
    index = json.loads((root / "odracir_index.json").read_text(encoding="utf-8"))
    paper = index["papers"][0]
    assert paper["figure_extraction_status"] == "extracted"
    assert paper["figure_count"] == 1

    manifest = json.loads((root / paper["figure_artifact"]).read_text(encoding="utf-8"))
    figure = manifest["figures"][0]
    assert figure["page_number"] == 1
    assert figure["figure_label"].lower().startswith("figure 1")
    assert "Representative tissue" in figure["caption"]
    assert figure["kind"] == "caption_anchored_region"
    assert len(figure["bounding_box"]) == 4
    assert figure["source_component_count"] == 1
    assert len(figure["source_image_paths"]) == 1
    assert figure["subfigures"] == []
    assert figure["completeness_status"] == "caption_matched"
    assert isinstance(figure["figure_text_elements"], list)
    assert manifest["detected_figure_labels"] == ["Figure 1"]
    assert manifest["extracted_figure_labels"] == ["Figure 1"]
    assert manifest["missing_figure_labels"] == []
    assert figure["inline_references"] == ["As shown in Fig. 1, the tissue regions differ."]
    assert (root / figure["image_path"]).is_file()
    assert (root / figure["region_render_path"]).is_file()
    assert (root / figure["page_render_path"]).is_file()


def test_figure_extractor_uses_caption_anchored_region_for_vector_figure(tmp_path) -> None:
    root = tmp_path / "field"
    papers = root / "papers"
    papers.mkdir(parents=True)
    pdf_path = papers / "vector.pdf"

    document = fitz.open()
    page = document.new_page(width=600, height=800)
    page.draw_rect(fitz.Rect(80, 120, 420, 350), color=(0, 0, 0), fill=(0.8, 0.8, 0.8))
    page.insert_text((80, 400), "Fig. 2. Vector mechanism diagram.")
    document.save(pdf_path)
    document.close()

    result = PdfFigureExtractor(root).extract_index()
    index = json.loads((root / "odracir_index.json").read_text(encoding="utf-8"))
    manifest = json.loads((root / index["papers"][0]["figure_artifact"]).read_text(encoding="utf-8"))

    assert result.page_render_fallbacks == 0
    assert manifest["figures"][0]["kind"] == "caption_anchored_region"
    assert manifest["figures"][0]["source_component_count"] >= 1
    assert manifest["figures"][0]["image_path"] == manifest["figures"][0]["region_render_path"]


def test_figure_extractor_groups_multiple_panels_under_one_caption(tmp_path) -> None:
    root = tmp_path / "field"
    papers = root / "papers"
    papers.mkdir(parents=True)
    pdf_path = papers / "compound.pdf"

    document = fitz.open()
    page = document.new_page(width=600, height=800)
    page.insert_image(fitz.Rect(60, 100, 280, 330), stream=_png_bytes())
    page.insert_image(fitz.Rect(320, 100, 540, 330), stream=_png_bytes())
    page.insert_text((60, 380), "Figure 3. Compound microscopy comparison.")
    document.save(pdf_path)
    document.close()

    result = PdfFigureExtractor(root).extract_index()
    index = json.loads((root / "odracir_index.json").read_text(encoding="utf-8"))
    manifest = json.loads((root / index["papers"][0]["figure_artifact"]).read_text(encoding="utf-8"))

    assert result.figures == 1
    assert manifest["figures"][0]["source_component_count"] == 2
    assert len(manifest["figures"][0]["source_image_paths"]) == 2
    assert len(manifest["figures"][0]["subfigures"]) == 2
    assert all(
        (root / subfigure["image_path"]).is_file()
        for subfigure in manifest["figures"][0]["subfigures"]
    )
    assert all(
        subfigure["detection_method"] == "independent_image_component"
        for subfigure in manifest["figures"][0]["subfigures"]
    )


def test_figure_extractor_does_not_cross_neighboring_captions(tmp_path) -> None:
    root = tmp_path / "field"
    papers = root / "papers"
    papers.mkdir(parents=True)

    document = fitz.open()
    page = document.new_page(width=600, height=900)
    page.insert_image(fitz.Rect(80, 80, 520, 250), stream=_png_bytes())
    page.insert_text((80, 290), "Figure 1. Upper result.")
    page.insert_image(fitz.Rect(80, 360, 520, 530), stream=_png_bytes())
    page.insert_text((80, 570), "Figure 2. Lower result.")
    document.save(papers / "stacked.pdf")
    document.close()

    result = PdfFigureExtractor(root).extract_index()
    index = json.loads((root / "odracir_index.json").read_text(encoding="utf-8"))
    manifest = json.loads((root / index["papers"][0]["figure_artifact"]).read_text(encoding="utf-8"))

    assert manifest["extracted_figure_labels"] == ["Figure 1", "Figure 2"]
    assert len(manifest["figures"]) == 2
    assert all(figure["source_component_count"] == 1 for figure in manifest["figures"])


def test_figure_extractor_ignores_large_images_without_captions(tmp_path) -> None:
    root = tmp_path / "field"
    papers = root / "papers"
    papers.mkdir(parents=True)

    document = fitz.open()
    page = document.new_page(width=600, height=800)
    page.insert_image(fitz.Rect(50, 80, 550, 700), stream=_png_bytes())
    page.insert_text((60, 740), "A large page screenshot without a figure caption.")
    document.save(papers / "screenshot.pdf")
    document.close()

    result = PdfFigureExtractor(root).extract_index()
    index = json.loads((root / "odracir_index.json").read_text(encoding="utf-8"))
    manifest = json.loads((root / index["papers"][0]["figure_artifact"]).read_text(encoding="utf-8"))

    assert result.figures == 0
    assert manifest["figures"] == []


def test_figure_extractor_uses_body_text_as_region_boundary(tmp_path) -> None:
    root = tmp_path / "field"
    papers = root / "papers"
    papers.mkdir(parents=True)

    document = fitz.open()
    page = document.new_page(width=600, height=800)
    page.insert_image(fitz.Rect(80, 40, 520, 170), stream=_png_bytes())
    page.insert_textbox(
        fitz.Rect(70, 190, 530, 285),
        "This is a long body paragraph positioned between unrelated page artwork "
        "and the actual scientific figure. It must act as a crop boundary.",
        fontsize=11,
    )
    page.insert_image(fitz.Rect(100, 330, 500, 500), stream=_png_bytes())
    page.insert_text((100, 540), "Figure 5. Actual result below body text.")
    document.save(papers / "body-boundary.pdf")
    document.close()

    result = PdfFigureExtractor(root).extract_index()
    index = json.loads((root / "odracir_index.json").read_text(encoding="utf-8"))
    manifest = json.loads((root / index["papers"][0]["figure_artifact"]).read_text(encoding="utf-8"))
    figure = manifest["figures"][0]

    assert figure["bounding_box"][1] >= 300
    assert figure["source_component_count"] == 1


def test_figure_extractor_preserves_short_text_inside_diagram(tmp_path) -> None:
    root = tmp_path / "field"
    papers = root / "papers"
    papers.mkdir(parents=True)

    document = fitz.open()
    page = document.new_page(width=600, height=800)
    page.draw_rect(fitz.Rect(100, 120, 500, 350), color=(0, 0, 0))
    page.insert_text((180, 230), "Input cells")
    page.insert_text((350, 230), "Output state")
    page.insert_text((100, 390), "Fig. 6. Cell-processing workflow.")
    document.save(papers / "diagram-text.pdf")
    document.close()

    PdfFigureExtractor(root).extract_index()
    index = json.loads((root / "odracir_index.json").read_text(encoding="utf-8"))
    manifest = json.loads((root / index["papers"][0]["figure_artifact"]).read_text(encoding="utf-8"))
    figure_text = manifest["figures"][0]["figure_text"]

    assert "Input cells" in figure_text
    assert "Output state" in figure_text


def test_figure_extractor_reports_caption_without_extractable_region(tmp_path) -> None:
    root = tmp_path / "field"
    papers = root / "papers"
    papers.mkdir(parents=True)

    document = fitz.open()
    page = document.new_page(width=600, height=800)
    page.insert_text((80, 400), "Figure 7. Missing source graphic.")
    document.save(papers / "missing-figure.pdf")
    document.close()

    result = PdfFigureExtractor(root).extract_index()
    index = json.loads((root / "odracir_index.json").read_text(encoding="utf-8"))
    manifest = json.loads((root / index["papers"][0]["figure_artifact"]).read_text(encoding="utf-8"))

    assert manifest["detected_figure_labels"] == ["Figure 7"]
    assert manifest["extracted_figure_labels"] == []
    assert manifest["missing_figure_labels"] == ["Figure 7"]
    assert result.missing_labels == 1


def test_figure_extractor_does_not_treat_body_reference_as_caption(tmp_path) -> None:
    root = tmp_path / "field"
    papers = root / "papers"
    papers.mkdir(parents=True)

    document = fitz.open()
    page = document.new_page(width=600, height=800)
    page.insert_textbox(
        fitz.Rect(70, 100, 530, 260),
        "Fig. 9, we can conclude that the measured response remains stable "
        "across all tested conditions and therefore supports the discussion.",
        fontsize=11,
    )
    document.save(papers / "body-reference.pdf")
    document.close()

    PdfFigureExtractor(root).extract_index()
    index = json.loads((root / "odracir_index.json").read_text(encoding="utf-8"))
    manifest = json.loads((root / index["papers"][0]["figure_artifact"]).read_text(encoding="utf-8"))

    assert manifest["detected_figure_labels"] == []
    assert manifest["figures"] == []


def test_figure_extractor_supports_table_captions(tmp_path) -> None:
    root = tmp_path / "field"
    papers = root / "papers"
    papers.mkdir(parents=True)

    document = fitz.open()
    page = document.new_page(width=600, height=800)
    page.insert_text((100, 100), "Table 1. Dataset comparison.")
    page.draw_rect(fitz.Rect(100, 140, 500, 350), color=(0, 0, 0))
    page.insert_text((130, 190), "Dataset")
    page.insert_text((350, 190), "Accuracy")
    document.save(papers / "table.pdf")
    document.close()

    PdfFigureExtractor(root).extract_index()
    index = json.loads((root / "odracir_index.json").read_text(encoding="utf-8"))
    manifest = json.loads((root / index["papers"][0]["figure_artifact"]).read_text(encoding="utf-8"))

    assert manifest["figures"][0]["figure_label"] == "Table 1"
    assert "Dataset" in manifest["figures"][0]["figure_text"]


def test_figure_extractor_supports_borderless_text_tables(tmp_path) -> None:
    root = tmp_path / "field"
    papers = root / "papers"
    papers.mkdir(parents=True)

    document = fitz.open()
    page = document.new_page(width=600, height=800)
    page.insert_text((100, 100), "Table 2. Borderless results.")
    page.insert_text((120, 150), "Method A       91.2")
    page.insert_text((120, 180), "Method B       93.8")
    document.save(papers / "borderless-table.pdf")
    document.close()

    PdfFigureExtractor(root).extract_index()
    index = json.loads((root / "odracir_index.json").read_text(encoding="utf-8"))
    manifest = json.loads((root / index["papers"][0]["figure_artifact"]).read_text(encoding="utf-8"))

    assert manifest["missing_figure_labels"] == []
    assert manifest["figures"][0]["source_component_count"] == 0
    assert manifest["figures"][0]["kind"] == "caption_anchored_text_region"
    assert manifest["figures"][0]["figure_text"] == ["Method A       91.2", "Method B       93.8"]


def test_figure_extractor_skips_current_artifact(tmp_path) -> None:
    root = tmp_path / "field"
    papers = root / "papers"
    papers.mkdir(parents=True)
    pdf_path = papers / "paper.pdf"

    document = fitz.open()
    page = document.new_page()
    page.insert_image(fitz.Rect(50, 50, 300, 250), stream=_png_bytes())
    document.save(pdf_path)
    document.close()

    PdfFigureExtractor(root).extract_index()
    result = PdfFigureExtractor(root).extract_index()

    assert result.extracted == 0
    assert result.skipped == 1
    assert result.figures == 0
    assert result.missing_labels == 0


def test_figure_extractor_renders_image_region_without_reusable_xref(
    tmp_path,
    monkeypatch,
) -> None:
    root = tmp_path / "field"
    papers = root / "papers"
    papers.mkdir(parents=True)
    pdf_path = papers / "inline.pdf"

    document = fitz.open()
    page = document.new_page(width=600, height=800)
    page.draw_rect(fitz.Rect(80, 120, 420, 350), color=(0, 0, 0), fill=(0.5, 0.5, 0.5))
    page.insert_text((80, 400), "Figure 4. Inline scientific image.")
    document.save(pdf_path)
    document.close()

    monkeypatch.setattr(
        figure_extraction,
        "_image_infos",
        lambda page: [{"xref": 0, "width": 340, "height": 230, "bbox": (80, 120, 420, 350)}],
    )
    result = PdfFigureExtractor(root).extract_index()
    index = json.loads((root / "odracir_index.json").read_text(encoding="utf-8"))
    manifest = json.loads((root / index["papers"][0]["figure_artifact"]).read_text(encoding="utf-8"))

    assert result.failed == 0
    assert result.figures == 1
    assert (root / manifest["figures"][0]["image_path"]).suffix == ".png"


def test_figure_extractor_keeps_batch_progress_after_invalid_pdf(tmp_path) -> None:
    root = tmp_path / "field"
    papers = root / "papers"
    papers.mkdir(parents=True)

    document = fitz.open()
    page = document.new_page()
    page.insert_image(fitz.Rect(50, 50, 300, 250), stream=_png_bytes())
    document.save(papers / "valid.pdf")
    document.close()
    (papers / "broken.pdf").write_bytes(b"not a PDF")

    result = PdfFigureExtractor(root).extract_index()
    index = json.loads((root / "odracir_index.json").read_text(encoding="utf-8"))
    by_name = {paper["file_name"]: paper for paper in index["papers"]}

    assert result.extracted == 1
    assert result.failed == 1
    assert by_name["valid.pdf"]["figure_extraction_status"] == "extracted"
    assert by_name["broken.pdf"]["figure_extraction_status"] == "failed"
