import json
import hashlib

import pytest

from odracir.providers import JsonCompletionResult
from odracir.research_folder import ResearchFolderHarness
from odracir.research_memory import ResearchCatalogBuilder
from odracir.synthesis import ResearchSynthesizer, validate_synthesis
from odracir.time_utils import now_iso


class SynthesisStubProvider:
    provider_name = "stub"
    model = "synthesis-model"

    def __init__(self) -> None:
        self.calls = []

    def complete_json(self, *, system_prompt: str, user_prompt: str, max_tokens: int):
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "max_tokens": max_tokens,
            }
        )
        return JsonCompletionResult(
            payload={
                "overview": "Two papers describe related optimization methods.",
                "topic_groups": [
                    {
                        "name": "Optimization methods",
                        "description": "Papers about optimization algorithms.",
                        "paper_ids": ["paper-a", "paper-b"],
                        "key_takeaways": ["Both focus on optimization."],
                    }
                ],
                "method_comparison": [
                    {
                        "method": "Method A",
                        "paper_ids": ["paper-a"],
                        "problem_addressed": "Gradient conflict.",
                        "core_idea": "Project gradients.",
                        "strengths": ["Simple update rule."],
                        "limitations": ["Fixture-only evidence."],
                    }
                ],
                "evidence_matrix": [
                    {
                        "claim": "Optimization methods require careful trade-offs.",
                        "supporting_papers": ["paper-a", "paper-b"],
                        "contradicting_papers": [],
                        "evidence_strength": "moderate",
                        "notes": "Supported by fixture summaries.",
                    }
                ],
                "claim_evidence_matrix": [
                    {
                        "claim": "Optimization methods require careful trade-offs.",
                        "supporting_evidence": [
                            {
                                "paper_id": "paper-a",
                                "evidence_type": "experiment",
                                "summary_finding": "Paper A supports optimization.",
                                "original_citations": ["[paper-a pp.1 chunk:one]"],
                            }
                        ],
                        "contradicting_evidence": [],
                        "evidence_strength": "moderate",
                        "uncertainty": "Fixture evidence is intentionally small.",
                    }
                ],
                "method_family_tree": [
                    {
                        "family": "Gradient methods",
                        "description": "Methods that modify optimization updates.",
                        "methods": [
                            {
                                "name": "Method A",
                                "paper_ids": ["paper-a"],
                                "role": "Baseline family member.",
                                "related_methods": ["Method B"],
                            }
                        ],
                    }
                ],
                "benchmark_matrix": [
                    {
                        "paper_id": "paper-a",
                        "benchmarks_or_datasets": ["Fixture benchmark"],
                        "metrics": ["Fixture score"],
                        "baselines": ["Baseline"],
                        "reported_result": "Improves fixture score.",
                        "comparability_notes": "Synthetic fixture only.",
                    }
                ],
                "reading_reproduction_priority": [
                    {
                        "paper_id": "paper-a",
                        "reading_priority": "high",
                        "reproduction_priority": "medium",
                        "reason": "Representative method.",
                        "suggested_action": "Inspect pseudocode.",
                    }
                ],
                "conflicts_or_tensions": [],
                "research_gaps": ["Need larger evaluation."],
                "recommended_next_steps": ["Review benchmark compatibility."],
            },
            usage={"total_tokens": 42},
        )


