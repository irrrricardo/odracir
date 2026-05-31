"""Deterministic, page-traceable text chunking."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from odracir.processing_state import invalidate_chunking, invalidate_summary
from odracir.research_folder import ResearchFolderHarness
from odracir.schemas import CHUNK_SCHEMA_VERSION, ChunkingStatus
from odracir.time_utils import now_iso


CHUNKER_NAME = "section-aware-character-chunker"
CHUNKER_VERSION = "0.1"
DEFAULT_TARGET_CHARS = 6000
DEFAULT_MAX_CHARS = 8000


@dataclass(frozen=True)
class ChunkingSummary:
    root: str
    index_path: str
    eligible_papers: int
    chunked: int
    skipped: int
    blocked: int
    failed: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class TextChunker:
    """Create stable chunks from extracted page-level text artifacts."""

    def __init__(self, root: str | Path, papers_dir: str | Path | None = None) -> None:
        self.harness = ResearchFolderHarness(root, papers_dir=papers_dir)
        self.root = self.harness.root
        self.chunks_dir = self.root / ".odracir" / "chunks"

    def chunk_index(
        self,
        *,
        force: bool = False,
        limit: int | None = None,
        paper_id: str | None = None,
    ) -> ChunkingSummary:
        self.harness.sync_index()
        self.chunks_dir.mkdir(parents=True, exist_ok=True)
        index = self.harness.load_index()
        records = [
            paper
            for paper in index.get("papers", [])
            if isinstance(paper, dict)
            and paper.get("file_type") == "pdf"
            and paper.get("status") != "missing"
            and (paper_id is None or paper.get("id") == paper_id)
        ]
        if limit is not None:
            records = records[:limit]

        chunked = 0
        skipped = 0
        blocked = 0
        failed = 0

        for paper in records:
            text_artifact_path = self._text_artifact_path(paper)
            chunk_artifact_path = self._chunk_artifact_path(paper)

            if not self._is_ready(paper, text_artifact_path):
                blocked += 1
                _mark_blocked(paper)
                continue

            text_artifact_sha256 = _sha256_file(text_artifact_path)
            if self._can_skip(paper, chunk_artifact_path, text_artifact_sha256, force):
                skipped += 1
                continue

            try:
                text_artifact = _load_json(text_artifact_path)
                chunks = chunk_pages(text_artifact.get("pages", []), str(paper["id"]))
                payload = {
                    "schema_version": CHUNK_SCHEMA_VERSION,
                    "paper_id": paper["id"],
                    "source_file": paper["source_file"],
                    "source_sha256": paper["sha256"],
                    "text_artifact": text_artifact_path.relative_to(self.root).as_posix(),
                    "text_artifact_sha256": text_artifact_sha256,
                    "chunker": CHUNKER_NAME,
                    "chunker_version": CHUNKER_VERSION,
                    "chunked_at": now_iso(),
                    "chunk_count": len(chunks),
                    "chunks": chunks,
                }
                _write_json(chunk_artifact_path, payload)
            except Exception as exc:  # noqa: BLE001 - preserve batch progress.
                failed += 1
                _mark_failed(paper, exc)
                continue

            _mark_chunked(
                paper=paper,
                artifact_path=chunk_artifact_path,
                root=self.root,
                text_artifact_sha256=text_artifact_sha256,
                chunk_count=len(chunks),
            )
            chunked += 1

        index["updated_at"] = now_iso()
        self.harness.write_index(index)
        return ChunkingSummary(
            root=str(self.root),
            index_path=str(self.harness.index_path),
            eligible_papers=len(records),
            chunked=chunked,
            skipped=skipped,
            blocked=blocked,
            failed=failed,
        )

    def _text_artifact_path(self, paper: dict[str, Any]) -> Path:
        artifact = paper.get("text_artifact")
        return self.root / str(artifact or "")

    def _chunk_artifact_path(self, paper: dict[str, Any]) -> Path:
        return self.chunks_dir / f"{_safe_name(str(paper['id']))}.json"

    def _is_ready(self, paper: dict[str, Any], artifact_path: Path) -> bool:
        return (
            paper.get("text_extraction_status") == "extracted"
            and bool(paper.get("text_artifact"))
            and artifact_path.is_file()
        )

    def _can_skip(
        self,
        paper: dict[str, Any],
        artifact_path: Path,
        text_artifact_sha256: str,
        force: bool,
    ) -> bool:
        if force or not artifact_path.exists():
            return False
        return (
            paper.get("chunking_status") == ChunkingStatus.CHUNKED.value
            and paper.get("chunking_sha256") == text_artifact_sha256
        )


def chunk_pages(
    pages: list[dict[str, Any]],
    paper_id: str,
    *,
    target_chars: int = DEFAULT_TARGET_CHARS,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> list[dict[str, Any]]:
    fragments = _page_fragments(pages, max_chars=max_chars)
    chunks: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    current_chars = 0
    section_hint = ""

    def flush() -> None:
        nonlocal current, current_chars
        if not current:
            return
        text = "\n\n".join(fragment["text"] for fragment in current).strip()
        if not text:
            current = []
            current_chars = 0
            return
        ordinal = len(chunks) + 1
        page_start = min(fragment["page_number"] for fragment in current)
        page_end = max(fragment["page_number"] for fragment in current)
        content_sha256 = _sha256_text(text)
        chunk_id = _sha256_text(
            f"{paper_id}:{ordinal}:{page_start}:{page_end}:{content_sha256}"
        )[:20]
        chunks.append(
            {
                "id": chunk_id,
                "ordinal": ordinal,
                "section_hint": current[0]["section_hint"],
                "page_start": page_start,
                "page_end": page_end,
                "char_count": len(text),
                "token_estimate": max(1, (len(text) + 3) // 4),
                "content_sha256": content_sha256,
                "text": text,
            }
        )
        current = []
        current_chars = 0

    for fragment in fragments:
        heading = _heading_hint(fragment["text"])
        if heading:
            section_hint = heading
        fragment["section_hint"] = section_hint
        fragment_chars = len(fragment["text"])
        if current and current_chars + fragment_chars > target_chars:
            flush()
        current.append(fragment)
        current_chars += fragment_chars
        if current_chars >= max_chars:
            flush()

    flush()
    return chunks


def _page_fragments(pages: list[dict[str, Any]], *, max_chars: int) -> list[dict[str, Any]]:
    fragments: list[dict[str, Any]] = []
    for page in pages:
        page_number = int(page.get("page_number", 0))
        text = str(page.get("text", "")).strip()
        if not text:
            continue
        for paragraph in re.split(r"\n\s*\n", text):
            paragraph = paragraph.strip()
            if not paragraph:
                continue
            for start in range(0, len(paragraph), max_chars):
                fragments.append(
                    {
                        "page_number": page_number,
                        "text": paragraph[start : start + max_chars],
                    }
                )
    return fragments


def _heading_hint(text: str) -> str:
    first_line = text.splitlines()[0].strip()
    if len(first_line) > 120:
        return ""
    if re.match(r"^(\d+(\.\d+)*[.)]?\s+|[A-Z][A-Z\s-]{3,}$)", first_line):
        return first_line
    return ""


def _mark_chunked(
    *,
    paper: dict[str, Any],
    artifact_path: Path,
    root: Path,
    text_artifact_sha256: str,
    chunk_count: int,
) -> None:
    paper["chunking_status"] = ChunkingStatus.CHUNKED.value
    paper["chunking_sha256"] = text_artifact_sha256
    paper["chunk_artifact"] = artifact_path.relative_to(root).as_posix()
    paper["chunk_count"] = chunk_count
    paper["chunked_at"] = now_iso()
    paper.pop("chunking_error", None)
    invalidate_summary(paper)
    paper["updated_at"] = now_iso()


def _mark_blocked(paper: dict[str, Any]) -> None:
    invalidate_chunking(paper)
    paper["chunking_status"] = ChunkingStatus.BLOCKED.value
    paper["chunking_error"] = "text extraction must succeed before chunking"
    paper["updated_at"] = now_iso()


def _mark_failed(paper: dict[str, Any], exc: Exception) -> None:
    invalidate_chunking(paper)
    paper["chunking_status"] = ChunkingStatus.FAILED.value
    paper["chunking_error"] = str(exc)
    paper["updated_at"] = now_iso()


def _safe_name(value: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value).strip("-")
    return safe or "paper"


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
        file.write("\n")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
