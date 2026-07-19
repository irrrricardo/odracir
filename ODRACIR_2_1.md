# Odracir 2.1

Odracir 2.1 has one responsibility: independently convert each input PDF into
one paper-local JSON document. Corpus reasoning belongs to downstream
SciEngram.

```bash
odracir extract-paper-study \
  --paper-folder /path/to/pdfs \
  --output-folder /path/to/empty/output
```

For `N` valid PDFs, the successful output is a flat directory of `N` files:

```text
output/
├── paper-1.json
├── paper-2.json
└── ...
```

The output folder must be empty before a run. This prevents stale files from a
previous corpus being mistaken for current results. A failed paper does not
leave a partial JSON file; failures are reported in the CLI's stdout summary
and produce a non-zero exit status.

The 2.1 execution path has no reconnaissance, duplicate collapse, clustering,
chronological batching, rolling global context, belief ledger, inter-paper
relations, delivery reconciliation, or corpus manifest. Byte-identical PDFs
with distinct filenames remain distinct inputs and receive distinct outputs.

The `.odracir/texts` and `.odracir/chunks` directories under the input folder
are reusable PDF-ingestion caches, not output or corpus-level artifacts.
