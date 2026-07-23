"""Preserve raw model readings when structured summary decoding fails."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

from odracir.processing_state import invalidate_summary
from odracir.providers import JsonCompletionError, JsonCompletionProvider
from odracir.schemas import RAW_SUMMARY_SCHEMA_VERSION
from odracir.time_utils import now_iso


class RawSummaryCapture(Exception):
    """Carry preserved raw model output from a failed structured decode."""

    def __init__(self, stage: str, error: JsonCompletionError) -> None:
        super().__init__(str(error))
        self.stage = stage
        self.error = error


def capture_raw_summary(
    root: Path,
    *,
    paper: dict[str, Any],
    chunk_artifact_path: Path,
    chunk_artifact_sha256: str,
    provider: JsonCompletionProvider,
    capture: RawSummaryCapture,
    prompt_version: str,
) -> dict[str, Any]:
    """Archive raw output and update a stable latest pointer."""
    captured_at = now_iso()
    capture_id = f"{re.sub(r'[^0-9A-Za-z]+', '', captured_at)}-{uuid4().hex[:8]}"
    raw_dir = root / ".odracir" / "raw-summaries" / _safe_name(str(paper["id"]))
    artifact_path = raw_dir / f"{capture_id}.json"
    latest_path = raw_dir / "latest.json"
    artifact = {
        "schema_version": RAW_SUMMARY_SCHEMA_VERSION,
        "paper_id": paper["id"],
        "source_file": paper["source_file"],
        "source_sha256": paper["sha256"],
        "chunk_artifact": chunk_artifact_path.relative_to(root).as_posix(),
        "chunk_artifact_sha256": chunk_artifact_sha256,
        "provider": provider.provider_name,
        "model": provider.model,
        "prompt_version": prompt_version,
        "captured_at": captured_at,
        "stage": capture.stage,
        "finish_reason": capture.error.finish_reason,
        "max_tokens": capture.error.max_tokens,
        "usage": capture.error.usage,
        "error": str(capture.error),
        "content": capture.error.content,
    }
    _write_json_atomic(artifact_path, artifact)
    _write_json_atomic(latest_path, artifact)
    return {
        **artifact,
        "artifact_path": artifact_path.relative_to(root).as_posix(),
        "latest_artifact_path": latest_path.relative_to(root).as_posix(),
    }


def mark_raw_captured(
    root: Path,
    paper: dict[str, Any],
    *,
    artifact: dict[str, Any],
    artifact_path: Path,
    chunk_artifact_sha256: str,
    provider: JsonCompletionProvider,
) -> None:
    """Expose a preserved raw reading through portable index state."""
    invalidate_summary(paper)
    paper["summary_status"] = "raw_captured"
    paper["raw_summary_artifact"] = artifact_path.relative_to(root).as_posix()
    paper["raw_summary_input_sha256"] = chunk_artifact_sha256
    paper["raw_summary_provider"] = provider.provider_name
    paper["raw_summary_model"] = provider.model
    paper["raw_summary_prompt_version"] = str(artifact["prompt_version"])
    paper["raw_summary_stage"] = str(artifact["stage"])
    paper["raw_summary_finish_reason"] = str(artifact["finish_reason"])
    paper["raw_summary_error"] = str(artifact["error"])
    paper["raw_summary_captured_at"] = str(artifact["captured_at"])
    paper["summary_error"] = str(artifact["error"])
    paper["updated_at"] = now_iso()


def _safe_name(value: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value).strip("-")
    return safe or "paper"


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(f"{path.suffix}.{uuid4().hex}.tmp")
    with temporary_path.open("w", encoding="utf-8", newline="\n") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
        file.write("\n")
    temporary_path.replace(path)
