import json

from odracir.providers import JsonCompletionResult
from odracir.research_folder import ResearchFolderHarness
from odracir.skills import get_builtin_skill_registry
from odracir.summarization import EvidenceSummaryGenerator, build_summary_plan


class StubProvider:
    provider_name = "stub"
    model = "stub-model"

    def __init__(
        self,
        *,
        cite_findings: bool = True,
        finding_citation: str = "[paper pp.1 chunk:one]",
        include_domain_extension: bool = True,
    ) -> None:
        self.calls = []
        self.cite_findings = cite_findings
        self.finding_citation = finding_citation
        self.include_domain_extension = include_domain_extension

    def complete_json(self, *, system_prompt: str, user_prompt: str, max_tokens: int):
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "max_tokens": max_tokens,
            }
        )
        if "one traceable chunk" in system_prompt:
            citation = user_prompt.split("Citation: ", 1)[1].splitlines()[0]
            return JsonCompletionResult(
                payload={
                    "chunk_summary": "Local evidence.",
                    "key_points": [{"claim": "Evidence.", "citation": citation}],
                    "methods": [],
                    "limitations": [],
                    "key_terms": ["world model"],
                },
                usage={"total_tokens": 10},
            )

        finding = {"claim": "The method uses a world model.", "inference": False}
        if self.cite_findings:
            finding["citations"] = [self.finding_citation]
        payload = {
                "summary_short": "Short evidence-aware summary.",
                "summary_detailed": "Detailed evidence-aware summary.",
                "research_question": "Can a world model help?",
                "methods": ["Method"],
                "findings": [finding],
                "limitations": [],
                "key_terms": ["world model"],
                "implementation_notes": [],
                "inferences": [],
            }
        if "domain_extensions" in system_prompt and self.include_domain_extension:
            payload["domain_extensions"] = {
                "biomedical": {
                    "population": [
                        {
                            "value": "Patients with longitudinal records.",
                            "citations": [self.finding_citation],
                            "inference": False,
                        }
                    ],
                    "intervention_or_exposure": [],
                    "comparator": [],
                    "outcomes": [],
                    "biological_mechanisms": [],
                    "assays_or_measurements": [],
                    "clinical_relevance": [],
                    "safety_or_ethics": [],
                }
            }
        return JsonCompletionResult(
            payload=payload,
            usage={"total_tokens": 20},
        )


