# Odracir 2.2 run reports

For the API-free packet/chunk/locator-crosswalk package consumed by SciEngram
Ablation Lab, see
[`docs/ODRACIR_2_2_ABLATION_EVIDENCE_EXPORT.md`](docs/ODRACIR_2_2_ABLATION_EVIDENCE_EXPORT.md).

Packet output and run telemetry use separate, non-nested directories:

```bash
odracir extract-paper-study \
  --paper-folder papers \
  --output-folder run/packets \
  --report-folder run/report
```

`packets/` contains only successful paper-local JSON files. `report/` contains:

- `summary.json`: run totals, success/failure counts, aggregate token usage,
  aggregate latency, score range, and optional estimated cost;
- `papers.jsonl`: authoritative detailed record, one paper per line, including
  failures and separate extraction/judge telemetry;
- `papers.csv`: flat Excel-compatible view for sorting and plotting.

If `--report-folder` is omitted, the default is a sibling named by appending
`-report` to the output directory name. Both directories must be empty before
the run.

Token counts come from provider responses. Extraction and semantic-quality
judge usage are recorded separately and summed per paper and per run. Latency
is measured locally with a monotonic clock.

Cost is deliberately `null` unless both prices and a price date are explicit:

```bash
  --input-usd-per-million-tokens 0.00 \
  --output-usd-per-million-tokens 0.00 \
  --pricing-as-of YYYY-MM-DD
```

Replace the zero placeholders with the approved provider price snapshot for
the run. The amount is labelled `estimated_cost_usd`; Odracir does not fetch
mutable pricing or infer cached-token discounts.

Failed papers do not leave partial packet JSON. Their report row records the
error type/message and any stage telemetry that was available before failure.
If a quality judge returns a non-verbatim omission excerpt, Odracir performs
one constrained repair attempt. Both attempts' token usage and combined latency
are retained, including when the repaired audit still fails validation.
