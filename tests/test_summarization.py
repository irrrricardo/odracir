import json

from odracir.providers import JsonCompletionResult
from odracir.research_folder import ResearchFolderHarness
from odracir.summarization import EvidenceSummaryGenerator


class StubProvider:
    provider_name = "stub"
    model = "stub-model"

    def __init__(
        self,
        *,
        cite_findings: bool = True,
        finding_citation: str = "[paper pp.1 chunk:one]",
    ) -> None:
        self.calls = []
        self.cite_findings = cite_findings
        self.finding_citation = finding_citation

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
        return JsonCompletionResult(
            payload={
                "summary_short": "Short evidence-aware summary.",
                "summary_detailed": "Detailed evidence-aware summary.",
                "research_question": "Can a world model help?",
                "methods": ["Method"],
                "findings": [finding],
                "limitations": [],
                "key_terms": ["world model"],
                "implementation_notes": [],
                "inferences": [],
            },
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
