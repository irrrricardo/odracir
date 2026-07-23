import pytest

from odracir.pymupdf4llm_adapter import extract_pdf_text_with_pymupdf4llm


def test_pymupdf4llm_adapter_normalizes_page_markdown_without_implicit_ocr(
    tmp_path,
) -> None:
    source_path = tmp_path / "paper.pdf"
    source_path.write_bytes(b"%PDF-1.4\n")
    calls = []

    def to_markdown(path, **kwargs):
        calls.append((path, kwargs))
        return [
            {
                "metadata": {
                    "title": "Fixture Paper",
                    "file_path": str(source_path),
                    "page_count": 2,
                    "page_number": 1,
                },
                "text": "# Introduction\n\nLayout-aware page one.",
            },
            {
                "metadata": {"page_number": 2},
                "text": "## Method\n\nLayout-aware page two.",
            },
        ]

    artifact = extract_pdf_text_with_pymupdf4llm(
        source_path,
        to_markdown=to_markdown,
    )

    assert calls == [
        (
            str(source_path),
            {
                "page_chunks": True,
                "use_ocr": False,
                "show_progress": False,
            },
        )
    ]
    assert artifact["parser"] == "pymupdf4llm"
    assert artifact["page_count"] == 2
    assert artifact["metadata"]["page_text_format"] == "markdown"
    assert artifact["metadata"]["layout_aware"] is True
    assert artifact["metadata"]["ocr_mode"] == "disabled_use_odracir_ocr_preprocessor"
    assert artifact["metadata"]["title"] == "Fixture Paper"
    assert "file_path" not in artifact["metadata"]
    assert artifact["pages"][1]["page_number"] == 2
    assert artifact["pages"][1]["text"].startswith("## Method")


def test_pymupdf4llm_adapter_rejects_duplicate_page_numbers(tmp_path) -> None:
    source_path = tmp_path / "paper.pdf"
    source_path.write_bytes(b"%PDF-1.4\n")

    with pytest.raises(RuntimeError, match="duplicate page numbers"):
        extract_pdf_text_with_pymupdf4llm(
            source_path,
            to_markdown=lambda *args, **kwargs: [
                {"metadata": {"page_number": 1}, "text": "One"},
                {"metadata": {"page_number": 1}, "text": "Again"},
            ],
        )
