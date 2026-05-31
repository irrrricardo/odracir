import json

from odracir.providers import JsonCompletionResult
from odracir.research_folder import ResearchFolderHarness
from odracir.skills import get_builtin_skill_registry
from odracir.summarization import EvidenceSummaryGenerator
from odracir.summary_evaluation import SummaryEvaluationHarness


class AuditStubProvider:
    provider_name = "stub"
    model = "audit-model"

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
            "summary_short": "Short summary.",
            "summary_detailed": "Detailed summary.",
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


def _evaluator(root) -> SummaryEvaluationHarness:
    return SummaryEvaluationHarness(
        root,
        skill_registry=get_builtin_skill_registry(),
    )


def test_summary_evaluation_reports_missing_summary_and_caches_artifact(tmp_path) -> None:
    root = tmp_path / "field"
    _write_chunked_fixture(root, "paper")
    index_before = (root / "odracir_index.json").read_bytes()

    first = _evaluator(root).evaluate()
    second = _evaluator(root).evaluate()

    assert first.status_counts == {"missing_summary": 1}
    assert first.artifact_path is not None
    assert second.cached is True
    assert (root / first.artifact_path).is_file()
    assert (root / "odracir_index.json").read_bytes() == index_before


def test_summary_evaluation_passes_current_generic_summary(tmp_path) -> None:
    root = tmp_path / "field"
    _write_chunked_fixture(root, "paper")
    EvidenceSummaryGenerator(root, AuditStubProvider()).summarize_index()

    report = _evaluator(root).evaluate(write_artifact=False)
    record = report.records[0]

    assert report.artifact_path is None
    assert report.status_counts == {"passed": 1}
    assert record.metrics["findings"] == 1
    assert record.metrics["unique_citations"] == 1


def test_summary_evaluation_warns_for_empty_biomedical_fields(tmp_path) -> None:
    root = tmp_path / "field"
    _write_chunked_fixture(root, "paper")
    registry = get_builtin_skill_registry()
    skill = registry.get("biomedical-paper")
    EvidenceSummaryGenerator(root, AuditStubProvider(), skill=skill).summarize_index()

    report = _evaluator(root).evaluate(expected_skill=skill, write_artifact=False)
    record = report.records[0]

    assert report.status_counts == {"warning": 1}
    assert record.metrics["domain_namespace"] == "biomedical"
    assert record.metrics["domain_populated_fields"] == 1
    assert "Domain fields are empty" in record.warnings[0]


def test_summary_evaluation_rejects_stale_chunk_artifact(tmp_path) -> None:
    root = tmp_path / "field"
    harness = _write_chunked_fixture(root, "paper")
    EvidenceSummaryGenerator(root, AuditStubProvider()).summarize_index()
    paper = harness.load_index()["papers"][0]
    (root / paper["chunk_artifact"]).write_text('{"chunks": []}', encoding="utf-8")

    report = _evaluator(root).evaluate(write_artifact=False)

    assert report.status_counts == {"failed": 1}
    assert "stale because chunk content changed" in report.records[0].errors[0]


def test_summary_evaluation_isolates_invalid_summary_artifact(tmp_path) -> None:
    root = tmp_path / "field"
    harness = _write_chunked_fixture(root, "paper-a", "paper-b")
    EvidenceSummaryGenerator(root, AuditStubProvider()).summarize_index()
    papers = harness.load_index()["papers"]
    broken_path = root / papers[0]["summary_artifact"]
    broken = json.loads(broken_path.read_text(encoding="utf-8"))
    broken["skill"]["name"] = "imaginary"
    broken_path.write_text(json.dumps(broken), encoding="utf-8")

    report = _evaluator(root).evaluate(write_artifact=False)

    assert report.status_counts == {"failed": 1, "passed": 1}
    assert "Unknown research skill" in report.records[0].errors[0]
    assert report.records[1].status == "passed"


def test_summary_evaluation_isolates_malformed_domain_extension(tmp_path) -> None:
    root = tmp_path / "field"
    harness = _write_chunked_fixture(root, "paper-a", "paper-b")
    skill = get_builtin_skill_registry().get("biomedical-paper")
    EvidenceSummaryGenerator(root, AuditStubProvider(), skill=skill).summarize_index()
    papers = harness.load_index()["papers"]
    broken_path = root / papers[0]["summary_artifact"]
    broken = json.loads(broken_path.read_text(encoding="utf-8"))
    broken["summary"]["domain_extensions"]["biomedical"] = []
    broken_path.write_text(json.dumps(broken), encoding="utf-8")

    report = _evaluator(root).evaluate(expected_skill=skill, write_artifact=False)

    assert report.status_counts == {"failed": 1, "warning": 1}
    assert "domain_extensions.biomedical" in report.records[0].errors[0]
    assert report.records[1].status == "warning"
