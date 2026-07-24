"""Deterministic preparation of PDF inputs for the paper-study pipeline."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from odracir.paper_study.planning import ChunkArtifact, SourceChunk, load_chunk_artifact


_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9._-]+")


def ensure_pdf_chunk_artifacts(paper_folder: str | Path) -> tuple[Path, ...]:
    """Create reusable page-level chunk artifacts for PDFs lacking legacy chunks."""

    folder = Path(paper_folder).expanduser().resolve()
    if not folder.is_dir():
        raise ValueError(f"paper_folder is not a directory: {folder}")
    chunks_root = folder / ".odracir" / "chunks"
    existing = tuple(sorted(chunks_root.glob("*.json"))) if chunks_root.is_dir() else ()
    pdfs = tuple(
        sorted(
            path
            for path in folder.rglob("*.pdf")
            if ".odracir" not in path.relative_to(folder).parts
        )
    )
    if not pdfs:
        return existing

    paper_ids = _paper_ids(pdfs, folder)
    outputs: list[Path] = []
    for pdf_path, paper_id in zip(pdfs, paper_ids, strict=True):
        target = chunks_root / f"{paper_id}.json"
        source_sha256 = _sha256_file(pdf_path)
        if target.is_file():
            current = load_chunk_artifact(target)
            if current.paper_id == paper_id and current.source_sha256 == source_sha256:
                outputs.append(target)
                continue
        outputs.append(
            _ingest_pdf(
                pdf_path,
                paper_id=paper_id,
                paper_folder=folder,
                source_sha256=source_sha256,
                target=target,
            )
        )
    return tuple(outputs)


def _ingest_pdf(
    pdf_path: Path,
    *,
    paper_id: str,
    paper_folder: Path,
    source_sha256: str,
    target: Path,
) -> Path:
    extracted_source_sha256, pages, chunks = extract_pdf_page_chunks(pdf_path)
    if extracted_source_sha256 != source_sha256:
        raise ValueError(f"PDF changed while it was being ingested: {pdf_path}")

    text_path = paper_folder / ".odracir" / "texts" / f"{paper_id}.json"
    text_payload = {
        "schema_version": "1.0",
        "paper_id": paper_id,
        "source_file": str(pdf_path.relative_to(paper_folder)),
        "source_sha256": source_sha256,
        "pages": list(pages),
    }
    _write_json(text_payload, text_path)
    text_sha256 = _sha256_file(text_path)
    artifact = ChunkArtifact(
        schema_version="0.1",
        paper_id=paper_id,
        source_file=str(pdf_path.relative_to(paper_folder)),
        source_sha256=source_sha256,
        text_artifact=str(text_path.relative_to(paper_folder)),
        text_artifact_sha256=text_sha256,
        chunker="odracir.pdf-page",
        chunker_version="1.0",
        chunked_at=datetime.now(timezone.utc).isoformat(),
        chunk_count=len(chunks),
        chunks=list(chunks),
    )
    _write_json(artifact.model_dump(mode="json", by_alias=True), target)
    return target


def extract_pdf_page_chunks(
    pdf_path: str | Path,
) -> tuple[str, tuple[dict[str, object], ...], tuple[SourceChunk, ...]]:
    """Read a PDF into deterministic page chunks without writing artifacts.

    The returned chunk identifiers use the same frozen namespace as
    :func:`ensure_pdf_chunk_artifacts`.  Exporters can therefore materialize
    additional evidence packages without invoking a model or mutating the
    source corpus.
    """

    source = Path(pdf_path).expanduser().resolve()
    if not source.is_file():
        raise ValueError(f"PDF does not exist: {source}")
    try:
        import fitz
    except ImportError as exc:  # pragma: no cover - packaging/environment guard
        raise RuntimeError(
            "PyMuPDF is required to prepare bare PDFs; install the project dependencies"
        ) from exc

    source_sha256 = _sha256_file(source)
    pages: list[dict[str, object]] = []
    chunks: list[SourceChunk] = []
    with fitz.open(source) as document:
        for page_index, page in enumerate(document, start=1):
            text = page.get_text("text").strip()
            if not text:
                continue
            content_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
            chunk_id = hashlib.sha256(
                f"{source_sha256}:{page_index}:{content_sha256}".encode("utf-8")
            ).hexdigest()[:20]
            pages.append({"page": page_index, "text": text})
            chunks.append(
                SourceChunk.model_validate(
                    {
                        "id": chunk_id,
                        "ordinal": len(chunks) + 1,
                        "section_hint": _section_hint(text),
                        "page_start": page_index,
                        "page_end": page_index,
                        "char_count": len(text),
                        "token_estimate": max(1, (len(text) + 3) // 4),
                        "content_sha256": content_sha256,
                        "text": text,
                    }
                )
            )
    if not chunks:
        raise ValueError(
            f"PDF contains no extractable text and requires OCR before ingestion: {source}"
        )
    return source_sha256, tuple(pages), tuple(chunks)


def _paper_ids(pdfs: tuple[Path, ...], root: Path) -> tuple[str, ...]:
    bases = [_safe_paper_id(path.stem) for path in pdfs]
    counts = {base: bases.count(base) for base in set(bases)}
    resolved = []
    for path, base in zip(pdfs, bases, strict=True):
        if counts[base] == 1:
            resolved.append(base)
            continue
        relative_digest = hashlib.sha256(
            str(path.relative_to(root)).encode("utf-8")
        ).hexdigest()[:8]
        resolved.append(f"{base}-{relative_digest}")
    if len(resolved) != len(set(resolved)):
        raise ValueError("PDF paths could not be mapped to unique paper IDs")
    return tuple(resolved)


def _safe_paper_id(value: str) -> str:
    normalized = _SAFE_ID_RE.sub("-", value.strip()).strip("-._")
    return normalized or "paper"


def _section_hint(text: str) -> str:
    prefix = " ".join(text[:500].casefold().split())
    for section in ("abstract", "methods", "results", "discussion", "references"):
        if section in prefix:
            return section
    return "page"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(payload: object, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
