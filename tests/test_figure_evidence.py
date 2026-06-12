import json

from odracir.figure_evidence import FigureEvidenceCatalogBuilder


def test_figure_evidence_catalog_excludes_inference_and_unsupported(tmp_path) -> None:
    root = tmp_path / "field"
    analysis_dir = root / ".odracir" / "figure-analyses" / "paper"
    analysis_dir.mkdir(parents=True)
    artifact = {
        "status": "completed",
        "paper_id": "paper",
        "figure_id": "paper-p0001-f001",
        "analysis_image_path": ".odracir/figures/paper/figure.png",
        "analysis_image_sha256": "abc",
        "analysis": {
            "figure_type": "statistical_chart",
            "scientific_question": "Which method has the lowest error?",
            "evidence_items": [
                {
                    "claim": "Method A has the lowest visible error.",
                    "support_level": "direct_visual",
                    "source": "image",
                    "evidence_detail": "Method A curve ends below Method B.",
                    "confidence": 0.9,
                },
                {
                    "claim": "Method A will generalize better.",
                    "support_level": "inference",
                    "source": "image",
                    "evidence_detail": "Generalization is not measured.",
                    "confidence": 0.4,
                },
                {
                    "claim": "A low-confidence visible difference exists.",
                    "support_level": "direct_visual",
                    "source": "image",
                    "evidence_detail": "The curves may differ.",
                    "confidence": 0.2,
                },
            ],
        },
    }
    (analysis_dir / "figure.json").write_text(
        json.dumps(artifact),
        encoding="utf-8",
    )

    result = FigureEvidenceCatalogBuilder(root).build()
    catalog = json.loads(
        (root / ".odracir" / "figure-evidence" / "catalog.json").read_text(
            encoding="utf-8"
        )
    )

    assert result.evidence_items == 1
    assert result.excluded_items == 2
    assert catalog["records"][0]["claim"] == "Method A has the lowest visible error."
    assert catalog["minimum_confidence"] == 0.7


def test_figure_evidence_catalog_rejects_conflicting_source_supported_claim(tmp_path) -> None:
    root = tmp_path / "field"
    analysis_dir = root / ".odracir" / "figure-analyses" / "paper"
    analysis_dir.mkdir(parents=True)
    artifact = {
        "status": "completed",
        "paper_id": "paper",
        "figure_id": "figure",
        "verification_mode": "multi_model_consensus",
        "analysis": {
            "figure_type": "statistical_chart",
            "scientific_question": "question",
            "text_image_consistency": "conflicting",
            "evidence_items": [
                {
                    "claim": "Caption claim",
                    "support_level": "source_supported",
                    "source": "caption",
                    "evidence_detail": "Caption text",
                    "confidence": 0.9,
                }
            ],
        },
    }
    (analysis_dir / "figure.json").write_text(json.dumps(artifact), encoding="utf-8")

    result = FigureEvidenceCatalogBuilder(root).build()

    assert result.evidence_items == 0
    assert result.excluded_items == 1


def test_figure_evidence_catalog_can_require_multi_model_consensus(tmp_path) -> None:
    root = tmp_path / "field"
    analysis_dir = root / ".odracir" / "figure-analyses" / "paper"
    analysis_dir.mkdir(parents=True)
    artifact = {
        "status": "completed",
        "paper_id": "paper",
        "figure_id": "figure",
        "verification_mode": "single_model",
        "analysis": {
            "figure_type": "statistical_chart",
            "scientific_question": "question",
            "text_image_consistency": "consistent",
            "evidence_items": [
                {
                    "claim": "Visible claim",
                    "support_level": "direct_visual",
                    "source": "image",
                    "evidence_detail": "Visible curve",
                    "confidence": 0.95,
                }
            ],
        },
    }
    (analysis_dir / "figure.json").write_text(json.dumps(artifact), encoding="utf-8")

    result = FigureEvidenceCatalogBuilder(root, require_consensus=True).build()

    assert result.evidence_items == 0
    assert result.excluded_items == 1


def test_figure_evidence_catalog_validates_minimum_confidence(tmp_path) -> None:
    try:
        FigureEvidenceCatalogBuilder(tmp_path, minimum_confidence=1.1)
    except ValueError as exc:
        assert "between 0 and 1" in str(exc)
    else:
        raise AssertionError("Expected invalid confidence threshold to fail.")
