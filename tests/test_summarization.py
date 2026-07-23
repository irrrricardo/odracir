import json

import odracir.summarization as summarization
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
    assert len(provider.calls) == 1
    assert paper["summary_status"] == "summarized"
    assert paper["summary_short"] == "Short evidence-aware summary."
    assert paper["summary_strategy"] == "single_pass"
    assert paper["summary_request_count"] == 1
    assert artifact["provider"] == "stub"
    assert artifact["usage"]["total_tokens"] == 20
    assert artifact["summary_strategy"] == "single_pass"
    assert artifact["request_count"] == 1
    assert artifact["map_summaries"] == []


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
    assert len(biomedical_provider.calls) == 1


def test_summary_uses_map_reduce_fallback_above_single_pass_limit(
    tmp_path,
    monkeypatch,
) -> None:
    root = tmp_path / "field"
    _write_summary_fixture(root)
    monkeypatch.setattr(summarization, "SINGLE_PASS_MAX_CHARS", 1)
    provider = StubProvider()

    result = EvidenceSummaryGenerator(root, provider).summarize_index()
    paper = ResearchFolderHarness(root).load_index()["papers"][0]
    artifact = json.loads((root / paper["summary_artifact"]).read_text(encoding="utf-8"))

    assert result.summarized == 1
    assert result.strategy_counts == {"map_reduce_fallback": 1}
    assert len(provider.calls) == 3
    assert artifact["summary_strategy"] == "map_reduce_fallback"
    assert artifact["request_count"] == 3
    assert "above the 1 single-pass safety limit" in artifact["fallback_reason"]
    assert len(artifact["map_summaries"]) == 2


class ConnectionFailureProvider:
    provider_name = "stub"
    model = "connection-failure"

    def __init__(self) -> None:
        self.calls = 0

    def complete_json(self, *, system_prompt: str, user_prompt: str, max_tokens: int):
        self.calls += 1
        raise ConnectionError("network unavailable")


class MatchingConnectionFailureProvider(ConnectionFailureProvider):
    model = "stub-model"


def test_summary_does_not_fan_out_transport_failure_into_map_reduce(tmp_path) -> None:
    root = tmp_path / "field"
    _write_summary_fixture(root)
    provider = MatchingConnectionFailureProvider()

    result = EvidenceSummaryGenerator(root, provider).summarize_index()
    paper = ResearchFolderHarness(root).load_index()["papers"][0]

    assert result.failed == 1
    assert provider.calls == 1
    assert paper["summary_status"] == "failed"
    assert "network unavailable" in paper["summary_error"]


def test_summary_adopts_valid_artifact_from_interrupted_run(tmp_path) -> None:
    root = tmp_path / "field"
    _write_summary_fixture(root)
    EvidenceSummaryGenerator(root, StubProvider()).summarize_index()
    harness = ResearchFolderHarness(root)
    index = harness.load_index()
    paper = index["papers"][0]
    paper["summary_status"] = "not_started"
    paper.pop("summary_provider", None)
    paper.pop("summary_model", None)
    harness.write_index(index)
    provider = MatchingConnectionFailureProvider()

    result = EvidenceSummaryGenerator(root, provider).summarize_index()
    paper = harness.load_index()["papers"][0]

    assert result.skipped == 1
    assert result.failed == 0
    assert provider.calls == 0
    assert paper["summary_status"] == "summarized"
    assert paper["summary_short"] == "Short evidence-aware summary."


class RepairingProvider:
    provider_name = "stub"
    model = "repairing-model"

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
        citation = "[paper pp.1 chunk:one]"
        if "repair one evidence-aware paper summary" in system_prompt:
            finding = {
                "claim": "The method uses a world model.",
                "citations": [citation],
                "inference": False,
            }
        else:
            finding = {
                "claim": "The method uses a world model.",
                "citations": ["[paper pp.99 chunk:imaginary]"],
                "inference": False,
            }
        return JsonCompletionResult(
            payload={
                "summary_short": "Repairable summary.",
                "summary_detailed": "Repairable detailed summary.",
                "research_question": "Can a world model help?",
                "methods": ["Method"],
                "findings": [finding],
                "limitations": [],
                "key_terms": ["world model"],
                "implementation_notes": [],
                "inferences": [],
            },
            usage={"total_tokens": 7},
        )


def test_summary_repairs_invalid_citation_once(tmp_path) -> None:
    root = tmp_path / "field"
    _write_summary_fixture(root)
    provider = RepairingProvider()

    result = EvidenceSummaryGenerator(root, provider).summarize_index()
    paper = ResearchFolderHarness(root).load_index()["papers"][0]
    artifact = json.loads((root / paper["summary_artifact"]).read_text(encoding="utf-8"))

    assert result.summarized == 1
    assert result.failed == 0
    assert len(provider.calls) == 2
    assert artifact["request_count"] == 2
    assert "repaired" in artifact["fallback_reason"]
    assert artifact["summary"]["findings"][0]["citations"] == ["[paper pp.1 chunk:one]"]


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
