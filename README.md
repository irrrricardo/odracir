# Odracir 2.2

[中文说明](README.zh-CN.md)

Odracir is a paper-local scientific evidence compiler. It converts each input
PDF independently into one typed, provenance-bound, quality-gated JSON packet
for downstream systems such as SciEngram.

Odracir 2.2 does **not** compare papers, propagate cross-paper context, infer
inter-paper relations, or maintain belief states. Those are downstream tasks.
The core contract is:

```text
N PDFs in a folder -> N independent JSON packets + one separate run report
```

## What the packet contains

Each packet represents the paper as:

```text
ResearchQuestion
  -> StudyUnit / experiment
       -> Dataset and Method
       -> ResultObservation
       -> Claim
            -> inference_basis_ids
            -> page/chunk/excerpt provenance
```

Claims may reference results only inside the same `StudyUnit`. Provenance
records identify source chunks and pages, and distinguish faithful paraphrases
from near-verbatim excerpts.

## Pipeline

1. Recursively discover PDFs and extract page text with PyMuPDF.
2. Create stable page-level chunks and source hashes under `.odracir/`.
3. Classify the paper's domain and scientific logic mode.
4. Select high-value chunks for structured LLM extraction.
5. Validate the strict 2.2 schema and repair invalid model output when possible.
6. Canonicalize duplicate objects within the paper.
7. Check ID references, StudyUnit-local support, pages, chunks, and excerpts.
8. Compute deterministic structure/provenance diagnostics.
9. Use a second LLM pass to audit errors and omissions against the full paper.
10. Deliver the packet only when semantic F1 meets the configured threshold.

A failed paper is isolated and never leaves a partial JSON file in the delivery
folder.

## Requirements

- Python 3.11 or later
- An extractable-text PDF; scanned PDFs require OCR before ingestion
- A DeepSeek-compatible API key for extraction and semantic judging

Install:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[test]"
cp .env.example .env
```

Set `DEEPSEEK_API_KEY` in `.env`. The default provider endpoint and model are:

```dotenv
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-pro
DEEPSEEK_THINKING=disabled
```

## Main command

For a folder containing any number of PDFs:

```bash
odracir extract-paper-study \
  --paper-folder /path/to/pdfs \
  --output-folder /path/to/run/packets \
  --report-folder /path/to/run/report \
  --env-file .env
```

PDF discovery is recursive. Directories named `.odracir` are excluded.

Important options:

- `--max-chunks 4`: maximum chunks used for initial extraction.
- `--max-tokens 16000`: maximum completion tokens per model request.
- `--validation-retries 1`: retries after invalid structured output.
- `--minimum-quality-score 0.6`: semantic-F1 delivery threshold.
- `--index PATH`: optional JSON index selecting prepared paper artifacts.
- `--input-usd-per-million-tokens` and
  `--output-usd-per-million-tokens`: optional pricing snapshot for cost reports.

The command exits non-zero if any paper fails, while preserving all successful
packets and complete per-paper telemetry.

## Outputs

```text
run/
├── packets/
│   ├── paper-a.json
│   └── paper-b.json
└── report/
    ├── summary.json
    ├── papers.jsonl
    └── papers.csv
```

The delivery folder contains only accepted packet JSON files. Reports are kept
separate and include extraction/judge attempts, token usage, latency, estimated
cost, precision, recall, semantic F1, failure details, and whether usage
telemetry is complete.

## Quality protocol

Odracir uses complementary controls:

- **Hard validation:** strict schema, unique IDs, legal references, source
  pages/chunks, and StudyUnit-local Claim-to-Result links.
- **Deterministic diagnostics:** 50% structural completeness, 35% provenance
  coverage, and 15% boundary richness.
- **Semantic audit:** a model judge compares all atomic extracted items against
  every page chunk, reports incorrect and missed core items, and calculates
  precision, recall, and F1.

The semantic score measures extraction fidelity, not the scientific strength of
the source paper. P-value and sample-size observability are therefore reported
separately. See [ODRACIR_2_2_QUALITY.md](ODRACIR_2_2_QUALITY.md).

## Recover failed papers

Recovery retries only failed records, normally with broader source coverage. It
verifies source hashes and never overwrites an accepted delivery:

```bash
python scripts/recover_independent_run.py \
  --source-report /path/to/run/report/papers.jsonl \
  --paper-folder /path/to/pdfs \
  --delivery-folder /path/to/run/packets \
  --work-folder /path/to/recovery/work \
  --report-folder /path/to/recovery/report \
  --env-file .env
```

Recovery defaults to `--max-chunks 8` and `--validation-retries 3`.

## Export evidence for SciEngram ablations

This command is deterministic and API-free. It validates and exports namespaced
packets, reconstructed chunks, and exact locator crosswalks:

```bash
odracir export-ablation-evidence \
  --corpus-root /path/to/formal_corpus \
  --packets-root /path/to/formal_outputs \
  --output-folder /path/to/ablation_evidence
```

See
[docs/ODRACIR_2_2_ABLATION_EVIDENCE_EXPORT.md](docs/ODRACIR_2_2_ABLATION_EVIDENCE_EXPORT.md).

## Formal validation

The repository includes a completed 228-paper run:

- 228 input PDFs and 228 delivered schema-2.2 packets;
- all final packets passed the configured semantic-F1 threshold of 0.6;
- observed final semantic F1: mean 0.9600, minimum 0.6176;
- 5,543 provenance-to-chunk bindings in the ablation evidence export;
- 13.45 million recorded tokens;
- estimated total model cost about USD 7.06, with incomplete telemetry explicitly
  marked rather than silently imputed.

These are operational results from a model-based judge, not human-annotated
benchmark accuracy. See [ODRACIR_2_2_RUN_REPORT.md](ODRACIR_2_2_RUN_REPORT.md).

## Source layout

```text
src/odracir/
├── cli.py
└── paper_study/
    ├── ingestion.py
    ├── inputs.py
    ├── planning.py
    ├── domains.py
    ├── extraction.py
    ├── models.py
    ├── canonicalization.py
    ├── quality.py
    ├── semantic_quality.py
    ├── independent.py
    ├── independent_recovery.py
    ├── run_reporting.py
    └── ablation_evidence.py
```

## Current limitations

- PyMuPDF text extraction does not fully recover figures, complex tables,
  equations, or scanned pages.
- The initial extraction sees selected chunks rather than the complete paper;
  full-paper semantic auditing and recovery reduce but do not eliminate this
  risk.
- The semantic judge is model-based and may share errors with the extraction
  model.
- The formal corpus is not a blinded, manually annotated gold benchmark.

## Development

```bash
python -m pytest -q
```

The supported public CLI consists of `extract-paper-study` and
`export-ablation-evidence`. Cross-paper reasoning belongs to SciEngram.
