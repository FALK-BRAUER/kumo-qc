# Scanner Opportunity Ranker #467

This report trains dependency-free pairwise linear rankers on future-path labels using
only scan-time features. Validation is expanding-window by scan date; no random split is used.

## Inputs

- Labels: `/Users/falk/projects/kumo-qc-467-opportunity-ranker/sweeps/reports/scanner_opportunity_paths_464/opportunity_path_labels.csv.gz`
- Panel metadata: `/Users/falk/projects/kumo-qc-467-opportunity-ranker/sweeps/reports/scanner_opportunity_panel_463/opportunity_panel.csv.gz`
- Candidate filter: `kumo_top100_or_george`

## Coverage

- Rows: `23455`
- Dates: `234`
- OOF rows: `19586`
- Feature version: `scanner_opportunity_scan_time_v1`
- Feature hash: `96eda175c8439bc9b988e5823e37a4d7c11b46d3f33fb008f70087b0add2896e`

## Top-10 Trade-Worthy Ranking

| score | selected_rows | hit_rows | recall_pct | precision_pct | ndcg_mean | avg_ret20_topk_pct | bad_trade_pct_topk |
| --- | --- | --- | --- | --- | --- | --- | --- |
| model_runner_score | 1950 | 1100 | 13.141 | 56.41 | 0.5571 | 6.4832 | 39.179 |
| model_combined_score | 1950 | 1053 | 12.579 | 54.0 | 0.5449 | 5.727 | 41.128 |
| model_trade_worthy_score | 1950 | 1020 | 12.185 | 52.308 | 0.5223 | 4.7793 | 41.744 |
| baseline_kumo_score | 1950 | 821 | 9.884 | 42.103 | 0.4214 | 2.0328 | 41.744 |
| baseline_rule_score | 1950 | 817 | 9.76 | 41.897 | 0.4196 | 1.7797 | 40.154 |
| baseline_kumo_rank_score | 1950 | 778 | 9.367 | 39.897 | 0.4046 | 1.4481 | 42.923 |

## Top-10 Runner Ranking

| score | selected_rows | hit_rows | recall_pct | precision_pct | ndcg_mean | avg_ret20_topk_pct | bad_trade_pct_topk |
| --- | --- | --- | --- | --- | --- | --- | --- |
| model_runner_score | 1950 | 1133 | 21.17 | 58.103 | 0.5917 | 6.4832 | 39.179 |
| model_combined_score | 1950 | 1091 | 20.385 | 55.949 | 0.5849 | 5.727 | 41.128 |
| model_trade_worthy_score | 1950 | 1016 | 18.984 | 52.103 | 0.5349 | 4.7793 | 41.744 |
| baseline_kumo_score | 1950 | 523 | 9.881 | 26.821 | 0.2572 | 2.0328 | 41.744 |
| baseline_kumo_rank_score | 1950 | 515 | 9.73 | 26.41 | 0.2681 | 1.4481 | 42.923 |
| baseline_rule_score | 1950 | 470 | 8.782 | 24.103 | 0.2367 | 1.7797 | 40.154 |

## Fold Summary

| target | fold | train_start | train_end | valid_start | valid_end | train_rows | valid_rows | train_positive_pct | coef_nonzero |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| trade_worthy | 1 | 2025-05-05 | 2025-06-30 | 2025-07-01 | 2025-08-25 | 3869 | 3869 | 45.697 | 30 |
| runner | 1 | 2025-05-05 | 2025-06-30 | 2025-07-01 | 2025-08-25 | 3869 | 3869 | 22.202 | 30 |
| trade_worthy | 2 | 2025-05-05 | 2025-08-25 | 2025-08-26 | 2025-10-20 | 7738 | 3870 | 41.096 | 30 |
| runner | 2 | 2025-05-05 | 2025-08-25 | 2025-08-26 | 2025-10-20 | 7738 | 3870 | 21.078 | 30 |
| trade_worthy | 3 | 2025-05-05 | 2025-10-20 | 2025-10-21 | 2025-12-15 | 11608 | 3851 | 40.377 | 30 |
| runner | 3 | 2025-05-05 | 2025-10-20 | 2025-10-21 | 2025-12-15 | 11608 | 3851 | 23.389 | 30 |
| trade_worthy | 4 | 2025-05-05 | 2025-12-15 | 2025-12-16 | 2026-02-11 | 15459 | 3898 | 41.536 | 31 |
| runner | 4 | 2025-05-05 | 2025-12-15 | 2025-12-16 | 2026-02-11 | 15459 | 3898 | 24.594 | 31 |
| trade_worthy | 5 | 2025-05-05 | 2026-02-11 | 2026-02-12 | 2026-04-09 | 19357 | 4098 | 43.829 | 32 |
| runner | 5 | 2025-05-05 | 2026-02-11 | 2026-02-12 | 2026-04-09 | 19357 | 4098 | 25.758 | 32 |

