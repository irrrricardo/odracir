"""Research-folder harness for Odracir."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


DEFAULT_INDEX_NAME = "odracir_index.json"
PAPER_EXTENSIONS = {".pdf", ".txt", ".md"}
SCHEMA_VERSION = "0.1"


@dataclass(frozen=True)
class ResearchFolderSyncResult:
    root: str
    index_path: str
    total_papers: int
    new_papers: int
    updated_papers: int
    missing_papers: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class ResearchFolderHarness:
    """Maintain the local folder layout and JSON memory for a research project."""

    def __init__(self, root: str | Path, papers_dir: str | Path | None = None) -> None:
        self.root = Path(root).expanduser().resolve()
        self.papers_dir = self._resolve_papers_dir(papers_dir)
        self.notes_dir = self.root / "notes"
        self.code_dir = self.root / "code"
        self.index_path = self.root / DEFAULT_INDEX_NAME

    def ensure_layout(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.papers_dir.mkdir(exist_ok=True)
        self.notes_dir.mkdir(exist_ok=True)
        self.code_dir.mkdir(exist_ok=True)

    def _resolve_papers_dir(self, papers_dir: str | Path | None) -> Path:
        if papers_dir is None:
            return self.root / "papers"

        path = Path(papers_dir).expanduser()
        if path.is_absolute():
            return path.resolve()

        return (self.root / path).resolve()

    def sync_index(self) -> ResearchFolderSyncResult:
        self.ensure_layout()

        now = _now_iso()
        index = self.load_index()
        existing_papers = index.get("papers", [])
        existing_by_source = {
            paper.get("source_file"): paper
            for paper in existing_papers
            if isinstance(paper, dict) and paper.get("source_file")
        }

        papers: list[dict[str, Any]] = []
        seen_sources: set[str] = set()
        used_ids: set[str] = set()
        new_count = 0
        updated_count = 0

        for paper_path in self.scan_papers():
            source_file = _relative_posix(paper_path, self.root)
            seen_sources.add(source_file)
            file_hash = _sha256_file(paper_path)
            existing = existing_by_source.get(source_file)

            if existing is None:
                new_count += 1
                record = self._new_paper_record(paper_path, file_hash, used_ids, now)
            else:
                previous_hash = existing.get("sha256")
                record = self._merge_paper_record(existing, paper_path, file_hash, used_ids, now)
                if previous_hash != file_hash:
                    updated_count += 1

            used_ids.add(record["id"])
            papers.append(record)

        missing_count = 0
        for existing in existing_papers:
            source_file = existing.get("source_file") if isinstance(existing, dict) else None
            if not source_file or source_file in seen_sources:
                continue

            missing_count += 1
            missing_record = dict(existing)
            missing_record["status"] = "missing"
            missing_record["updated_at"] = now
            if missing_record.get("id"):
                used_ids.add(str(missing_record["id"]))
            papers.append(missing_record)

        index.update(
            {
                "schema_version": SCHEMA_VERSION,
                "folder_name": self.root.name,
                "generated_by": "odracir",
                "updated_at": now,
                "papers": papers,
            }
        )
        self.write_index(index)

        return ResearchFolderSyncResult(
            root=str(self.root),
            index_path=str(self.index_path),
            total_papers=len(papers),
            new_papers=new_count,
            updated_papers=updated_count,
            missing_papers=missing_count,
        )

    def scan_papers(self) -> list[Path]:
        if not self.papers_dir.exists():
            return []

        return sorted(
            path
            for path in self.papers_dir.rglob("*")
            if path.is_file() and path.suffix.lower() in PAPER_EXTENSIONS
        )

    def load_index(self) -> dict[str, Any]:
        if not self.index_path.exists():
            return {
                "schema_version": SCHEMA_VERSION,
                "folder_name": self.root.name,
                "generated_by": "odracir",
                "updated_at": None,
                "papers": [],
            }

        with self.index_path.open("r", encoding="utf-8") as file:
            data = json.load(file)

        if not isinstance(data, dict):
            raise ValueError(f"{self.index_path} must contain a JSON object.")

        data.setdefault("papers", [])
        return data

    def write_index(self, index: dict[str, Any]) -> None:
        with self.index_path.open("w", encoding="utf-8", newline="\n") as file:
            json.dump(index, file, ensure_ascii=False, indent=2)
            file.write("\n")

    def _new_paper_record(
        self,
        paper_path: Path,
        file_hash: str,
        used_ids: set[str],
        now: str,
    ) -> dict[str, Any]:
        return {
            "id": _paper_id(paper_path, self.root, used_ids),
            "title": paper_path.stem,
            "authors": [],
            "year": None,
            "source_file": _relative_posix(paper_path, self.root),
            "file_name": paper_path.name,
            "file_type": paper_path.suffix.lower().lstrip("."),
            "file_size_bytes": paper_path.stat().st_size,
            "sha256": file_hash,
            "status": "indexed",
            "translation_status": "not_started",
            "summary_status": "not_started",
            "research_area": "",
            "core_problem": "",
            "main_contribution": "",
            "methods": [],
            "datasets": [],
            "experiments": [],
            "limitations": [],
            "implementation_notes": [],
            "summary_short": "",
            "summary_detailed": "",
            "notes": [],
            "added_at": now,
            "updated_at": now,
        }

    def _merge_paper_record(
        self,
        existing: dict[str, Any],
        paper_path: Path,
        file_hash: str,
        used_ids: set[str],
        now: str,
    ) -> dict[str, Any]:
        record = dict(existing)
        record.setdefault("id", _paper_id(paper_path, self.root, used_ids))
        record.setdefault("title", paper_path.stem)
        record.setdefault("authors", [])
        record.setdefault("year", None)
        record["source_file"] = _relative_posix(paper_path, self.root)
        record["file_name"] = paper_path.name
        record["file_type"] = paper_path.suffix.lower().lstrip(".")
        record["file_size_bytes"] = paper_path.stat().st_size
        record["sha256"] = file_hash
        record["status"] = "indexed"
        record.setdefault("translation_status", "not_started")
        record.setdefault("summary_status", "not_started")
        record.setdefault("research_area", "")
        record.setdefault("core_problem", "")
        record.setdefault("main_contribution", "")
        record.setdefault("methods", [])
        record.setdefault("datasets", [])
        record.setdefault("experiments", [])
        record.setdefault("limitations", [])
        record.setdefault("implementation_notes", [])
        record.setdefault("summary_short", "")
        record.setdefault("summary_detailed", "")
        record.setdefault("notes", [])
        record.setdefault("added_at", now)
        record["updated_at"] = now
        return record


def _now_iso() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")


def _relative_posix(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _paper_id(path: Path, root: Path, used_ids: set[str]) -> str:
    stem = re.sub(r"[^a-zA-Z0-9]+", "-", path.stem).strip("-").lower()
    base = stem or "paper"

    if base not in used_ids:
        return base

    rel_hash = hashlib.sha1(_relative_posix(path, root).encode("utf-8")).hexdigest()[:8]
    return f"{base}-{rel_hash}"
