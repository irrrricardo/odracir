# Critical Scientific Conflicts

- Corpus: `sc-perturbation-dl-long-horizon-v1`
- Ledger revision: `8`
- Ledger digest: `sha256:1856a6c3ff5425207bd0cb1240ed2881b51cd9c1b2b639f36bf580e2d06a820a`
- Report digest: `sha256:29d2811fd2ff1b7119d774588fb0ea55f3bfa3458704f20439cd55986f86b895`
- Conflict count: `3`

The JSON artifact is the authoritative full-fidelity representation.

## C1-norman-double-perturbation-baseline — Norman double-perturbation performance relative to simple baselines

- Classification: `conditional_tension`
- Rationale: Both claims concern Norman multi-gene perturbations, but they use materially different evaluation conditions. Paper 1_12 evaluates held-out double perturbations across repeated random splits against additive and no-change baselines using aggregate prediction-error and interaction-recovery metrics. Paper 1_8 reports GEARS gains over CPA for selected non-additive genetic-interaction subtypes using correlation and precision-at-10. The apparent contradiction must therefore be reviewed only after harmonizing split, target, metric, and baseline family.
- Review question: Under the same Norman train/test split, non-additivity target, metric, and comparator set, does GEARS outperform the additive or no-change baseline, or are the two reported conclusions valid only under different evaluation protocols?

### Side A: `1_12` / `clm_5aa2545892ec3be37b6ecb2b`

- Packet: `accepted`, quality `0.8935`, reconciliation `false`
- Assertion: `ga_59482b3bbbcaa0202dc6be8f`, status `supported`, evidence weight `1000000` ppm
- Assertion statement: none of the seven deep learning models scgpt scfoundation uce scbert geneformer gears cpa outperformed the additive baseline in predicting double perturbation effects none outperformed the no-change baseline in predicting genetic interactions.
- Claim: None of the seven deep learning models (scGPT, scFoundation, UCE, scBERT, Geneformer, GEARS, CPA) outperformed the additive baseline in predicting double perturbation effects; none outperformed the no-change baseline in predicting genetic interactions.
- Claim provenance: chunk `90ad5cb8744c6029e02c`, pages `1–1`, paraphrased `true` — All models had a prediction error substantially higher than the additive baseline (Fig. 1a,b). None of the models was better than the ‘no change’ baseline.

| Result | Metric | Value | Provenance |
|---|---|---|---|
| `res_01edaaab5dd05987a9859b21` | True positive rate vs false discovery proportion for interaction prediction | None of the models was better than the ‘no change’ baseline. The same ranking of models was observed when using other metrics (Extended Data Fig. 4). | 90ad5cb8744c6029e02c p1–1; paraphrased=false; None of the models was better than the ‘no change’ baseline. The same ranking of models was observed when using other metrics (Extended Data Fig. 4). |
| `res_aab9d9407e8211a1b0cd617f` | Prediction error (L2 distance) | All models had a prediction error substantially higher than the additive baseline (Fig. 1a,b). | 90ad5cb8744c6029e02c p1–1; paraphrased=false; All models had a prediction error substantially higher than the additive baseline (Fig. 1a,b). |

### Side B: `1_8` / `clm_f58718572d19004a48bf4611`

- Packet: `provisional`, quality `0.8727`, reconciliation `true`
- Assertion: `ga_274ac4f9bd4d1edf30ffce2e`, status `unresolved`, evidence weight `350000` ppm
- Assertion statement: gears significantly outperforms cpa in predicting non-additive combinatorial perturbation effects across multiple genetic interaction subtypes with correlation coefficients 0.4 vs 0.0 and precision 10 improvements >40% for four of five subtypes.
- Claim: GEARS significantly outperforms CPA in predicting non-additive combinatorial perturbation effects across multiple genetic interaction subtypes, with correlation coefficients ~0.4 vs ~0.0, and precision@10 improvements >40% for four of five subtypes.
- Claim provenance: chunk `95fc598f94068058c5c1`, pages `3–3`, paraphrased `true` — GEARS improved precision@10 by more than 40% for four of five genetic interaction subtypes

