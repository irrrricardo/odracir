"""Normalized PDF text artifacts shared by parser backends."""

from __future__ import annotations

from typing import Any, Iterable

from odracir.time_utils import now_iso


MIN_TEXT_CHARS_PER_PAGE = 40
OCR_PAGE_RATIO_THRESHOLD = 0.8


def build_pdf_text_artifact(
    *,
    parser: str,
    parser_version: str,
    pages: Iterable[dict[str, Any]],
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Normalize parser output while preserving page-level traceability."""
    normalized_pages = [
        {
            "page_number": int(page["page_number"]),
            "text": str(page.get("text", "")).strip(),
            "char_count": len(str(page.get("text", "")).strip()),
        }
        for page in pages
    ]
    text_char_count = sum(page["char_count"] for page in normalized_pages)
    empty_text_page_count = sum(
        1
        for page in normalized_pages
        if page["char_count"] < MIN_TEXT_CHARS_PER_PAGE
    )
    needs_ocr, ocr_reason = detect_ocr_need(
        page_count=len(normalized_pages),
        text_char_count=text_char_count,
        empty_text_page_count=empty_text_page_count,
    )
    return {
        "parser": parser,
        "parser_version": parser_version,
        "extracted_at": now_iso(),
        "page_count": len(normalized_pages),
        "text_char_count": text_char_count,
        "empty_text_page_count": empty_text_page_count,
        "needs_ocr": needs_ocr,
        "ocr_reason": ocr_reason,
        "metadata": metadata or {},
        "pages": normalized_pages,
    }


def detect_ocr_need(
    *,
    page_count: int,
    text_char_count: int,
    empty_text_page_count: int,
) -> tuple[bool, str]:
    if page_count == 0:
        return True, "pdf_has_no_pages"
    if text_char_count == 0:
        return True, "no_extractable_text"
    if empty_text_page_count / page_count >= OCR_PAGE_RATIO_THRESHOLD:
        return True, "most_pages_have_little_extractable_text"
    return False, ""
