"""Shared downstream invalidation for generated research artifacts."""

from __future__ import annotations

from typing import Any


def invalidate_text_extraction(paper: dict[str, Any]) -> None:
    paper["text_extraction_status"] = "not_started"
    for field in (
        "text_extraction_sha256",
        "text_extraction_error",
        "text_artifact",
        "page_count",
        "text_char_count",
        "empty_text_page_count",
        "needs_ocr",
        "ocr_reason",
        "text_extracted_at",
        "text_parser",
        "text_parser_version",
    ):
        paper.pop(field, None)
    invalidate_chunking(paper)


def invalidate_chunking(paper: dict[str, Any]) -> None:
    paper["chunking_status"] = "not_started"
    for field in (
        "chunking_sha256",
        "chunk_artifact",
        "chunk_count",
        "chunked_at",
        "chunking_error",
    ):
        paper.pop(field, None)
    invalidate_summary(paper)


def invalidate_summary(paper: dict[str, Any]) -> None:
    paper["summary_status"] = "not_started"
    for field in (
        "summary_artifact",
        "summary_input_sha256",
        "summary_provider",
        "summary_model",
        "summary_prompt_version",
        "summary_error",
        "summarized_at",
    ):
        paper.pop(field, None)
    paper["summary_short"] = ""
    paper["summary_detailed"] = ""
    paper["translation_status"] = "not_started"