| Result | Metric | Value | Provenance |
|---|---|---|---|
| `res_557d34433a3c4586acc81187` | Top ten accuracy (strongest interactions) | GEARS demonstrated a twofold increase in accuracy when predicting the ten strongest interactions | 95fc598f94068058c5c1 p3–3; paraphrased=false; GEARS demonstrated a twofold increase in accuracy when predicting the ten strongest interactions for a specific genetic interaction subtype |
| `res_7d2d2c68b056340cf109da39` | Correlation coefficient (R2) with true GI scores | GEARS correlation coefficient ~0.4 for synergy, neomorphism, redundancy; CPA ~0.0 | 95fc598f94068058c5c1 p3–3; paraphrased=false; the correlation coefficient (R2) was approximately 0.4 for synergy, neomorphism and redundancy, whereas it was only around 0.0 for the same interactions when predicted by CPA |
| `res_b78125637de7d5c3b154e7c1` | Mean squared error (top 20 affected genes) | GEARS captured different types of genetic interactions more than 40% better than existing methods across three of five subtypes | 95fc598f94068058c5c1 p3–3; paraphrased=true; GEARS was able to capture the effects of different types of genetic interactions more than 40% better than existing methods across three of the five genetic interaction subtypes |
| `res_bf3bea5d2a053d3f52586de8` | Precision@10 | GEARS improved precision@10 by more than 40% for four of five genetic interaction subtypes, >90% for redundancy and epistasis | 95fc598f94068058c5c1 p3–3; paraphrased=false; GEARS improved precision@10 by more than 40% for four of five genetic interaction subtypes, and the improvement exceeded 90% for redundancy and epistasis |

## C2-replogle-single-perturbation-baseline — Unseen single-perturbation performance on Replogle RPE1 and K562

- Classification: `conditional_tension`
- Rationale: Paper 1_12 finds that deep models do not consistently beat mean or linear baselines for unseen single perturbations on Adamson and Replogle K562/RPE1 data under the GEARS splitting procedure. Paper 1_8 reports large GEARS gains on RPE1 and K562, but its comparison set and metrics emphasize no-perturbation, CPA or GRN-style baselines, normalized MSE on top differentially expressed genes, and Pearson correlation. The word 'baselines' is not interchangeable across these protocols.
- Review question: When Replogle RPE1/K562 splits, preprocessing, evaluated genes, normalized-MSE or correlation metric, and baseline family are made identical, does GEARS still outperform the mean or linear baseline consistently across datasets?

### Side A: `1_12` / `clm_0c06723f53ffd93e2b614306`

- Packet: `accepted`, quality `0.8935`, reconciliation `false`
- Assertion: `ga_d424c9a86eb43e63ecba6743`, status `supported`, evidence weight `1000000` ppm
- Assertion statement: none of the deep learning models gears scgpt uce scbert geneformer consistently outperformed the mean baseline or the linear model in predicting unseen single perturbation effects.
- Claim: None of the deep learning models (GEARS, scGPT, UCE, scBERT, Geneformer) consistently outperformed the mean baseline or the linear model in predicting unseen single perturbation effects.
- Claim provenance: chunk `e1157b406b24c44a5c96`, pages `4–4`, paraphrased `false` — None of the deep learning models was able to consistently outperform the mean prediction or the linear model

| Result | Metric | Value | Provenance |
|---|---|---|---|
| `res_021b3c3fec3f886236904c23` | Prediction error (L2 distance) | None of the deep learning models was able to consistently outperform the mean prediction or the linear model (Fig. 2a and Extended Data Fig. 8). | e1157b406b24c44a5c96 p4–4; paraphrased=false; None of the deep learning models was able to consistently outperform the mean prediction or the linear model (Fig. 2a and Extended Data Fig. 8). |