def _write_catalog_fixture(root) -> None:
    root.mkdir(parents=True, exist_ok=True)
    index = {
        "schema_version": "0.2",
        "folder_name": root.name,
        "generated_by": "odracir",
        "updated_at": now_iso(),
        "papers": [
            _paper_record("paper-a", "Paper A"),
            _paper_record("paper-b", "Paper B"),
        ],
    }
    (root / "odracir_index.json").write_text(
        json.dumps(index, ensure_ascii=False),
        encoding="utf-8",
    )
    summaries = root / ".odracir" / "summaries"
    chunks = root / ".odracir" / "chunks"
    summaries.mkdir(parents=True)
    chunks.mkdir(parents=True)
    for paper_id, title in (("paper-a", "Paper A"), ("paper-b", "Paper B")):
        chunk_path = chunks / f"{paper_id}.json"
        chunk_path.write_text(
            json.dumps(
                {
                    "chunks": [
                        {
                            "id": "one",
                            "page_start": 1,
                            "page_end": 1,
                            "text": f"{title} supports optimization.",
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        chunk_sha256 = _file_sha256(chunk_path)
        (summaries / f"{paper_id}.json").write_text(
            json.dumps(
                {
                    "schema_version": "0.3",
                    "paper_id": paper_id,
                    "source_file": f"{title}.pdf",
                    "source_sha256": _hash_for(paper_id),
                    "chunk_artifact": f".odracir/chunks/{paper_id}.json",
                    "chunk_artifact_sha256": chunk_sha256,
                    "provider": "stub",
                    "model": "summary-model",
                    "prompt_version": "0.3",
                    "skill": {"name": "generic", "version": "0.1"},
                    "summarized_at": now_iso(),
                    "usage": {},
                    "summary_strategy": "single_pass",
                    "request_count": 1,
                    "input_char_count": 100,
                    "fallback_reason": None,
                    "map_summaries": [],
                    "summary": {
                        "summary_short": f"{title} short summary.",
                        "summary_detailed": f"{title} detailed summary.",
                        "research_question": f"What does {title} solve?",
                        "methods": [f"{title} method"],
                        "findings": [
                            {
                                "claim": f"{title} supports optimization.",
                                "citations": [f"[{paper_id} pp.1 chunk:one]"],
                                "inference": False,
                            }
                        ],
                        "limitations": ["Small fixture."],
                        "key_terms": ["optimization"],
                        "implementation_notes": ["Check pseudocode."],
                        "inferences": [],
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    ResearchCatalogBuilder(root).build()


def _paper_record(paper_id: str, title: str) -> dict:
    return {
        "id": paper_id,
        "title": title,
        "authors": [],
        "year": None,
        "source_file": f"papers/{title}.pdf",
        "file_name": f"{title}.pdf",
        "file_type": "pdf",
        "file_size_bytes": 10,
        "sha256": _hash_for(paper_id),
        "status": "indexed",
        "ocr_status": "not_started",
        "text_extraction_status": "extracted",
        "chunking_status": "chunked",
        "summary_status": "summarized",
        "translation_status": "not_started",
        "chunk_artifact": f".odracir/chunks/{paper_id}.json",
        "summary_artifact": f".odracir/summaries/{paper_id}.json",
        "summary_input_sha256": f"{paper_id}-chunks",
        "summary_provider": "stub",
        "summary_model": "summary-model",
        "summary_prompt_version": "0.3",
        "summary_skill": "generic",
        "summary_skill_version": "0.1",
    }


def _hash_for(value: str) -> str:
    return (value.replace("-", "") * 64)[:64]


def _file_sha256(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_synthesis_writes_artifact_markdown_and_uses_cache(tmp_path) -> None:
    root = tmp_path / "field"
    _write_catalog_fixture(root)
    provider = SynthesisStubProvider()
    synthesizer = ResearchSynthesizer(root, provider)

    first = synthesizer.synthesize()
    second = synthesizer.synthesize()

    assert first.cached is False
    assert second.cached is True
    assert len(provider.calls) == 1
    assert first.paper_count == 2
    assert first.usage == {"total_tokens": 42}
    assert (root / first.artifact_path).is_file()
    markdown = (root / "research_synthesis.md").read_text(encoding="utf-8")
    assert "Two papers describe related optimization methods." in markdown
    assert "Optimization methods" in markdown
    assert "Claim-Level Evidence Matrix" in markdown
    assert "Method Family Tree" in markdown
    assert "Benchmark Matrix" in markdown
    assert "Reading And Reproduction Priority" in markdown


def test_synthesis_rejects_unknown_paper_id() -> None:
    with pytest.raises(ValueError, match="unknown paper ids"):
        validate_synthesis(
            {
                "overview": "Bad paper id.",
                "topic_groups": [
                    {
                        "name": "Bad",
                        "description": "",
                        "paper_ids": ["missing"],
                        "key_takeaways": [],
                    }
                ],
                "method_comparison": [],
                "evidence_matrix": [],
                "claim_evidence_matrix": [],
                "method_family_tree": [],
                "benchmark_matrix": [],
                "reading_reproduction_priority": [],
                "conflicts_or_tensions": [],
                "research_gaps": [],
                "recommended_next_steps": [],
            },
            {"paper-a"},
        )


def test_synthesis_requires_audited_summaries(tmp_path) -> None:
    root = tmp_path / "field"
    ResearchFolderHarness(root).sync_index()

    with pytest.raises(ValueError, match="at least one audited paper summary"):
        ResearchSynthesizer(root, SynthesisStubProvider()).synthesize()


def test_synthesis_rejects_output_path_outside_research_folder(tmp_path) -> None:
    root = tmp_path / "field"

    with pytest.raises(ValueError, match="inside the research folder"):
        ResearchSynthesizer(
            root,
            SynthesisStubProvider(),
            output_name="../outside.md",
        )


def test_synthesis_rejects_markdown_output_inside_state_directory(tmp_path) -> None:
    root = tmp_path / "field"

    with pytest.raises(ValueError, match=".odracir state directory"):
        ResearchSynthesizer(
            root,
            SynthesisStubProvider(),
            output_name=".odracir/synthesis.md",
        )


def test_synthesis_rejects_malformed_string_lists() -> None:
    with pytest.raises(ValueError, match="recommended_next_steps items must be strings"):
        validate_synthesis(
            {
                "overview": "Bad list item.",
                "topic_groups": [],
                "method_comparison": [],
                "evidence_matrix": [],
                "claim_evidence_matrix": [],
                "method_family_tree": [],
                "benchmark_matrix": [],
                "reading_reproduction_priority": [],
                "conflicts_or_tensions": [],
                "research_gaps": [],
                "recommended_next_steps": [{"not": "a string"}],
            },
            {"paper-a"},
        )
