from types import SimpleNamespace

from odracir.docling_adapter import extract_pdf_text_with_docling
from odracir.pdf_extraction import build_pdf_parser_registry


class _FakeDocument:
    pages = {1: object(), 2: object()}

    def export_to_markdown(self, *, page_no: int) -> str:
        return {
            1: "# Introduction\n\nDocling preserves page one.",
            2: "## Method\n\nDocling preserves page two.",
        }[page_no]


class _FakeConverter:
    def convert(self, source_path):
        return SimpleNamespace(document=_FakeDocument(), status="success")


def test_docling_adapter_normalizes_page_level_markdown(tmp_path) -> None:
    source_path = tmp_path / "paper.pdf"
    source_path.write_bytes(b"%PDF-1.4\n")

    artifact = extract_pdf_text_with_docling(source_path, converter=_FakeConverter())

    assert artifact["parser"] == "docling"
    assert artifact["page_count"] == 2
    assert artifact["metadata"]["page_text_format"] == "markdown"
    assert artifact["pages"][0]["page_number"] == 1
    assert artifact["pages"][1]["text"].startswith("## Method")


def test_default_parser_registry_exposes_optional_backends() -> None:
    assert build_pdf_parser_registry().names() == ("docling", "pymupdf", "pymupdf4llm")
