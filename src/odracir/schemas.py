"""Typed schemas and validation helpers for Odracir artifacts."""

from __future__ import annotations

from enum import Enum
from typing import Any, TypedDict


INDEX_SCHEMA_VERSION = "0.2"
TEXT_SCHEMA_VERSION = "0.2"
CHUNK_SCHEMA_VERSION = "0.1"
SUMMARY_SCHEMA_VERSION = "0.1"


class ExtractionStatus(str, Enum):
    NOT_STARTED = "not_started"
    EXTRACTED = "extracted"
    NEEDS_OCR = "needs_ocr"
    FAILED = "failed"


class ChunkingStatus(str, Enum):
    NOT_STARTED = "not_started"
    CHUNKED = "chunked"
    FAILED = "failed"
    BLOCKED = "blocked"


class PaperRecord(TypedDict, total=False):
    id: str
    title: str
    authors: list[str]
    year: int | None
    source_file: str
    file_name: str
    file_type: str
    file_size_bytes: int
    sha256: str
    status: str
    text_extraction_status: str
    text_extraction_sha256: str
    text_extraction_error: str
    text_artifact: str
    text_parser: str
    text_parser_version: str
    page_count: int
    text_char_count: int
    empty_text_page_count: int
    needs_ocr: bool
    ocr_reason: str
    text_extracted_at: str
    chunking_status: str
    chunking_sha256: str
    chunk_artifact: str
    chunk_count: int
    chunking_error: str
    chunked_at: str
    translation_status: str
    summary_status: str
    summary_artifact: str
    summary_input_sha256: str
    summary_provider: str
    summary_model: str
    summary_prompt_version: str
    summary_error: str
    summarized_at: str


class ProjectIndex(TypedDict, total=False):
    schema_version: str
    folder_name: str
    generated_by: str
    updated_at: str | None
    papers: list[PaperRecord]


class TextPage(TypedDict):
    page_number: int
    text: str
    char_count: int


class TextArtifact(TypedDict, total=False):
    schema_version: str
    paper_id: str
    source_file: str
    source_sha256: str
    parser: str
    parser_version: str
    extracted_at: str
    page_count: int
    text_char_count: int
    empty_text_page_count: int
    needs_ocr: bool
    ocr_reason: str
    metadata: dict[str, Any]
    pages: list[TextPage]


class ChunkRecord(TypedDict):
    id: str
    ordinal: int
    section_hint: str
    page_start: int
    page_end: int
    char_count: int
    token_estimate: int
    content_sha256: str
    text: str


class ChunkArtifact(TypedDict):
    schema_version: str
    paper_id: str
    source_file: str
    source_sha256: str
    text_artifact: str
    text_artifact_sha256: str
    chunker: str
    chunker_version: str
    chunked_at: str
    chunk_count: int
    chunks: list[ChunkRecord]


class EvidenceFinding(TypedDict, total=False):
    claim: str
    citations: list[str]
    inference: bool


class SummaryArtifact(TypedDict, total=False):
    schema_version: str
    paper_id: str
    source_file: str
    source_sha256: str
    chunk_artifact: str
    chunk_artifact_sha256: str
    provider: str
    model: str
    prompt_version: str
    summarized_at: str
    usage: dict[str, int]
    map_summaries: list[dict[str, Any]]
    summary: dict[str, Any]


def validate_project_index(index: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(index, dict):
        return ["index must be a JSON object"]

    papers = index.get("papers")
    if not isinstance(papers, list):
        return ["papers must be a list"]

    seen_ids: set[str] = set()
    seen_sources: set[str] = set()
    for position, paper in enumerate(papers):
        prefix = f"papers[{position}]"
        if not isinstance(paper, dict):
            errors.append(f"{prefix} must be an object")
            continue

        paper_id = paper.get("id")
        source_file = paper.get("source_file")
        sha256 = paper.get("sha256")
        if not isinstance(paper_id, str) or not paper_id:
            errors.append(f"{prefix}.id must be a non-empty string")
        elif paper_id in seen_ids:
            errors.append(f"{prefix}.id duplicates {paper_id!r}")
        else:
            seen_ids.add(paper_id)

        if not isinstance(source_file, str) or not source_file:
            errors.append(f"{prefix}.source_file must be a non-empty string")
        elif source_file in seen_sources:
            errors.append(f"{prefix}.source_file duplicates {source_file!r}")
        else:
            seen_sources.add(source_file)

        if not isinstance(sha256, str) or len(sha256) != 64:
            errors.append(f"{prefix}.sha256 must be a 64-character hash")

    return errors


def require_valid_project_index(index: dict[str, Any]) -> None:
    errors = validate_project_index(index)
    if errors:
        details = "; ".join(errors)
        raise ValueError(f"Invalid odracir_index.json: {details}")