### Side B: `1_8` / `clm_266e33da38756b4f055014b9`

- Packet: `provisional`, quality `0.8727`, reconciliation `true`
- Assertion: `ga_0f1f36df611d8297b376115b`, status `unresolved`, evidence weight `350000` ppm
- Assertion statement: gears significantly outperforms all baseline methods in predicting single-gene perturbation transcriptional responses on both rpe-1 and k562 datasets with m.s.e. improvement of 30-50% and pearson correlation more than double that of baselines.
- Claim: GEARS significantly outperforms all baseline methods in predicting single-gene perturbation transcriptional responses on both RPE-1 and K562 datasets, with m.s.e. improvement of 30-50% and Pearson correlation more than double that of baselines.
- Claim provenance: chunk `95fc598f94068058c5c1`, pages `3–3`, paraphrased `true` — GEARS significantly outperformed all baselines on both datasets with an m.s.e. improvement of 30–50%

| Result | Metric | Value | Provenance |
|---|---|---|---|
| `res_3ee69b01875722253e79fc27` | normalized mean squared error (top 20 DE genes) | GEARS m.s.e. at -47.2% improvement over no perturbation baseline for RPE-1 cells (single-gene pert.) | 95fc598f94068058c5c1 p3–3; paraphrased=true; GEARS significantly outperformed all baselines on both datasets with an m.s.e. improvement of 30–50% |
| `res_570d88041e2c5b536194d175` | Pearson correlation (all genes) | GEARS exhibited more than two times better performance in both cell lines | 95fc598f94068058c5c1 p3–3; paraphrased=false; When considering all genes using Pearson correlation, GEARS exhibited more than two times better performance in the case of both cell lines |
| `res_af4570af435a101465f6d93b` | normalized mean squared error (top 20 DE genes) | GEARS m.s.e. at -32.4% improvement over no perturbation baseline for K562 cells (single-gene pert.) | 95fc598f94068058c5c1 p3–3; paraphrased=true; GEARS significantly outperformed all baselines on both datasets with an m.s.e. improvement of 30–50% |

## C3-generalization-winner-ranking — Cross-task ranking of perturbation-generalization methods

- Classification: `performance_ranking`
- Rationale: Paper 1_19 reports that no method performs well across all perturbation-generalization datasets and assigns different winners to genetic, chemical-single, chemical-combination, small-data, and large-data tasks. Paper 1_17 reports that scDCA outperforms ChemCPA, BioLORD, and SAMS-VAE across all evaluated tasks, with its strongest gains in unseen-cell-line zero-shot and few-shot settings. A global winner cannot be selected until task type, dataset, split, dose or cell context, metric, and baseline roster are matched.
- Review question: On the exact datasets and splits shared by both studies, and separately for unseen drugs, unseen drug-cell-line combinations, and zero-shot or few-shot unseen cell lines, does scDCA remain superior under the benchmark metrics and complete comparator roster used by paper 1_19?

### Side A: `1_19` / `clm_cf4fffa61e81fce561f495c0`

- Packet: `provisional`, quality `0.8727`, reconciliation `true`
- Assertion: `ga_d6f10c8d88d3e9c10008a65d`, status `unresolved`, evidence weight `350000` ppm
- Assertion statement: no single method performs well across all datasets in the perturbation generalization scenario.
- Claim: No single method performs well across all datasets in the perturbation generalization scenario.
- Claim provenance: chunk `49fc71ae0e1db1dc81a6`, pages `12–12`, paraphrased `false` — Our findings revealed that no single method performs well across all datasets