## Feature Diagnostics

| target | feature | coef_mean | coef_abs_mean | coef_std |
| --- | --- | --- | --- | --- |
| runner | kumo_close_log | -0.239729 | 0.239729 | 0.031305 |
| runner | gap_abs_rank_in_day | 0.221447 | 0.221447 | 0.016612 |
| runner | gap_abs_pctile_in_day | -0.220185 | 0.220185 | 0.016652 |
| runner | kumo_volume_log | 0.179063 | 0.179063 | 0.021384 |
| runner | gap_between_minus2_5 | -0.127758 | 0.127758 | 0.011754 |
| runner | kumo_gap_negative_abs | 0.085718 | 0.085718 | 0.013189 |
| runner | rank_le_20 | -0.061117 | 0.061117 | 0.027785 |
| runner | gap_lt_minus5 | 0.042842 | 0.042842 | 0.013974 |
| runner | kumo_gap_abs | 0.042555 | 0.042555 | 0.029621 |
| runner | rank_le_10 | -0.038249 | 0.038249 | 0.011489 |
| runner | relvol_pctile_in_day | -0.035406 | 0.035406 | 0.007337 |
| runner | relvol_rank_in_day | 0.034907 | 0.034907 | 0.007209 |
| runner | gap_rank_in_day | -0.030947 | 0.030947 | 0.009822 |
| runner | gap_pctile_in_day | 0.030641 | 0.030641 | 0.009315 |
| runner | kumo_gap_positive | 0.029463 | 0.029463 | 0.026193 |
| runner | kumo_dollar_vol_log | -0.025975 | 0.025975 | 0.014784 |
| runner | rank_le_50 | 0.005981 | 0.019442 | 0.022375 |
| runner | gap_gt_8 | 0.00604 | 0.018294 | 0.022921 |
| runner | kumo_gap_pct | 0.015862 | 0.017577 | 0.023267 |
| runner | dollar_vol_pctile_in_day | 0.002823 | 0.015689 | 0.018029 |
| runner | dollar_vol_rank_in_day | -0.003417 | 0.015178 | 0.017562 |
| runner | rank_rank_in_day | -0.011871 | 0.011871 | 0.008656 |
| runner | rank_pctile_in_day | 0.011146 | 0.011146 | 0.008543 |
| runner | kumo_rank_by_score | -0.010214 | 0.010214 | 0.008485 |
| runner | kumo_rank_inverse | 0.010214 | 0.010214 | 0.008485 |
| runner | score_rank_in_day | -0.004827 | 0.008697 | 0.008158 |
| runner | score_pctile_in_day | 0.004398 | 0.00846 | 0.008121 |
| runner | score_ge_8 | 0.003639 | 0.006957 | 0.006756 |
| runner | kumo_score | 0.003501 | 0.006662 | 0.006711 |
| runner | kumo_vol_ratio_20d | -0.001518 | 0.003604 | 0.004059 |

## Integration Notes

- `oof_predictions.csv.gz` contains date, symbol, labels, source flags, feature hash/version,
  baseline scores, and OOF model predictions.
- `model_artifact.json` is a compact linear ranker artifact for #468 conversion/testing; it is
  not wired into LEAN/QC yet.
- Feature names are guarded against George/source/future-label tokens.
