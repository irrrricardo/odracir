# Odracir 2.2 quality protocol

Odracir 2.2 separates extraction quality from the scientific strength of the
paper's evidence. Both reference documents are currently arXiv preprints, not
verified peer-reviewed publications: Agents-K1 v2 (`arXiv:2606.13669`) and
EvidenceNet v3 (`arXiv:2603.28325`). Their protocols are useful design evidence,
but their reported performance is not treated as an established benchmark for
Odracir.

## Primary extraction-quality score

Following the semantic evaluation in Agents-K1, an LLM judge compares every
atomic extracted item with the complete paper text. It reports:

- `N_ext`: extracted questions, tasks, datasets, methods, results, claims, and
  limitations;
- `N_err`: unsupported, contradicted, or materially overstated extracted items;
- `N_miss`: omitted core methods, datasets, experiments, quantitative results,
  central findings, or material limitations.

The public `quality_score` is semantic F1:

```text
correct   = N_ext - N_err
precision = correct / N_ext
recall    = correct / (correct + N_miss)
F1        = 2 * precision * recall / (precision + recall)
```

The judge is lenient about wording and synonyms, accepts faithful abstraction,
and does not count minor details, generic background, citations, or incidental
hyperparameters as misses. Every reported error binds to an extracted item ID;
every reported omission must bind to a real source chunk and exact excerpt.
Unknown IDs and non-source excerpts fail validation.

Recall is judged against all PDF page chunks, even when extraction selected only
a subset. This prevents a narrow extraction prompt from obtaining an artificial
perfect score by hiding unselected pages from the evaluator.

## Secondary diagnostics

The former deterministic score remains as `deterministic_rule_score`. It checks
schema completeness, provenance coverage, and boundary richness, but does not
decide the 2.2 `quality_score`.

EvidenceNet's composite score combines study design, source impact, statistical
support, sample size, and LLM confidence. That measures evidence strength rather
than extraction fidelity. Odracir therefore does not fold it into semantic F1.
It reports only source-observable diagnostics:

- fraction of results with p-values;
- fraction of results with sample sizes;
- log-normalized sample-size signal when sample sizes are present.

Journal impact and citation signals are intentionally absent because Odracir 2.2
does not query external bibliometric sources and must not invent them.

## Limitations

- The judge is model-based and not a substitute for blinded human annotation.
- Using the same model family for extraction and judging may introduce correlated
  error; a future benchmark should compare independent judges and human labels.
- Structured extraction and judging use temperature zero to reduce avoidable
  run-to-run variance, but provider-side nondeterminism may still remain.
- A single-paper score is a smoke result, not evidence that the metric is
  calibrated. Calibration requires a stratified, manually annotated paper set.