def _write_summary_fixture(root) -> None:
    papers = root / "papers"
    papers.mkdir(parents=True)
    (papers / "paper.pdf").write_bytes(b"%PDF-1.4\n")
    harness = ResearchFolderHarness(root)
    harness.sync_index()
    index = harness.load_index()
    paper = index["papers"][0]
    paper["chunking_status"] = "chunked"
    paper["chunk_artifact"] = ".odracir/chunks/paper.json"
    harness.write_index(index)

    chunks_dir = root / ".odracir" / "chunks"
    chunks_dir.mkdir(parents=True)
    (chunks_dir / "paper.json").write_text(
        json.dumps(
            {
                "chunks": [
                    {
                        "id": "one",
                        "page_start": 1,
                        "page_end": 1,
                        "text": "A world model supports evidence-aware planning.",
                    },
                    {
                        "id": "two",
                        "page_start": 2,
                        "page_end": 3,
                        "text": "The method includes longitudinal state prediction.",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )


def test_summarization_writes_artifact_and_skips_unchanged_chunks(tmp_path) -> None:
    root = tmp_path / "field"
    _write_summary_fixture(root)
    provider = StubProvider()
    generator = EvidenceSummaryGenerator(root, provider)

    first = generator.summarize_index()
    index = generator.harness.load_index()
    paper = index["papers"][0]
    artifact = json.loads((root / paper["summary_artifact"]).read_text(encoding="utf-8"))
    second = generator.summarize_index()

    assert first.summarized == 1
    assert second.skipped == 1
    assert len(provider.calls) == 3
    assert paper["summary_status"] == "summarized"
    assert paper["summary_short"] == "Short evidence-aware summary."
    assert artifact["provider"] == "stub"
    assert artifact["usage"]["total_tokens"] == 40
    assert len(artifact["map_summaries"]) == 2


def test_summarization_rejects_uncited_non_inference_finding(tmp_path) -> None:
    root = tmp_path / "field"
    _write_summary_fixture(root)
    provider = StubProvider(cite_findings=False)

    result = EvidenceSummaryGenerator(root, provider).summarize_index()
    paper = ResearchFolderHarness(root).load_index()["papers"][0]

    assert result.failed == 1
    assert paper["summary_status"] == "failed"
    assert "citations or inference=true" in paper["summary_error"]


def test_summarization_blocks_unchunked_paper(tmp_path) -> None:
    root = tmp_path / "field"
    papers = root / "papers"
    papers.mkdir(parents=True)
    (papers / "paper.pdf").write_bytes(b"%PDF-1.4\n")

    result = EvidenceSummaryGenerator(root, StubProvider()).summarize_index()
    paper = ResearchFolderHarness(root).load_index()["papers"][0]

    assert result.blocked == 1
    assert paper["summary_status"] == "blocked"


def test_summarization_rejects_citation_outside_source_chunks(tmp_path) -> None:
    root = tmp_path / "field"
    _write_summary_fixture(root)
    provider = StubProvider(finding_citation="[paper pp.99 chunk:imaginary]")

    result = EvidenceSummaryGenerator(root, provider).summarize_index()
    paper = ResearchFolderHarness(root).load_index()["papers"][0]

    assert result.failed == 1
    assert paper["summary_status"] == "failed"
    assert "outside source chunks" in paper["summary_error"]


def test_failed_forced_summary_removes_stale_summary_but_preserves_translation(tmp_path) -> None:
    root = tmp_path / "field"
    _write_summary_fixture(root)
    generator = EvidenceSummaryGenerator(root, StubProvider())
    generator.summarize_index()
    index = generator.harness.load_index()
    paper = index["papers"][0]
    paper["translation_status"] = "translated"
    paper["translation_artifact"] = ".odracir/translations/paper.zh-CN.json"
    generator.harness.write_index(index)

    result = EvidenceSummaryGenerator(
        root,
        StubProvider(cite_findings=False),
    ).summarize_index(force=True)
    paper = ResearchFolderHarness(root).load_index()["papers"][0]

    assert result.failed == 1
    assert paper["summary_status"] == "failed"
    assert "summary_artifact" not in paper
    assert paper["summary_short"] == ""
    assert paper["translation_status"] == "translated"
    assert paper["translation_artifact"] == ".odracir/translations/paper.zh-CN.json"


def test_biomedical_skill_records_versioned_domain_extension(tmp_path) -> None:
    root = tmp_path / "field"
    _write_summary_fixture(root)
    skill = get_builtin_skill_registry().get("biomedical-paper")

    result = EvidenceSummaryGenerator(root, StubProvider(), skill=skill).summarize_index()
    index = ResearchFolderHarness(root).load_index()
    paper = index["papers"][0]
    artifact = json.loads((root / paper["summary_artifact"]).read_text(encoding="utf-8"))

    assert result.summarized == 1
    assert paper["summary_skill"] == "biomedical-paper"
    assert paper["summary_skill_version"] == "0.1"
    assert artifact["skill"]["name"] == "biomedical-paper"
    assert artifact["summary"]["domain_extensions"]["biomedical"]["population"][0][
        "citations"
    ] == ["[paper pp.1 chunk:one]"]


def test_switching_summary_skill_invalidates_cache(tmp_path) -> None:
    root = tmp_path / "field"
    _write_summary_fixture(root)
    generic_provider = StubProvider()
    EvidenceSummaryGenerator(root, generic_provider).summarize_index()
    biomedical_provider = StubProvider()
    biomedical = get_builtin_skill_registry().get("biomedical-paper")

    result = EvidenceSummaryGenerator(
        root,
        biomedical_provider,
        skill=biomedical,
    ).summarize_index()

    assert result.summarized == 1
    assert result.skipped == 0
    assert len(biomedical_provider.calls) == 3


def test_summary_dry_run_reports_scope_without_provider(tmp_path) -> None:
    root = tmp_path / "field"
    _write_summary_fixture(root)
    skill = get_builtin_skill_registry().get("biomedical-paper")

    plan = build_summary_plan(root, skill=skill)

    assert plan.skill["name"] == "biomedical-paper"
    assert plan.ready == 1
    assert plan.total_chunks == 2


def test_biomedical_skill_rejects_missing_domain_extension(tmp_path) -> None:
    root = tmp_path / "field"
    _write_summary_fixture(root)
    skill = get_builtin_skill_registry().get("biomedical-paper")

    result = EvidenceSummaryGenerator(
        root,
        StubProvider(include_domain_extension=False),
        skill=skill,
    ).summarize_index()
    paper = ResearchFolderHarness(root).load_index()["papers"][0]

    assert result.failed == 1
    assert "must include domain_extensions" in paper["summary_error"]
