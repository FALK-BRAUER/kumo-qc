# QC-Safe Feature Subset Experiment

Issue: #423

Purpose: test whether the scanner-alignment rankers still work when the feature matrix is restricted to
columns that the promotion gate marks as both `safe_for_qc_handoff=True` and
`deployability_class=qc_cloud_deployable`.

## Protocol

- Label set: `george_oof_stage1_scores.csv`, 306 covered George rows.
- Denominator: `george_ranking_denominator_profiled.csv`.
- Base panel: top3000 ADV20 price>=10, BCT score>=6.
- Validation: chronological date-grouped OOF folds.
- Feature gate: `feature_parity_columns.csv`.
- Models: LightGBM LambdaMART and dependency-free pairwise linear ranker.
- Runtime status: research-only result. No runtime promotion from this experiment.

The LambdaMART command enabled sector context, denominator ranks, and sector breadth, matching #435, then
filtered the final matrix through the QC-cloud-safe allowlist. The allowlist has 98 columns; the ranker
used 60 surviving columns after intersecting with the harness feature set.

## Result

| Variant | Gate | hits@5 | hits@10 | hits@20 | hits@50 | hits@100 | precision@10 | median George rank |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| LambdaMART QC-safe subset | clean_top2000 | 52 | 88 | 133 | 183 | 204 | 19.13% | 15.0 |
| LambdaMART QC-safe subset | score7_or_clean6 | 48 | 74 | 120 | 173 | 213 | 16.09% | 21.5 |
| LambdaMART QC-safe subset | all rows | 47 | 72 | 117 | 178 | 223 | 15.65% | 29.0 |
| Pairwise QC-safe subset | clean_top2000 | 26 | 54 | 95 | 149 | 184 | 11.74% | 25.5 |
| Pairwise QC-safe subset | all rows | 15 | 32 | 72 | 130 | 182 | 6.96% | 57.0 |

## Comparison

- Full-feature #435 LambdaMART all-rows recall@10: `107/306`.
- QC-safe LambdaMART all-rows recall@10: `72/306`, a `-35` hit regression.
- Full-feature #435 LambdaMART clean_top2000 recall@10: `100/306`.
- QC-safe LambdaMART clean_top2000 recall@10: `88/306`, a `-12` hit regression.
- Full-feature #434 pairwise clean_top2000 recall@10: `88/306`.
- QC-safe pairwise clean_top2000 recall@10: `54/306`, a `-34` hit regression.

The clean_top2000 LambdaMART subset is the best deployable-feature result in this pass, but it is still
only `28.76%` recall@10. The scanner promotion gate target remains `38.11%` recall@10 over the 306 labels,
so this experiment does not promote a runtime ranker.

## Read

The remaining deployable signal is mostly raw chart and volume behavior: `day_return_pct`,
`d_tenkan_extension_pct`, `d_return_10d_pct`, `d_cloud_distance_pct`, `w_cloud_distance_pct`,
`rel_volume20`, `gap_pct`, ADX/DI fields, wick/body fields, and daily structure score.

The lost lift points to blocked feature classes rather than a pure model-class problem:

- denominator-relative ranks from the live panel;
- profiled TC2000-style sector and industry breadth;
- lab-only feature-rich scores and model outputs.

Next promotable path: either make the denominator-relative rank features reproducible in QC cloud, or train
a constrained clean_top2000 LambdaMART model that is explicitly optimized around the surviving raw chart
features and beats this `88/306` benchmark.
