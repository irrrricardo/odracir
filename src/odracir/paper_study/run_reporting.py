"""Machine- and spreadsheet-friendly run reporting for Odracir 2.2."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from pydantic import Field, model_validator

from odracir.paper_study.models import StrictModel


class PricingSnapshot(StrictModel):
    currency: str = Field(default="USD", min_length=1)
    input_usd_per_million_tokens: float | None = Field(default=None, ge=0.0)
    output_usd_per_million_tokens: float | None = Field(default=None, ge=0.0)
    pricing_as_of: str | None = None
    pricing_source: str = "explicit-run-config"

    @model_validator(mode="after")
    def require_complete_pair(self) -> PricingSnapshot:
        values = (
            self.input_usd_per_million_tokens,
            self.output_usd_per_million_tokens,
        )
        if (values[0] is None) != (values[1] is None):
            raise ValueError("input and output token prices must be supplied together")
        if values[0] is not None and not self.pricing_as_of:
            raise ValueError("pricing_as_of is required when token prices are supplied")
        return self


class StageMetrics(StrictModel):
    model: str = Field(min_length=1)
    attempts: int = Field(ge=0)
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    usage_complete: bool = True
    latency_seconds: float = Field(ge=0.0)
    estimated_cost_usd: float | None = Field(default=None, ge=0.0)
    finish_reason: str | None = None


class PaperRunRecord(StrictModel):
    paper_id: str = Field(min_length=1)
    source_file: str = Field(min_length=1)
    source_sha256: str | None = None
    status: str
    output_file: str | None = None
    pages: int | None = Field(default=None, ge=0)
    source_chunks: int | None = Field(default=None, ge=0)
    selected_chunks: int | None = Field(default=None, ge=0)
    extraction: StageMetrics | None = None
    quality_judge: StageMetrics | None = None
    quality_score: float | None = Field(default=None, ge=0.0, le=1.0)
    precision: float | None = Field(default=None, ge=0.0, le=1.0)
    recall: float | None = Field(default=None, ge=0.0, le=1.0)
    deterministic_rule_score: float | None = Field(default=None, ge=0.0, le=1.0)
    incorrect_item_count: int | None = Field(default=None, ge=0)
    missed_core_item_count: int | None = Field(default=None, ge=0)
    total_prompt_tokens: int = Field(default=0, ge=0)
    total_completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    usage_complete: bool = True
    total_latency_seconds: float = Field(default=0.0, ge=0.0)
    estimated_cost_usd: float | None = Field(default=None, ge=0.0)
    error_type: str | None = None
    error_message: str | None = None


class RunReportSummary(StrictModel):
    schema_version: str = "odracir-run-report/1"
    odracir_version: str = "2.2.0"
    started_at: str
    completed_at: str
    input_folder: str
    output_folder: str
    report_folder: str
    input_pdf_count: int = Field(ge=0)
    succeeded: int = Field(ge=0)
    failed: int = Field(ge=0)
    total_prompt_tokens: int = Field(ge=0)
    total_completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    usage_complete: bool = True
    estimated_cost_is_lower_bound: bool = False
    total_latency_seconds: float = Field(ge=0.0)
    estimated_cost_usd: float | None = Field(default=None, ge=0.0)
    mean_quality_score: float | None = Field(default=None, ge=0.0, le=1.0)
    minimum_quality_score: float | None = Field(default=None, ge=0.0, le=1.0)
    maximum_quality_score: float | None = Field(default=None, ge=0.0, le=1.0)
    pricing: PricingSnapshot


def stage_metrics(
    *,
    model: str,
    attempts: int,
    usage: dict[str, int],
    latency_seconds: float,
    pricing: PricingSnapshot,
    finish_reason: str | None,
    usage_complete: bool = True,
) -> StageMetrics:
    prompt = _usage_value(usage, "prompt_tokens", "input_tokens")
    completion = _usage_value(usage, "completion_tokens", "output_tokens")
    # Recompute the aggregate total.  Mixed provider attempts may omit total_tokens on
    # some responses; summing only the reported totals would then undercount the run.
    total = prompt + completion
    cost = _estimated_cost(prompt, completion, pricing)
    return StageMetrics(
        model=model,
        attempts=attempts,
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=total,
        usage_complete=usage_complete,
        latency_seconds=round(latency_seconds, 6),
        estimated_cost_usd=cost,
        finish_reason=finish_reason,
    )


def finalize_record(record: PaperRunRecord) -> PaperRunRecord:
    stages = [stage for stage in (record.extraction, record.quality_judge) if stage]
    costs = [stage.estimated_cost_usd for stage in stages]
    return record.model_copy(
        update={
            "total_prompt_tokens": sum(stage.prompt_tokens for stage in stages),
            "total_completion_tokens": sum(stage.completion_tokens for stage in stages),
            "total_tokens": sum(stage.total_tokens for stage in stages),
            "usage_complete": all(stage.usage_complete for stage in stages),
            "total_latency_seconds": round(
                sum(stage.latency_seconds for stage in stages), 6
            ),
            "estimated_cost_usd": (
                round(sum(cost for cost in costs if cost is not None), 8)
                if costs and all(cost is not None for cost in costs)
                else None
            ),
        }
    )


def write_run_report(
    records: list[PaperRunRecord],
    *,
    report_folder: str | Path,
    input_folder: str,
    output_folder: str,
    started_at: datetime,
    pricing: PricingSnapshot,
) -> tuple[RunReportSummary, dict[str, str]]:
    root = Path(report_folder).expanduser().resolve()
    _prepare_empty_folder(root)
    completed_at = datetime.now(timezone.utc)
    scores = [record.quality_score for record in records if record.quality_score is not None]
    costs = [record.estimated_cost_usd for record in records]
    summary = RunReportSummary(
        started_at=started_at.isoformat(),
        completed_at=completed_at.isoformat(),
        input_folder=input_folder,
        output_folder=output_folder,
        report_folder=str(root),
        input_pdf_count=len(records),
        succeeded=sum(record.status == "succeeded" for record in records),
        failed=sum(record.status == "failed" for record in records),
        total_prompt_tokens=sum(record.total_prompt_tokens for record in records),
        total_completion_tokens=sum(record.total_completion_tokens for record in records),
        total_tokens=sum(record.total_tokens for record in records),
        usage_complete=all(record.usage_complete for record in records),
        estimated_cost_is_lower_bound=not all(
            record.usage_complete for record in records
        ),
        total_latency_seconds=round(sum(record.total_latency_seconds for record in records), 6),
        estimated_cost_usd=(
            round(sum(cost for cost in costs if cost is not None), 8)
            if costs and all(cost is not None for cost in costs)
            else None
        ),
        mean_quality_score=(round(sum(scores) / len(scores), 4) if scores else None),
        minimum_quality_score=min(scores) if scores else None,
        maximum_quality_score=max(scores) if scores else None,
        pricing=pricing,
    )
    summary_path = root / "summary.json"
    jsonl_path = root / "papers.jsonl"
    csv_path = root / "papers.csv"
    _write_json(summary.model_dump(mode="json"), summary_path)
    _write_jsonl(records, jsonl_path)
    _write_csv(records, csv_path)
    return summary, {
        "summary": str(summary_path.resolve()),
        "jsonl": str(jsonl_path.resolve()),
        "csv": str(csv_path.resolve()),
    }


def _write_csv(records: list[PaperRunRecord], path: Path) -> None:
    columns = (
        "paper_id", "status", "quality_score", "precision", "recall",
        "deterministic_rule_score", "incorrect_item_count", "missed_core_item_count",
        "total_prompt_tokens", "total_completion_tokens", "total_tokens",
        "estimated_cost_usd", "usage_complete", "total_latency_seconds", "output_file",
        "error_type", "error_message",
    )
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for record in records:
            payload = record.model_dump(mode="json")
            writer.writerow({column: payload.get(column) for column in columns})
    temporary.replace(path)


def _write_jsonl(records: list[PaperRunRecord], path: Path) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        "".join(
            json.dumps(record.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
            + "\n"
            for record in records
        ),
        encoding="utf-8",
    )
    temporary.replace(path)


def _write_json(payload: object, path: Path) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _prepare_empty_folder(root: Path) -> None:
    if root.exists() and any(root.iterdir()):
        raise ValueError(f"report folder must be empty: {root}")
    root.mkdir(parents=True, exist_ok=True)


def _usage_value(usage: dict[str, int], primary: str, alternative: str) -> int:
    return int(usage.get(primary, usage.get(alternative, 0)))


def _estimated_cost(
    prompt_tokens: int,
    completion_tokens: int,
    pricing: PricingSnapshot,
) -> float | None:
    if pricing.input_usd_per_million_tokens is None:
        return None
    assert pricing.output_usd_per_million_tokens is not None
    return round(
        prompt_tokens * pricing.input_usd_per_million_tokens / 1_000_000
        + completion_tokens * pricing.output_usd_per_million_tokens / 1_000_000,
        8,
    )
