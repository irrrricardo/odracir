"""Deterministic, explainable reading priorities for one research folder."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from odracir.research_folder import ResearchFolderHarness
from odracir.research_memory import ResearchCatalogBuilder
from odracir.schemas import READING_QUEUE_SCHEMA_VERSION
from odracir.skills import ResearchSkillManifest, ResearchSkillRegistry, get_builtin_skill_registry
from odracir.time_utils import now_iso


READING_QUEUE_POLICY_VERSION = "0.1"
DEFAULT_QUEUE_LIMIT = 5
MAX_QUERY_EVIDENCE = 3
MAX_SNIPPET_CHARS = 240
STOPWORDS = {
    "a",
    "an",
    "and",
    "based",
    "for",
    "from",
    "in",
    "of",
    "on",
    "the",
    "to",
    "using",
    "with",
}


@dataclass(frozen=True)
class ReadingQueueEntry:
    rank: int
    paper_id: str
    title: str
    source_file: str
    priority_score: int
    action: str
    readiness: str
    summary_quality: str
    query_score: int
    centrality_score: int
    workload_chunks: int
    workload_chars: int
    reasons: list[str]
    query_evidence: list[dict[str, Any]]
    next_commands: list[str]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ReadingQueueReport:
    root: str
    artifact_path: str | None
    cached: bool
    policy_version: str
    generated_at: str
    input_sha256: str
    query: str | None
    skill: dict[str, Any]
    total_papers: int
    queue_limit: int
    action_counts: dict[str, int]
    entries: list[ReadingQueueEntry]

    def as_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "entries": [entry.as_dict() for entry in self.entries],
        }


class ReadingQueueBuilder:
    """Build cached local reading priorities without invoking an LLM."""

    def __init__(
        self,
        root: str | Path,
        papers_dir: str | Path | None = None,
        *,
        skill_registry: ResearchSkillRegistry | None = None,
    ) -> None:
        self.harness = ResearchFolderHarness(root, papers_dir=papers_dir)
        self.root = self.harness.root
        self.queues_dir = self.root / ".odracir" / "planning" / "reading-queues"
        self.skill_registry = skill_registry or get_builtin_skill_registry()

    def build(
        self,
        *,
        query: str | None = None,
        skill_name: str = "generic",
        limit: int = DEFAULT_QUEUE_LIMIT,
        force: bool = False,
        write_artifact: bool = True,
    ) -> ReadingQueueReport:
        if limit < 1:
            raise ValueError("Reading queue limit must be at least 1.")
        clean_query = query.strip() if query else None
        if query is not None and not clean_query:
            raise ValueError("Reading queue query must not be empty.")
        skill = self.skill_registry.get(skill_name)
        catalog = ResearchCatalogBuilder(
            self.root,
            papers_dir=self.harness.papers_dir,
            skill_registry=self.skill_registry,
        ).build(write_artifact=False)
        input_sha256 = _input_sha256(
            self.root,
            catalog_input_sha256=catalog.input_sha256,
            records=catalog.records,
            query=clean_query,
            skill=skill,
            limit=limit,
        )
        artifact_path = self.queues_dir / f"{input_sha256[:20]}.json"
        if write_artifact and not force and artifact_path.is_file():
            artifact = _load_json(artifact_path)
            if _can_use_cached(artifact, input_sha256=input_sha256):
                return _report_from_artifact(
                    root=self.root,
                    artifact_path=artifact_path,
                    artifact=artifact,
                    cached=True,
                )

        contexts = [
            _build_context(self.root, record, query=clean_query)
            for record in catalog.records
        ]
        title_document_frequency = Counter(
            token for context in contexts for token in context["title_tokens"]
        )
        ranked = [
            _build_entry(
                self.harness,
                context,
                query=clean_query,
                skill=skill,
                title_document_frequency=title_document_frequency,
            )
            for context in contexts
        ]
        ranked.sort(
            key=lambda entry: (
                -entry.priority_score,
                -entry.query_score,
                -entry.centrality_score,
                entry.paper_id,
            )
        )
        entries = [
            ReadingQueueEntry(**{**entry.as_dict(), "rank": rank})
            for rank, entry in enumerate(ranked[:limit], start=1)
        ]
        artifact = {
            "schema_version": READING_QUEUE_SCHEMA_VERSION,
            "policy_version": READING_QUEUE_POLICY_VERSION,
            "generated_at": now_iso(),
            "input_sha256": input_sha256,
            "query": clean_query,
            "skill": {"name": skill.name, "version": skill.version},
            "total_papers": len(ranked),
            "queue_limit": limit,
            "action_counts": _action_counts(ranked),
            "entries": [entry.as_dict() for entry in entries],
        }
        if write_artifact:
            self.queues_dir.mkdir(parents=True, exist_ok=True)
            _write_json(artifact_path, artifact)
        return _report_from_artifact(
            root=self.root,
            artifact_path=artifact_path if write_artifact else None,
            artifact=artifact,
            cached=False,
        )


def format_reading_queue(report: ReadingQueueReport) -> str:
    lines = [
        f"Research folder: {report.root}",
        (
            "Reading queue: "
            f"{len(report.entries)} shown of {report.total_papers} papers, "
            f"cached={'yes' if report.cached else 'no'}"
        ),
        f"Skill: {report.skill['name']}@{report.skill['version']}",
        f"Query: {report.query or 'none'}",
        f"Actions: {_format_counts(report.action_counts)}",
    ]
    if report.artifact_path:
        lines.append(f"Artifact: {report.artifact_path}")
    else:
        lines.append("Read-only: no reading-queue artifact was written.")
    lines.append("API usage: none")
    for entry in report.entries:
        lines.append(
            f"{entry.rank}. {entry.paper_id}: score={entry.priority_score}, "
            f"action={entry.action}, summary={entry.summary_quality}"
        )
        for reason in entry.reasons:
            lines.append(f"   - {reason}")
        for command in entry.next_commands:
            lines.append(f"   $ {command}")
    return "\n".join(lines)


def _build_context(
    root: Path,
    record: dict[str, Any],
    *,
    query: str | None,
) -> dict[str, Any]:
    title = str(record.get("title", ""))
    context: dict[str, Any] = {
        "record": record,
        "title_tokens": set(_meaningful_tokens(title)),
        "query_score": _score_text(title, query) * 5 if query else 0,
        "query_evidence": [],
        "workload_chunks": 0,
        "workload_chars": 0,
        "errors": [],
    }
    artifact_value = dict(record.get("artifacts", {})).get("chunks")
    if (
        dict(record.get("processing", {})).get("chunking") != "chunked"
        or not artifact_value
    ):
        return context
    try:
        artifact = _load_json(root / str(artifact_value))
        chunks = artifact.get("chunks", [])
        if not isinstance(chunks, list):
            raise ValueError(f"{artifact_value} must contain a chunks list.")
        evidence: list[dict[str, Any]] = []
        for chunk in chunks:
            if not isinstance(chunk, dict):
                continue
            text = str(chunk.get("text", ""))
            context["workload_chunks"] += 1
            context["workload_chars"] += len(text)
            if not query:
                continue
            score = _score_text(text, query)
            if not score:
                continue
            page_start = int(chunk.get("page_start", 0))
            page_end = int(chunk.get("page_end", page_start))
            chunk_id = str(chunk.get("id", ""))
            evidence.append(
                {
                    "citation": _citation(
                        str(record.get("paper_id", "")),
                        page_start,
                        page_end,
                        chunk_id,
                    ),
                    "score": score,
                    "snippet": _snippet(text, query),
                }
            )
        evidence.sort(key=lambda item: (-item["score"], item["citation"]))
        context["query_evidence"] = evidence[:MAX_QUERY_EVIDENCE]
        context["query_score"] += sum(item["score"] for item in evidence[:MAX_QUERY_EVIDENCE])
    except Exception as exc:  # noqa: BLE001 - isolate one malformed chunk artifact.
        context["errors"].append(str(exc))
    return context


def _build_entry(
    harness: ResearchFolderHarness,
    context: dict[str, Any],
    *,
    query: str | None,
    skill: ResearchSkillManifest,
    title_document_frequency: Counter[str],
) -> ReadingQueueEntry:
    record = context["record"]
    processing = dict(record.get("processing", {}))
    quality = str(dict(record.get("memory_quality", {})).get("status", "missing_summary"))
    shared_terms = sorted(
        token
        for token in context["title_tokens"]
        if title_document_frequency[token] > 1
    )
    centrality_score = sum(
        min(title_document_frequency[token] - 1, 4) * 3 for token in shared_terms
    )
    action, readiness, base_score, reasons = _classify_action(
        record,
        processing=processing,
        quality=quality,
        context_errors=context["errors"],
    )
    query_score = int(context["query_score"])
    priority_score = base_score + centrality_score + query_score
    if quality in {"missing_summary", "failed", "raw_captured"}:
        priority_score += 20
    if query:
        reasons.append(
            f"Query relevance score={query_score} from "
            f"{len(context['query_evidence'])} traceable chunk hits."
        )
    if shared_terms:
        reasons.append(
            f"Corpus centrality score={centrality_score} from shared title terms: "
            f"{', '.join(shared_terms)}."
        )
    if context["workload_chunks"]:
        reasons.append(
            f"Estimated supervised summary workload: {context['workload_chunks']} chunks, "
            f"{context['workload_chars']} characters."
        )
    commands = _next_commands(
        harness,
        action=action,
        paper_id=str(record.get("paper_id", "")),
        skill=skill,
    )
    return ReadingQueueEntry(
        rank=0,
        paper_id=str(record.get("paper_id", "")),
        title=str(record.get("title", "")),
        source_file=str(record.get("source_file", "")),
        priority_score=priority_score,
        action=action,
        readiness=readiness,
        summary_quality=quality,
        query_score=query_score,
        centrality_score=centrality_score,
        workload_chunks=int(context["workload_chunks"]),
        workload_chars=int(context["workload_chars"]),
        reasons=reasons,
        query_evidence=list(context["query_evidence"]),
        next_commands=commands,
    )


def _classify_action(
    record: dict[str, Any],
    *,
    processing: dict[str, Any],
    quality: str,
    context_errors: list[str],
) -> tuple[str, str, int, list[str]]:
    if record.get("status") == "missing":
        return "restore_source", "blocked", 0, ["Source file is missing."]
    if record.get("file_type") != "pdf":
        return "review_manually", "blocked", 5, ["File type is not supported by the PDF pipeline."]
    if processing.get("extraction") == "needs_ocr":
        return "run_ocr", "blocked", 15, ["PDF needs explicit OCR preprocessing before reading."]
    if context_errors:
        return "repair_pipeline", "blocked", 5, [
            f"Chunk artifact must be repaired: {'; '.join(context_errors)}"
        ]
    if processing.get("extraction") == "failed" or processing.get("chunking") == "failed":
        return "repair_pipeline", "blocked", 5, ["Local preparation failed and should be retried."]
    if processing.get("chunking") != "chunked":
        return "run_prepare", "blocked", 10, ["Traceable chunks are not ready yet."]
    if quality == "raw_captured":
        return "normalize_summary", "ready", 70, [
            "Raw model reading is preserved and should be normalized into audited memory."
        ]
    if quality in {"missing_summary", "failed"}:
        return "summarize", "ready", 60, ["Traceable chunks are ready, but audited summary memory is missing."]
    if quality == "warning":
        return "review_summary", "ready", 45, ["Existing summary has review warnings."]
    return "read_or_compare", "ready", 30, ["Audited summary memory is available."]


def _next_commands(
    harness: ResearchFolderHarness,
    *,
    action: str,
    paper_id: str,
    skill: ResearchSkillManifest,
) -> list[str]:
    root = _quote(str(harness.root))
    papers_dir = _quote(_display_papers_dir(harness))
    base = f"{root} --papers-dir {papers_dir} --paper {paper_id}"
    if action == "summarize":
        summary = f"odracir summarize {base} --skill {skill.name}"
        return [f"{summary} --dry-run", summary]
    if action == "normalize_summary":
        return [f"odracir normalize-summaries {base} --skill {skill.name}"]
    if action == "review_summary":
        return [f"odracir evaluate-summaries {base} --skill {skill.name}"]
    if action == "run_ocr":
        return [
            f"odracir ocr {base}",
            f"odracir prepare {base}",
        ]
    if action == "run_prepare":
        return [f"odracir prepare {base}"]
    if action == "repair_pipeline":
        return [f"odracir prepare {base} --force"]
    return []


def _display_papers_dir(harness: ResearchFolderHarness) -> str:
    try:
        return harness.papers_dir.relative_to(harness.root).as_posix()
    except ValueError:
        return str(harness.papers_dir)


def _quote(value: str) -> str:
    return f'"{value}"'


def _input_sha256(
    root: Path,
    *,
    catalog_input_sha256: str,
    records: list[dict[str, Any]],
    query: str | None,
    skill: ResearchSkillManifest,
    limit: int,
) -> str:
    payload = {
        "schema_version": READING_QUEUE_SCHEMA_VERSION,
        "policy_version": READING_QUEUE_POLICY_VERSION,
        "catalog_input_sha256": catalog_input_sha256,
        "query": query,
        "skill": {"name": skill.name, "version": skill.version},
        "limit": limit,
        "chunk_artifacts": [
            {
                "paper_id": record.get("paper_id"),
                "chunk_artifact": dict(record.get("artifacts", {})).get("chunks"),
                "chunk_artifact_sha256": _optional_file_sha256(
                    root / str(dict(record.get("artifacts", {})).get("chunks") or "")
                ),
            }
            for record in records
        ],
    }
    return _sha256_json(payload)


def _action_counts(entries: list[ReadingQueueEntry]) -> dict[str, int]:
    return dict(sorted(Counter(entry.action for entry in entries).items()))


def _format_counts(counts: dict[str, int]) -> str:
    return ", ".join(f"{key}={value}" for key, value in sorted(counts.items())) or "none"


def _score_text(text: str, query: str | None) -> int:
    if not query:
        return 0
    lowered = text.lower()
    score = 0
    for token in _tokenize(query):
        count = lowered.count(token)
        if count:
            score += 2 + min(count, 8)
    if query.lower() in lowered:
        score += 8
    return score


def _meaningful_tokens(text: str) -> list[str]:
    return [
        token
        for token in _tokenize(text)
        if token not in STOPWORDS and (len(token) > 2 or _is_chinese(token))
    ]


def _tokenize(text: str) -> list[str]:
    return list(
        dict.fromkeys(re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]", text.lower()))
    )


def _is_chinese(token: str) -> bool:
    return bool(re.fullmatch(r"[\u4e00-\u9fff]", token))


def _snippet(text: str, query: str) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    lowered = compact.lower()
    positions = [lowered.find(query.lower())]
    positions.extend(lowered.find(token) for token in _tokenize(query))
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


def _can_use_cached(artifact: dict[str, Any], *, input_sha256: str) -> bool:
    return (
        artifact.get("schema_version") == READING_QUEUE_SCHEMA_VERSION
        and artifact.get("policy_version") == READING_QUEUE_POLICY_VERSION
        and artifact.get("input_sha256") == input_sha256
        and isinstance(artifact.get("entries"), list)
        and isinstance(artifact.get("action_counts"), dict)
    )


def _report_from_artifact(
    *,
    root: Path,
    artifact_path: Path | None,
    artifact: dict[str, Any],
    cached: bool,
) -> ReadingQueueReport:
    return ReadingQueueReport(
        root=str(root),
        artifact_path=artifact_path.relative_to(root).as_posix() if artifact_path else None,
        cached=cached,
        policy_version=str(artifact["policy_version"]),
        generated_at=str(artifact["generated_at"]),
        input_sha256=str(artifact["input_sha256"]),
        query=str(artifact["query"]) if artifact.get("query") else None,
        skill=dict(artifact["skill"]),
        total_papers=int(artifact["total_papers"]),
        queue_limit=int(artifact["queue_limit"]),
        action_counts={
            str(key): int(value)
            for key, value in dict(artifact["action_counts"]).items()
        },
        entries=[ReadingQueueEntry(**entry) for entry in artifact["entries"]],
    )


def _optional_file_sha256(path: Path) -> str | None:
    return _sha256_file(path) if path.is_file() else None


def _sha256_json(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object.")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
        file.write("\n")
