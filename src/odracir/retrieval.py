"""Inspectable lexical retrieval over traceable research chunks."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from odracir.research_folder import ResearchFolderHarness


MAX_SNIPPET_CHARS = 360


@dataclass(frozen=True)
class SearchHit:
    paper_id: str
    title: str
    source_file: str
    chunk_id: str
    section_hint: str
    page_start: int
    page_end: int
    score: int
    citation: str
    snippet: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SearchReport:
    root: str
    query: str
    searched_papers: int
    searched_chunks: int
    hits: list[SearchHit]

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["hits"] = [hit.as_dict() for hit in self.hits]
        return payload


def search_chunks(
    root: str | Path,
    query: str,
    *,
    limit: int = 5,
) -> SearchReport:
    """Return ranked local chunk matches with stable source citations."""
    clean_query = query.strip()
    if not clean_query:
        raise ValueError("Search query must not be empty.")
    if limit < 1:
        raise ValueError("Search limit must be at least 1.")

    harness = ResearchFolderHarness(root)
    index = harness.load_index()
    query_tokens = _tokenize(clean_query)
    if not query_tokens:
        raise ValueError("Search query must contain searchable text.")

    papers = [
        paper
        for paper in index.get("papers", [])
        if isinstance(paper, dict)
        and paper.get("status") != "missing"
        and paper.get("chunking_status") == "chunked"
        and paper.get("chunk_artifact")
    ]
    searched_chunks = 0
    hits: list[SearchHit] = []
    for paper in papers:
        artifact = _load_json(harness.root / str(paper["chunk_artifact"]))
        chunks = artifact.get("chunks", [])
        if not isinstance(chunks, list):
            raise ValueError(f"{paper['chunk_artifact']} must contain a chunks list.")
        for chunk in chunks:
            if not isinstance(chunk, dict):
                continue
            searched_chunks += 1
            text = str(chunk.get("text", ""))
            score = _score_text(text, clean_query, query_tokens)
            if score == 0:
                continue
            page_start = int(chunk.get("page_start", 0))
            page_end = int(chunk.get("page_end", page_start))
            paper_id = str(paper.get("id", ""))
            chunk_id = str(chunk.get("id", ""))
            hits.append(
                SearchHit(
                    paper_id=paper_id,
                    title=str(paper.get("title", "")),
                    source_file=str(paper.get("source_file", "")),
                    chunk_id=chunk_id,
                    section_hint=str(chunk.get("section_hint", "")),
                    page_start=page_start,
                    page_end=page_end,
                    score=score,
                    citation=_citation(paper_id, page_start, page_end, chunk_id),
                    snippet=_snippet(text, clean_query, query_tokens),
                )
            )

    hits.sort(key=lambda hit: (-hit.score, hit.paper_id, hit.page_start, hit.chunk_id))
    return SearchReport(
        root=str(harness.root),
        query=clean_query,
        searched_papers=len(papers),
        searched_chunks=searched_chunks,
        hits=hits[:limit],
    )


def format_search_report(report: SearchReport) -> str:
    lines = [
        f"Research folder: {report.root}",
        f"Query: {report.query}",
        f"Searched: {report.searched_papers} papers, {report.searched_chunks} chunks",
        f"Hits: {len(report.hits)}",
    ]
    for hit in report.hits:
        lines.append(f"- {hit.citation} score={hit.score}")
        if hit.section_hint:
            lines.append(f"  Section: {hit.section_hint}")
        lines.append(f"  {hit.snippet}")
    return "\n".join(lines)


def _score_text(text: str, query: str, query_tokens: list[str]) -> int:
    lowered = text.lower()
    score = 0
    for token in query_tokens:
        count = lowered.count(token)
        if count:
            score += 2 + min(count, 8)
    if query.lower() in lowered:
        score += 8
    return score


def _snippet(text: str, query: str, query_tokens: list[str]) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    lowered = compact.lower()
    positions = [lowered.find(query.lower())]
    positions.extend(lowered.find(token) for token in query_tokens)
    positions = [position for position in positions if position >= 0]
    start = max(0, (min(positions) if positions else 0) - MAX_SNIPPET_CHARS // 3)
    end = min(len(compact), start + MAX_SNIPPET_CHARS)
    snippet = compact[start:end]
    if start:
        snippet = f"...{snippet}"
    if end < len(compact):
        snippet = f"{snippet}..."
    return snippet


def _citation(paper_id: str, page_start: int, page_end: int, chunk_id: str) -> str:
    pages = str(page_start) if page_start == page_end else f"{page_start}-{page_end}"
    return f"[{paper_id} pp.{pages} chunk:{chunk_id}]"


def _tokenize(text: str) -> list[str]:
    return list(
        dict.fromkeys(re.findall(r"[a-z0-9][a-z0-9_-]*|[\u4e00-\u9fff]", text.lower()))
    )


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object.")
    return payload
