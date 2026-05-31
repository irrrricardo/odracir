"""Optional PyMuPDF4LLM adapter for layout-aware PDF extraction."""

from __future__ import annotations

import importlib.util
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from odracir.pdf_artifacts import build_pdf_text_artifact


MarkdownConverter = Callable[..., Any]


@dataclass(frozen=True)
class PyMuPdf4LlmCapability:
    name: str
    available: bool
    version: str | None
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def detect_pymupdf4llm_capability() -> PyMuPdf4LlmCapability:
    if importlib.util.find_spec("pymupdf4llm") is None:
        return PyMuPdf4LlmCapability(
            name="pymupdf4llm",
            available=False,
            version=None,
            detail='Install optional support with `pip install -e ".[pymupdf4llm]"`.',
        )
    try:
        from pymupdf4llm import to_markdown  # noqa: F401
    except ImportError as exc:
        return PyMuPdf4LlmCapability(
            name="pymupdf4llm",
            available=False,
            version=_pymupdf4llm_version(),
            detail=f"PyMuPDF4LLM is installed but could not import its converter: {exc}",
        )
    return PyMuPdf4LlmCapability(
        name="pymupdf4llm",
        available=True,
        version=_pymupdf4llm_version(),
        detail=(
            "Layout-aware Markdown conversion import succeeded; available as the "
            "`pymupdf4llm` parser backend."
        ),
    )


def extract_pdf_text_with_pymupdf4llm(
    source_path: Path,
    *,
    to_markdown: MarkdownConverter | None = None,
) -> dict[str, Any]:
    """Convert one PDF into page-level Markdown without implicit OCR."""
    if to_markdown is None:
        try:
            from pymupdf4llm import to_markdown
        except ImportError as exc:
            raise RuntimeError(
                'PyMuPDF4LLM is required. Install with `pip install -e ".[pymupdf4llm]"`.'
            ) from exc

    raw_chunks = to_markdown(
        str(source_path),
        page_chunks=True,
        use_ocr=False,
        show_progress=False,
    )
    if not isinstance(raw_chunks, list):
        raise RuntimeError("PyMuPDF4LLM did not return page chunks.")

    pages: list[dict[str, Any]] = []
    seen_page_numbers: set[int] = set()
    document_metadata: dict[str, Any] = {}
    for ordinal, raw_chunk in enumerate(raw_chunks, start=1):
        if not isinstance(raw_chunk, Mapping):
            raise RuntimeError("PyMuPDF4LLM returned a non-object page chunk.")

        metadata = raw_chunk.get("metadata")
        if not isinstance(metadata, Mapping):
            metadata = {}
        page_number = _page_number(metadata, fallback=ordinal)
        if page_number in seen_page_numbers:
            raise RuntimeError("PyMuPDF4LLM returned duplicate page numbers.")
        seen_page_numbers.add(page_number)
        pages.append(
            {
                "page_number": page_number,
                "text": str(raw_chunk.get("text", "")),
            }
        )
        if not document_metadata:
            document_metadata = _document_metadata(metadata)

    return build_pdf_text_artifact(
        parser="pymupdf4llm",
        parser_version=_pymupdf4llm_version(),
        pages=pages,
        metadata={
            **document_metadata,
            "page_text_format": "markdown",
            "layout_aware": True,
            "ocr_mode": "disabled_use_odracir_ocr_preprocessor",
        },
    )


def _page_number(metadata: Mapping[str, Any], *, fallback: int) -> int:
    value = metadata.get("page_number", metadata.get("page", fallback))
    try:
        page_number = int(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("PyMuPDF4LLM returned an invalid page number.") from exc
    if page_number < 1:
        raise RuntimeError("PyMuPDF4LLM returned an invalid page number.")
    return page_number


def _document_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    excluded = {"file_path", "page", "page_number", "page_count"}
    return {
        str(key): value
        for key, value in metadata.items()
        if key not in excluded and _is_json_scalar(value)
    }


def _is_json_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (bool, int, float, str))


def _pymupdf4llm_version() -> str:
    try:
        return version("pymupdf4llm")
    except PackageNotFoundError:
        return "unknown"
