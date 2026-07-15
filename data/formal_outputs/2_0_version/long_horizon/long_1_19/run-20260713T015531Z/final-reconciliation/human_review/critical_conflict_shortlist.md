# Critical conflict shortlist

Only 3 high-value candidate tensions are listed. 
They are not ledger-declared unconditional contradictions.

## 1. Norman double-perturbation performance relative to simple baselines

- Pair: `1_12/clm_5aa2545892ec3be37b6ecb2b` (accepted, q=0.8935) vs `1_8/clm_f58718572d19004a48bf4611` (provisional, q=0.8727)
- Classification: `conditional_tension`
- Human decision: Under the same Norman train/test split, non-additivity target, metric, and comparator set, does GEARS outperform the additive or no-change baseline, or are the two reported conclusions valid only under different evaluation protocols?
- Recommended encoding: Treat as conditioned_on(split, target, metric, baseline_family); do not select a global winner.

## 2. Unseen single-perturbation performance on Replogle RPE1 and K562

- Pair: `1_12/clm_0c06723f53ffd93e2b614306` (accepted, q=0.8935) vs `1_8/clm_266e33da38756b4f055014b9` (provisional, q=0.8727)
- Classification: `conditional_tension`
- Human decision: When Replogle RPE1/K562 splits, preprocessing, evaluated genes, normalized-MSE or correlation metric, and baseline family are made identical, does GEARS still outperform the mean or linear baseline consistently across datasets?
- Recommended encoding: Treat as conditioned_on(split, preprocessing, evaluated_genes, metric, baseline_family).

## 3. Cross-task ranking of perturbation-generalization methods

- Pair: `1_19/clm_cf4fffa61e81fce561f495c0` (provisional, q=0.8727) vs `1_17/clm_b6256108f63b499eacad13dd` (provisional, q=0.8992)
- Classification: `performance_ranking`
- Human decision: On the exact datasets and splits shared by both studies, and separately for unseen drugs, unseen drug-cell-line combinations, and zero-shot or few-shot unseen cell lines, does scDCA remain superior under the benchmark metrics and complete comparator roster used by paper 1_19?
- Recommended encoding: Treat as conditioned_on(task, dataset, split, cell_context, dose, metric, comparator_roster); do not encode a global winner.
