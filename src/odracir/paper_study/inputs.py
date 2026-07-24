"""Paper-local input discovery for Odracir 2.2."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import Field

from odracir.paper_study.models import StrictModel
from odracir.paper_study.planning import load_chunk_artifact


_PATH_KEYS = (
    "source_path",
    "chunk_path",
    "chunk_artifact",
    "artifact_path",
    "path",
    "file",
)
_ID_KEYS = ("paper_id", "id")


class PaperIndexEntry(StrictModel):
    """One independently processed paper and its prepared chunk artifact."""

    paper_id: str = Field(min_length=1)
    source_path: str = Field(min_length=1)
    metadata: dict[str, str] = Field(default_factory=dict)


def discover_paper_entries(
    paper_folder: str | Path,
    *,
    index_path: str | Path | None = None,
) -> list[PaperIndexEntry]:
    """Discover prepared chunks, optionally through a JSON index."""

    folder = Path(paper_folder).expanduser().resolve()
    if not folder.is_dir():
        raise ValueError(f"paper_folder is not a directory: {folder}")
    if index_path is None:
        conventional = folder / "odracir_index.json"
        selected_index = conventional if conventional.is_file() else None
    else:
        candidate = Path(index_path).expanduser()
        selected_index = (
            candidate if candidate.is_absolute() else folder / candidate
        ).resolve()
        if not selected_index.is_file():
            raise ValueError(f"paper index does not exist: {selected_index}")
    if selected_index is not None:
        return load_paper_index(selected_index, paper_folder=folder)

    chunks_root = (
        folder if folder.name == "chunks" else folder / ".odracir" / "chunks"
    )
    candidates = sorted(chunks_root.glob("*.json"))
    if not candidates:
        candidates = sorted(folder.glob("**/.odracir/chunks/*.json"))
    if not candidates:
        raise ValueError("no .odracir/chunks/*.json artifacts were found")
    entries = [
        PaperIndexEntry(
            paper_id=load_chunk_artifact(path).paper_id,
            source_path=str(path.resolve()),
            metadata={"discovery": "chunk_glob"},
        )
        for path in candidates
    ]
    _validate_unique(entries)
    return sorted(entries, key=lambda item: (item.paper_id.casefold(), item.source_path))


def load_paper_index(
    index_path: str | Path,
    *,
    paper_folder: str | Path | None = None,
) -> list[PaperIndexEntry]:
    """Load a JSON list or an object containing ``papers`` or ``items``."""

    source = Path(index_path).expanduser().resolve()
    payload = json.loads(source.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        raw_items = payload
    elif isinstance(payload, dict):
        keys = [key for key in ("papers", "items") if key in payload]
        if len(keys) != 1 or not isinstance(payload[keys[0]], list):
            raise ValueError(
                "index object must contain exactly one list: papers or items"
            )
        raw_items = payload[keys[0]]
    else:
        raise ValueError("paper index must be a JSON list or object")
    base = (
        Path(paper_folder).expanduser().resolve()
        if paper_folder
        else source.parent
    )
    entries = [
        _normalize_index_entry(item, item_number=number, base_folder=base)
        for number, item in enumerate(raw_items, start=1)
    ]
    if not entries:
        raise ValueError(f"paper index contains no entries: {source}")
    _validate_unique(entries)
    return sorted(entries, key=lambda item: (item.paper_id.casefold(), item.source_path))


def _normalize_index_entry(
    item: Any,
    *,
    item_number: int,
    base_folder: Path,
) -> PaperIndexEntry:
    if isinstance(item, str):
        raw_path, paper_id, metadata = item, None, {}
    elif isinstance(item, Mapping):
        raw_path = _first_present(item, _PATH_KEYS)
        paper_id = _first_present(item, _ID_KEYS)
        raw_metadata = item.get("metadata", {})
        if not isinstance(raw_metadata, Mapping):
            raise ValueError(f"index item {item_number} metadata must be an object")
        metadata = {
            str(key): str(value)
            for key, value in raw_metadata.items()
            if value is not None
        }
    else:
        raise ValueError(f"index item {item_number} must be a path string or object")
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValueError(f"index item {item_number} has no non-empty source path")
    path = Path(raw_path).expanduser()
    resolved = (path if path.is_absolute() else base_folder / path).resolve()
    normalized_id = resolved.stem if paper_id in (None, "") else str(paper_id).strip()
    if not normalized_id:
        raise ValueError(f"index item {item_number} has an empty paper_id")
    return PaperIndexEntry(
        paper_id=normalized_id,
        source_path=str(resolved),
        metadata=metadata,
    )


def _first_present(item: Mapping[Any, Any], keys: tuple[str, ...]) -> Any:
    return next((item[key] for key in keys if key in item), None)


def _validate_unique(entries: list[PaperIndexEntry]) -> None:
    ids = [entry.paper_id for entry in entries]
    duplicates = sorted(
        paper_id for paper_id in set(ids) if ids.count(paper_id) > 1
    )
    if duplicates:
        raise ValueError(f"duplicate paper IDs: {duplicates}")
