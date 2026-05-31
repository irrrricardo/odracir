"""Optional Docling adapter for complex-layout PDF extraction."""

from __future__ import annotations

import importlib.util
from dataclasses import asdict, dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from odracir.pdf_artifacts import build_pdf_text_artifact


@dataclass(frozen=True)
class DoclingCapability:
    name: str
    available: bool
    version: str | None
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def detect_docling_capability() -> DoclingCapability:
    if importlib.util.find_spec("docling") is None:
        return DoclingCapability(
            name="docling",
            available=False,
            version=None,
            detail='Install optional support with `pip install -e ".[docling]"`.',
        )
    try:
        from docling.document_converter import DocumentConverter  # noqa: F401
    except ImportError as exc:
        return DoclingCapability(
            name="docling",
            available=False,
            version=_docling_version(),
            detail=f"Docling is installed but could not import its converter: {exc}",
        )
    return DoclingCapability(
        name="docling",
        available=True,
        version=_docling_version(),
        detail="Converter import succeeded; available as the `docling` parser backend.",
    )


def extract_pdf_text_with_docling(
    source_path: Path,
    *,
    converter: Any | None = None,
) -> dict[str, Any]:
    """Convert one PDF with Docling and emit the normalized page contract."""
    if converter is None:
        try:
            from docling.document_converter import DocumentConverter
        except ImportError as exc:
            raise RuntimeError(
                'Docling is required. Install with `pip install -e ".[docling]"`.'
            ) from exc
        converter = DocumentConverter()

    result = converter.convert(source_path)
    document = result.document
    page_numbers = _page_numbers(document)
    pages = [
        {
            "page_number": page_number,
            "text": document.export_to_markdown(page_no=page_number),
        }
        for page_number in page_numbers
    ]
    return build_pdf_text_artifact(
        parser="docling",
        parser_version=_docling_version(),
        pages=pages,
        metadata={
            "page_text_format": "markdown",
            "conversion_status": str(getattr(result, "status", "")),
        },
    )


def _page_numbers(document: Any) -> list[int]:
    pages = getattr(document, "pages", None)
    if isinstance(pages, dict):
        return sorted(int(page_number) for page_number in pages)

    page_count = getattr(document, "num_pages", None)
    if callable(page_count):
        page_count = page_count()
    if isinstance(page_count, int):
        return list(range(1, page_count + 1))

    raise RuntimeError("Docling result does not expose page-level PDF structure.")


def _docling_version() -> str:
    try:
        return version("docling")
    except PackageNotFoundError:
        return "unknown"
