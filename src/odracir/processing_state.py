"""Shared downstream invalidation for generated research artifacts."""

from __future__ import annotations

from typing import Any


def invalidate_text_extraction(paper: dict[str, Any]) -> None:
    paper["text_extraction_status"] = "not_started"
    for field in (
        "text_extraction_sha256",
        "text_extraction_input_sha256",
        "text_extraction_error",
        "text_artifact",
        "text_extracted_from",
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


def invalidate_ocr(paper: dict[str, Any]) -> None:
    paper["ocr_status"] = "not_started"
    for field in (
        "ocr_artifact",
        "ocr_artifact_sha256",
        "ocr_source_sha256",
        "ocr_provider",
        "ocr_provider_version",
        "ocr_languages",
        "ocr_deskew",
        "ocr_processed_at",
        "ocr_error",
    ):
        paper.pop(field, None)
    invalidate_text_extraction(paper)


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
    invalidate_translation(paper)


def invalidate_summary(paper: dict[str, Any]) -> None:
    paper["summary_status"] = "not_started"
    for field in (
        "summary_artifact",
        "summary_input_sha256",
        "summary_provider",
        "summary_model",
        "summary_prompt_version",
        "summary_skill",
        "summary_skill_version",
        "summary_error",
        "summarized_at",
    ):
        paper.pop(field, None)
    paper["summary_short"] = ""
    paper["summary_detailed"] = ""


def invalidate_translation(paper: dict[str, Any]) -> None:
    paper["translation_status"] = "not_started"
    for field in (
        "translation_artifact",
        "translation_input_sha256",
        "translation_selection_sha256",
        "translation_provider",
        "translation_model",
        "translation_prompt_version",
        "translation_target_language",
        "translated_chunk_count",
        "translation_error",
        "translated_at",
    ):
        paper.pop(field, None)
