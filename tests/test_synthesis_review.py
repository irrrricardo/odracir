import json

import pytest

from odracir.synthesis import ResearchSynthesizer
from odracir.synthesis_review import SynthesisReviewHarness
from tests.test_synthesis import SynthesisStubProvider, _write_catalog_fixture


def test_synthesis_review_writes_artifact_and_markdown(tmp_path) -> None:
    root = tmp_path / "field"
    _write_catalog_fixture(root)
    ResearchSynthesizer(root, SynthesisStubProvider()).synthesize()

    report = SynthesisReviewHarness(root).review()

    assert report.status == "warning"
    assert report.review_artifact is not None
    assert report.markdown_path == str(root / "synthesis_review.md")
    assert (root / report.review_artifact).is_file()
    markdown = (root / "synthesis_review.md").read_text(encoding="utf-8")
    assert "# Synthesis Review" in markdown
    assert "Benchmark matrix coverage" in markdown


def test_synthesis_review_flags_missing_claim_support(tmp_path) -> None:
    root = tmp_path / "field"
    _write_catalog_fixture(root)
    result = ResearchSynthesizer(root, SynthesisStubProvider()).synthesize()
    artifact_path = root / result.artifact_path
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    artifact["synthesis"]["claim_evidence_matrix"][0]["supporting_evidence"] = []
    artifact_path.write_text(json.dumps(artifact), encoding="utf-8")

    report = SynthesisReviewHarness(root).review(synthesis_artifact=result.artifact_path)

    assert report.status == "fail"
    assert any(issue.category == "claim_evidence" for issue in report.issues)


def test_synthesis_review_rejects_artifact_outside_research_folder(tmp_path) -> None:
    root = tmp_path / "field"
    root.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="inside the research folder"):
        SynthesisReviewHarness(root).review(synthesis_artifact=outside)


def test_synthesis_review_rejects_output_path_outside_research_folder(tmp_path) -> None:
    root = tmp_path / "field"

    with pytest.raises(ValueError, match="inside the research folder"):
        SynthesisReviewHarness(root, markdown_name="../outside.md")


def test_synthesis_review_rejects_markdown_output_inside_state_directory(tmp_path) -> None:
    root = tmp_path / "field"

    with pytest.raises(ValueError, match=".odracir state directory"):
        SynthesisReviewHarness(root, markdown_name=".odracir/review.md")
