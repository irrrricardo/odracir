import pytest

from odracir.schemas import require_valid_project_index, validate_project_index


def _paper(paper_id: str, source_file: str, sha256: str = "a" * 64) -> dict[str, str]:
    return {"id": paper_id, "source_file": source_file, "sha256": sha256}


def test_validate_project_index_accepts_unique_records() -> None:
    assert validate_project_index({"papers": [_paper("one", "papers/one.pdf")]}) == []


def test_validate_project_index_reports_duplicate_ids_and_sources() -> None:
    errors = validate_project_index(
        {
            "papers": [
                _paper("same", "papers/same.pdf"),
                _paper("same", "papers/same.pdf"),
            ]
        }
    )

    assert any("id duplicates" in error for error in errors)
    assert any("source_file duplicates" in error for error in errors)


def test_require_valid_project_index_rejects_invalid_hash() -> None:
    with pytest.raises(ValueError, match="64-character hash"):
        require_valid_project_index({"papers": [_paper("one", "papers/one.pdf", "bad")]})