| Result | Metric | Value | Provenance |
|---|---|---|---|
| `res_23931ae7f031f14e34cf74e0` | Best method for small training dataset | GenePert is the optimal choice when the training dataset is small. | 1bf733d287f142fd489c p10–10; paraphrased=false; GenePert is an optimal choice when the training dataset is small. |
| `res_56dc8b5514a704c78175ed2e` | Best method for chemical combined perturbations | baseReg baseline model achieves the highest accuracy in chemical combined-perturbation effect prediction. | 1bf733d287f142fd489c p10–10; paraphrased=true; the baseReg baseline model achieves the highest accuracy in chemical combined-perturbation effect prediction |
| `res_74d8d51682a4c65f39d7ccbd` | Best method for genetic combined perturbations | linearModel and scouter perform the best in predicting genetic combined-perturbation effects. | 1bf733d287f142fd489c p10–10; paraphrased=false; In predicting genetic combined-perturbation effects, linearModel and scouter perform the best. |
| `res_cc5f0f650fcdee274679ee54` | Best method for large fine-tuning dataset | CPA and scGPT are preferable when the fine-tuning dataset is sufficiently large. | 1bf733d287f142fd489c p10–10; paraphrased=false; when the fine-tuning dataset is sufficient, deep learning and foundation models such as CPA and scGPT are preferable. |
| `res_f12bda8c31df1add95de7f29` | Best method for chemical single perturbations | chemCPA is the preferred choice for chemical single-perturbation effect prediction. | 1bf733d287f142fd489c p10–10; paraphrased=false; In chemical single-perturbation effect prediction, chemCPA is the preferred choice. |

### Side B: `1_17` / `clm_b6256108f63b499eacad13dd`

- Packet: `provisional`, quality `0.8992`, reconciliation `true`
- Assertion: `ga_6008b65e7c66d343b0054892`, status `unresolved`, evidence weight `350000` ppm
- Assertion statement: scdca outperforms all baseline methods chemcpa biolord sams-vae across all tasks with particularly notable improvements in unseen cell line prediction zero-shot and few-shot .
- Claim: scDCA outperforms all baseline methods (ChemCPA, BioLORD, SAMS-VAE) across all tasks, with particularly notable improvements in unseen cell line prediction (zero-shot and few-shot).
- Claim provenance: chunk `313d6c4e46e82e3d309e`, pages `8–8`, paraphrased `false` — scDCA consistently outperforms the baseline models for all tasks, with the most notable improvement observed in the unseen cell line (zero-shot and few-shot) tasks.

| Result | Metric | Value | Provenance |
|---|---|---|---|
| `res_3dfd55587d8d52af756d1cd0` | R-squared (R2) | 0.83 ± 0.015 | 313d6c4e46e82e3d309e p8–8; paraphrased=true; Table 1: Comparison of scDCA and scGPT Finetuning (Mean ± SE) |
| `res_5370bc6ab964a3e6c534a353` | R-squared (R2) | 0.88 ± 0.004 | 313d6c4e46e82e3d309e p8–8; paraphrased=true; Table 1: Comparison of scDCA and scGPT Finetuning (Mean ± SE) |
| `res_5fc8e7ee1965515d8a4fd221` | t-statistic (paired t-test) | 31.5 | b283ca1ec2ed888496dc p18–18; paraphrased=false; scDCA vs ChemCPA 31.5 0.000 Yes |
| `res_7eed08a8ab6ef6a74a36c976` | t-statistic (paired t-test) | 9.0 | b283ca1ec2ed888496dc p18–18; paraphrased=false; scDCA vs ChemCPA 9.0 0.003 Yes |
| `res_a9522c3fbb24e90f3b34ad47` | t-statistic (paired t-test) | 4.5 | b283ca1ec2ed888496dc p18–18; paraphrased=false; scDCA vs ChemCPA 4.5 0.01 Yes |
| `res_f7c3d5dfc9d36aa65793cfbe` | R-squared (R2) | 0.82 ± 0.032 | 313d6c4e46e82e3d309e p8–8; paraphrased=true; Table 1: Comparison of scDCA and scGPT Finetuning (Mean ± SE) |
