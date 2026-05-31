import json

from odracir.providers import JsonCompletionResult
from odracir.research_folder import ResearchFolderHarness
from odracir.research_memory import ResearchCatalogBuilder
from odracir.skills import get_builtin_skill_registry
from odracir.summarization import EvidenceSummaryGenerator


class MemoryStubProvider:
    provider_name = "stub"
    model = "memory-model"

    def __init__(self) -> None:
        self.last_citation = ""

    def complete_json(self, *, system_prompt: str, user_prompt: str, max_tokens: int):
        if "one traceable chunk" in system_prompt:
            self.last_citation = user_prompt.split("Citation: ", 1)[1].splitlines()[0]
            return JsonCompletionResult(
                payload={
                    "chunk_summary": "Local evidence.",
                    "key_points": [
                        {"claim": "Evidence.", "citation": self.last_citation}
                    ],
                    "methods": [],
                    "limitations": ["Limited external validation."],
                    "key_terms": ["world model"],
                },
                usage={},
            )

        payload = {
            "summary_short": "Short memory.",
            "summary_detailed": "Detailed memory.",
            "research_question": "Can prediction help?",
            "methods": ["Method"],
            "findings": [
                {
                    "claim": "Prediction supports planning.",
                    "citations": [self.last_citation],
                    "inference": False,
                }
            ],
            "limitations": ["Limited external validation."],
            "key_terms": ["world model"],
            "implementation_notes": [],
            "inferences": [],
        }
        if "domain_extensions" in system_prompt:
            payload["domain_extensions"] = {
                "biomedical": {
                    "population": [
                        {
                            "value": "Patients with longitudinal records.",
                            "citations": [self.last_citation],
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
        return JsonCompletionResult(payload=payload, usage={})


def _write_chunked_fixture(root, *paper_names: str) -> ResearchFolderHarness:
    papers = root / "papers"
    papers.mkdir(parents=True)
    for paper_name in paper_names:
        (papers / f"{paper_name}.pdf").write_bytes(b"%PDF-1.4\n")
    harness = ResearchFolderHarness(root)
    harness.sync_index()
    index = harness.load_index()
    chunks_dir = root / ".odracir" / "chunks"
    chunks_dir.mkdir(parents=True)
    for paper in index["papers"]:
        paper["chunking_status"] = "chunked"
        paper["chunk_artifact"] = f".odracir/chunks/{paper['id']}.json"
        (root / paper["chunk_artifact"]).write_text(
            json.dumps(
                {
                    "chunks": [
                        {
                            "id": "one",
                            "page_start": 1,
                            "page_end": 1,
                            "text": "Longitudinal evidence supports prediction.",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
    harness.write_index(index)
    return harness


def test_research_memory_records_missing_summaries_and_caches_catalog(tmp_path) -> None:
    root = tmp_path / "field"
    _write_chunked_fixture(root, "paper")
    index_before = (root / "odracir_index.json").read_bytes()

    first = ResearchCatalogBuilder(root).build()
    second = ResearchCatalogBuilder(root).build()

    assert first.quality_counts == {"missing_summary": 1}
    assert first.records[0]["summary"] is None
    assert first.catalog_path == str(root / "research_catalog.json")
    assert second.cached is True
    assert (root / "odracir_index.json").read_bytes() == index_before


def test_research_memory_aggregates_audited_generic_summary(tmp_path) -> None:
    root = tmp_path / "field"
    _write_chunked_fixture(root, "paper")
    EvidenceSummaryGenerator(root, MemoryStubProvider()).summarize_index()

    result = ResearchCatalogBuilder(root).build()
    record = result.records[0]

    assert result.quality_counts == {"passed": 1}
    assert record["summary"]["summary_short"] == "Short memory."
    assert record["summary_provenance"]["skill"]["name"] == "generic"
    assert record["summary_provenance"]["skill"]["version"] == "0.1"


def test_research_memory_preserves_biomedical_extension(tmp_path) -> None:
    root = tmp_path / "field"
    _write_chunked_fixture(root, "paper")
    skill = get_builtin_skill_registry().get("biomedical-paper")
    EvidenceSummaryGenerator(root, MemoryStubProvider(), skill=skill).summarize_index()

    result = ResearchCatalogBuilder(root).build()
    record = result.records[0]

    assert result.quality_counts == {"warning": 1}
    assert record["summary"]["domain_extensions"]["biomedical"]["population"]
    assert "Domain fields are empty" in record["memory_quality"]["warnings"][0]


def test_research_memory_rebuilds_when_summary_artifact_changes(tmp_path) -> None:
    root = tmp_path / "field"
    harness = _write_chunked_fixture(root, "paper")
    EvidenceSummaryGenerator(root, MemoryStubProvider()).summarize_index()
    first = ResearchCatalogBuilder(root).build()
    paper = harness.load_index()["papers"][0]
    summary_path = root / paper["summary_artifact"]
    artifact = json.loads(summary_path.read_text(encoding="utf-8"))
    artifact["summary"]["summary_short"] = "Updated memory."
    summary_path.write_text(json.dumps(artifact), encoding="utf-8")

    second = ResearchCatalogBuilder(root).build()

    assert second.cached is False
    assert second.input_sha256 != first.input_sha256
    assert second.records[0]["summary"]["summary_short"] == "Updated memory."


def test_research_memory_isolates_failed_summary_artifact(tmp_path) -> None:
    root = tmp_path / "field"
    harness = _write_chunked_fixture(root, "paper-a", "paper-b")
    EvidenceSummaryGenerator(root, MemoryStubProvider()).summarize_index()
    papers = harness.load_index()["papers"]
    broken_path = root / papers[0]["summary_artifact"]
    broken = json.loads(broken_path.read_text(encoding="utf-8"))
    broken["skill"]["name"] = "imaginary"
    broken_path.write_text(json.dumps(broken), encoding="utf-8")

    result = ResearchCatalogBuilder(root).build(write_artifact=False)

    assert result.catalog_path is None
    assert result.quality_counts == {"failed": 1, "passed": 1}
    assert result.records[0]["summary"] is None
    assert "Unknown research skill" in result.records[0]["memory_quality"]["errors"][0]
    assert result.records[1]["summary"]["summary_short"] == "Short memory."
