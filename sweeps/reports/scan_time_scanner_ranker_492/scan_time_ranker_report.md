# Scan-Time Scanner Ranker #492

This trains a first-pass scan-time ranker on the #482 optimal/bad trade buckets.
Validation is expanding-window by scan date. The model does not use George/source, future path,
entry, exit, return, MFE, MAE, or prior-model columns as features.

## Inputs

- Trade universe: `/Users/falk/projects/kumo-qc-492-scan-time-ranking/sweeps/reports/scanner_trade_universe_482/scanner_trade_universe.csv.gz`
- Scan-time panel metadata: `/Users/falk/projects/kumo-qc-492-scan-time-ranking/sweeps/reports/scanner_opportunity_panel_463/opportunity_panel.csv.gz`
- Candidate filter: `kumo_ranked`

## Coverage

- Rows: `25585`
- Dates: `255`
- OOF rows: `21285`
- Optimal rows: `6209`
- Bad rows: `15306`
- Watch rows: `4070`
- Feature version: `scan_time_scanner_ranker_492_v1`
- Feature hash: `5c8a52bd0f8314bbdf161a26c78a0c1449f1e1e3b9faf6cb9e3387937d295b4a`

## Decision

- Recommendation: `iterate`
- Best top-10 #492 precision point: `{'score': 'model_492_optimal_score', 'optimal_precision_pct': 26.105, 'bad_trade_pct_topk': 70.789, 'optimal_recall_pct': 10.038, 'avg_best_entry_ret20_topk_pct': 1.1048, 'avg_deployable_ret40_topk_pct': 6.2005}`
- Lowest-bad top-10 #492 point: `{'score': 'model_492_risk_avoidance_score', 'optimal_precision_pct': 20.526, 'bad_trade_pct_topk': 50.789, 'optimal_recall_pct': 7.893, 'avg_best_entry_ret20_topk_pct': 1.0916, 'avg_deployable_ret40_topk_pct': 4.6486}`
- Top-10 optimal model vs current Kumo-score delta: `{'k': 10, 'optimal_precision_delta_pct': 0.526, 'bad_trade_delta_pct': 2.631, 'avg_ret20_delta_pct': -1.1301, 'ndcg_delta': -0.0116}`
- Top-10 25% risk blend vs current Kumo-score delta: `{'k': 10, 'optimal_precision_delta_pct': -0.579, 'bad_trade_delta_pct': -0.684, 'avg_ret20_delta_pct': -1.7898, 'ndcg_delta': -0.0086}`
- Top-10 full risk blend vs current Kumo-rank delta: `{'k': 10, 'optimal_precision_delta_pct': -1.0, 'bad_trade_delta_pct': -13.474, 'avg_ret20_delta_pct': -0.9187, 'ndcg_delta': 0.0068}`
- Top-50 full risk blend vs current Kumo-rank delta: `{'k': 50, 'optimal_precision_delta_pct': -0.421, 'bad_trade_delta_pct': -5.326, 'avg_ret20_delta_pct': -1.1682, 'ndcg_delta': 0.0071}`

Interpretation: scan-time features reduce bad-trade concentration more reliably than they
increase top-10 optimal precision. This is useful for a risk filter, but not enough on its own
to explain George-style top-pick selection.

## Top-10 Ranking

| score | selected_rows | optimal_hits | optimal_recall_pct | optimal_precision_pct | bad_trade_pct_topk | watch_pct_topk | ndcg_mean | avg_best_entry_ret20_topk_pct | avg_deployable_ret40_topk_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| model_492_optimal_score | 1900 | 496 | 10.038 | 26.105 | 70.789 | 3.105 | 0.2647 | 1.1048 | 6.2005 |
| baseline_492_rule_score | 1900 | 491 | 9.937 | 25.842 | 67.737 | 6.421 | 0.2722 | 1.0833 | 5.1191 |
| baseline_492_kumo_score | 1900 | 486 | 9.836 | 25.579 | 68.158 | 6.263 | 0.2763 | 2.2349 | 5.9491 |
| model_492_blend_risk25_score | 1900 | 475 | 9.613 | 25.0 | 67.474 | 7.526 | 0.2677 | 0.4451 | 5.1883 |
| prior_467_runner_score | 1900 | 458 | 9.269 | 24.105 | 75.053 | 0.842 | 0.2417 | 6.4972 | 12.095 |
| model_492_blend_risk50_score | 1900 | 446 | 9.027 | 23.474 | 62.947 | 13.579 | 0.2574 | 0.3963 | 4.9137 |
| prior_467_combined_score | 1900 | 441 | 8.925 | 23.211 | 75.842 | 0.947 | 0.2362 | 5.7297 | 11.493 |
| prior_467_trade_worthy_score | 1900 | 439 | 8.885 | 23.105 | 75.737 | 1.158 | 0.2278 | 4.8443 | 10.3989 |
| model_492_blend_risk75_score | 1900 | 434 | 8.784 | 22.842 | 59.316 | 17.842 | 0.2533 | 0.3776 | 4.6048 |
| baseline_492_kumo_rank_score | 1900 | 430 | 8.703 | 22.632 | 70.632 | 6.737 | 0.2399 | 1.4593 | 6.0795 |
| model_492_combined_score | 1900 | 411 | 8.318 | 21.632 | 57.158 | 21.211 | 0.2467 | 0.5406 | 4.5989 |
| model_492_risk_avoidance_score | 1900 | 390 | 7.893 | 20.526 | 50.789 | 28.684 | 0.2323 | 1.0916 | 4.6486 |

## Top-50 Ranking

| score | selected_rows | optimal_hits | optimal_recall_pct | optimal_precision_pct | bad_trade_pct_topk | watch_pct_topk | ndcg_mean | avg_best_entry_ret20_topk_pct | avg_deployable_ret40_topk_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| prior_467_runner_score | 9500 | 2571 | 52.034 | 27.063 | 70.979 | 1.958 | 0.3871 | 3.3587 | 8.12 |
| prior_467_combined_score | 9500 | 2524 | 51.083 | 26.568 | 71.505 | 1.926 | 0.3807 | 3.216 | 7.9792 |
| prior_467_trade_worthy_score | 9500 | 2484 | 50.273 | 26.147 | 71.684 | 2.168 | 0.3717 | 3.1138 | 7.8118 |
| baseline_492_rule_score | 9500 | 2463 | 49.848 | 25.926 | 65.442 | 8.632 | 0.3932 | 1.8188 | 5.7331 |
| baseline_492_kumo_rank_score | 9500 | 2463 | 49.848 | 25.926 | 67.221 | 6.853 | 0.3833 | 2.4302 | 6.3571 |
| model_492_risk_avoidance_score | 9500 | 2459 | 49.767 | 25.884 | 59.874 | 14.242 | 0.3898 | 1.4669 | 5.6192 |
| model_492_combined_score | 9500 | 2423 | 49.039 | 25.505 | 61.895 | 12.6 | 0.3904 | 1.262 | 5.6879 |
| model_492_optimal_score | 9500 | 2422 | 49.018 | 25.495 | 68.779 | 5.726 | 0.3839 | 1.7146 | 6.3058 |
| model_492_blend_risk25_score | 9500 | 2421 | 48.998 | 25.484 | 65.463 | 9.053 | 0.3928 | 1.2797 | 5.8527 |
| model_492_blend_risk75_score | 9500 | 2406 | 48.695 | 25.326 | 62.705 | 11.968 | 0.3888 | 1.2476 | 5.675 |
| baseline_492_kumo_score | 9500 | 2399 | 48.553 | 25.253 | 66.158 | 8.589 | 0.3897 | 2.1283 | 5.863 |
| model_492_blend_risk50_score | 9500 | 2397 | 48.512 | 25.232 | 63.768 | 11.0 | 0.3897 | 1.1887 | 5.6867 |

## Promotion/Demotion Examples

| example_type | scan_date | symbol | trade_bucket | model_score_name | kumo_rank_by_score | baseline_rank | model_rank | rank_delta | best_entry_ret_20d_close_pct | best_deployable_total_equity_ret_40d_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| optimal_model_promoted_optimal | 2026-03-12 | FANG | optimal | model_492_optimal_score | 166.0 | 104 | 1 | 103 | 7.6043 | 8.988 |
| optimal_model_promoted_optimal | 2026-02-13 | SPG | optimal | model_492_optimal_score | 240.0 | 103 | 1 | 102 | -3.9422 | 4.0 |
| optimal_model_promoted_optimal | 2026-04-07 | FANG | optimal | model_492_optimal_score | 214.0 | 102 | 1 | 101 | 16.3784 | 18.0322 |
| optimal_model_promoted_optimal | 2026-02-18 | CVX | optimal | model_492_optimal_score | 284.0 | 105 | 6 | 99 | 7.1887 | 8.0 |
| optimal_model_promoted_optimal | 2026-02-09 | IAG | optimal | model_492_optimal_score | 374.0 | 107 | 8 | 99 | 4.232 | 4.0 |
| optimal_model_promoted_optimal | 2025-08-20 | JPM | optimal | model_492_optimal_score | 100.0 | 100 | 1 | 99 | 7.2652 | 8.0 |
| optimal_model_promoted_optimal | 2025-12-22 | MRK | optimal | model_492_optimal_score | 100.0 | 100 | 1 | 99 | 4.4185 | 16.8133 |
| optimal_model_promoted_optimal | 2026-01-21 | BBD | optimal | model_492_optimal_score | 99.0 | 99 | 1 | 98 | 8.2228 | 8.0 |
| optimal_model_promoted_optimal | 2025-10-31 | WELL | optimal | model_492_optimal_score | 100.0 | 100 | 2 | 98 | 13.4164 | 12.4266 |
| optimal_model_promoted_optimal | 2025-10-22 | CYBR | optimal | model_492_optimal_score | 100.0 | 100 | 2 | 98 | -5.2375 | 4.0 |
| optimal_model_promoted_optimal | 2025-12-10 | STX | optimal | model_492_optimal_score | 99.0 | 99 | 1 | 98 | 3.6035 | 4.0 |
| optimal_model_promoted_optimal | 2025-09-30 | ASND | optimal | model_492_optimal_score | 98.0 | 98 | 1 | 97 | 3.0865 | 8.0 |
| optimal_model_promoted_optimal | 2025-11-04 | SEE | optimal | model_492_optimal_score | 100.0 | 100 | 3 | 97 | 18.7308 | 19.9329 |
| optimal_model_promoted_optimal | 2025-09-25 | SOXX | optimal | model_492_optimal_score | 100.0 | 100 | 4 | 96 | 8.7216 | 8.0 |
| optimal_model_promoted_optimal | 2025-12-08 | SATS | optimal | model_492_optimal_score | 98.0 | 98 | 2 | 96 | 27.6426 | 25.5854 |
| optimal_model_promoted_optimal | 2026-01-15 | AME | optimal | model_492_optimal_score | 97.0 | 97 | 1 | 96 | 6.8949 | 8.0 |
| optimal_model_promoted_optimal | 2025-12-17 | CRS | optimal | model_492_optimal_score | 97.0 | 97 | 1 | 96 | 4.4496 | 5.6348 |
| optimal_model_promoted_optimal | 2026-01-29 | AME | optimal | model_492_optimal_score | 98.0 | 98 | 3 | 95 | 5.8042 | 4.0 |
| optimal_model_promoted_optimal | 2025-11-28 | SGOL | optimal | model_492_optimal_score | 100.0 | 100 | 5 | 95 | 2.001 | 26.8281 |
| optimal_model_promoted_optimal | 2026-02-19 | MCD | optimal | model_492_optimal_score | 165.0 | 101 | 6 | 95 | -5.6184 | 4.0 |
| optimal_model_promoted_optimal | 2025-09-25 | MRVL | optimal | model_492_optimal_score | 98.0 | 98 | 3 | 95 | 0.3638 | 8.0 |
| optimal_model_promoted_optimal | 2026-03-18 | BKR | optimal | model_492_optimal_score | 97.0 | 97 | 2 | 95 | 5.6301 | 12.6198 |
| optimal_model_promoted_optimal | 2025-11-12 | XLV | optimal | model_492_optimal_score | 100.0 | 100 | 5 | 95 | 1.224 | 4.0 |
| optimal_model_promoted_optimal | 2026-02-05 | WAB | optimal | model_492_optimal_score | 96.0 | 96 | 1 | 95 | 1.0532 | 8.0 |
| optimal_model_promoted_optimal | 2025-09-19 | PRIM | optimal | model_492_optimal_score | 99.0 | 99 | 5 | 94 | 6.1792 | 8.0 |
| optimal_model_promoted_optimal | 2026-04-09 | DLR | optimal | model_492_optimal_score | 96.0 | 96 | 2 | 94 | 3.4908 | 8.0 |
| optimal_model_promoted_optimal | 2025-12-10 | GM | optimal | model_492_optimal_score | 98.0 | 98 | 4 | 94 | 3.0624 | 8.0 |
| optimal_model_promoted_optimal | 2025-11-12 | LLY | optimal | model_492_optimal_score | 97.0 | 97 | 3 | 94 | -0.0698 | 8.0 |
| optimal_model_promoted_optimal | 2025-10-14 | WELL | optimal | model_492_optimal_score | 95.0 | 95 | 1 | 94 | 13.7929 | 13.0592 |
| optimal_model_promoted_optimal | 2025-09-25 | SMH | optimal | model_492_optimal_score | 99.0 | 99 | 5 | 94 | 7.6203 | 8.0 |

## Monthly Stability

| month | score | selected_rows | optimal_precision_pct | bad_trade_pct | watch_pct | avg_best_entry_ret20_pct |
| --- | --- | --- | --- | --- | --- | --- |
| 2025-07 | baseline_492_kumo_rank_score | 180 | 12.222 | 78.889 | 8.889 | -0.2888 |
| 2025-08 | baseline_492_kumo_rank_score | 210 | 20.0 | 61.429 | 18.571 | 2.0877 |
| 2025-09 | baseline_492_kumo_rank_score | 210 | 35.714 | 52.381 | 11.905 | 3.7636 |
| 2025-10 | baseline_492_kumo_rank_score | 230 | 8.696 | 82.174 | 9.13 | -5.1912 |
| 2025-11 | baseline_492_kumo_rank_score | 190 | 27.368 | 68.947 | 3.684 | -0.2095 |
| 2025-12 | baseline_492_kumo_rank_score | 220 | 30.909 | 65.909 | 3.182 | 9.1097 |
| 2026-01 | baseline_492_kumo_rank_score | 200 | 31.5 | 63.5 | 5.0 | 0.1369 |
| 2026-02 | baseline_492_kumo_rank_score | 190 | 14.737 | 85.263 | 0.0 | -3.4281 |
| 2026-03 | baseline_492_kumo_rank_score | 220 | 15.455 | 84.545 | 0.0 | 1.5059 |
| 2026-04 | baseline_492_kumo_rank_score | 210 | 12.381 | 14.762 | 72.857 | 17.305 |
| 2026-05 | baseline_492_kumo_rank_score | 60 | 0.0 | 0.0 | 100.0 | nan |
| 2025-07 | baseline_492_rule_score | 180 | 12.778 | 78.889 | 8.333 | -0.1284 |
| 2025-08 | baseline_492_rule_score | 210 | 22.857 | 61.905 | 15.238 | 1.8639 |
| 2025-09 | baseline_492_rule_score | 210 | 32.857 | 56.19 | 10.952 | 2.8715 |
| 2025-10 | baseline_492_rule_score | 230 | 19.565 | 72.174 | 8.261 | -0.8906 |
| 2025-11 | baseline_492_rule_score | 190 | 28.947 | 65.263 | 5.789 | -0.2738 |
| 2025-12 | baseline_492_rule_score | 220 | 36.818 | 57.727 | 5.455 | 3.3171 |
| 2026-01 | baseline_492_rule_score | 200 | 44.5 | 52.0 | 3.5 | 3.0621 |
| 2026-02 | baseline_492_rule_score | 190 | 18.421 | 81.579 | 0.0 | -4.3234 |
| 2026-03 | baseline_492_rule_score | 220 | 10.909 | 89.091 | 0.0 | 0.5891 |
| 2026-04 | baseline_492_rule_score | 210 | 10.476 | 16.667 | 72.857 | 10.3436 |
| 2026-05 | baseline_492_rule_score | 60 | 0.0 | 0.0 | 100.0 | nan |
| 2025-07 | prior_467_combined_score | 180 | 20.556 | 78.333 | 1.111 | -0.7556 |
| 2025-08 | prior_467_combined_score | 210 | 29.048 | 69.048 | 1.905 | 15.1166 |
| 2025-09 | prior_467_combined_score | 210 | 29.048 | 70.476 | 0.476 | 16.8275 |
| 2025-10 | prior_467_combined_score | 230 | 7.826 | 90.435 | 1.739 | -13.6708 |
| 2025-11 | prior_467_combined_score | 190 | 28.947 | 69.474 | 1.579 | 4.2797 |
| 2025-12 | prior_467_combined_score | 220 | 27.727 | 70.909 | 1.364 | 16.559 |
| 2026-01 | prior_467_combined_score | 200 | 22.0 | 78.0 | 0.0 | -1.7925 |
| 2026-02 | prior_467_combined_score | 190 | 17.368 | 82.105 | 0.526 | -2.69 |
| 2026-03 | prior_467_combined_score | 220 | 19.545 | 80.455 | 0.0 | 9.7898 |
| 2026-04 | prior_467_combined_score | 60 | 46.667 | 53.333 | 0.0 | 28.4031 |
| 2025-07 | model_492_combined_score | 180 | 13.889 | 68.889 | 17.222 | 0.7446 |
| 2025-08 | model_492_combined_score | 210 | 23.333 | 47.619 | 29.048 | 1.8951 |
| 2025-09 | model_492_combined_score | 210 | 23.81 | 38.095 | 38.095 | 1.5753 |
| 2025-10 | model_492_combined_score | 230 | 6.522 | 66.957 | 26.522 | -2.7412 |
| 2025-11 | model_492_combined_score | 190 | 27.895 | 50.526 | 21.579 | 1.4014 |
| 2025-12 | model_492_combined_score | 220 | 21.818 | 48.636 | 29.545 | 2.7691 |
| 2026-01 | model_492_combined_score | 200 | 37.0 | 39.5 | 23.5 | 2.1697 |
| 2026-02 | model_492_combined_score | 190 | 17.368 | 74.737 | 7.895 | -3.5574 |
| 2026-03 | model_492_combined_score | 220 | 21.364 | 78.182 | 0.455 | -1.5637 |
| 2026-04 | model_492_combined_score | 210 | 8.095 | 20.0 | 71.905 | 7.0777 |
| 2026-05 | model_492_combined_score | 60 | 0.0 | 0.0 | 100.0 | nan |

## Fold Summary

| target | fold | train_start | train_end | valid_start | valid_end | train_rows | valid_rows | train_positive_pct | coef_nonzero |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| optimal | 1 | 2025-05-05 | 2025-07-07 | 2025-07-08 | 2025-09-05 | 4300 | 4300 | 29.488 | 34 |
| bad_risk | 1 | 2025-05-05 | 2025-07-07 | 2025-07-08 | 2025-09-05 | 4300 | 4300 | 60.86 | 34 |
| optimal | 2 | 2025-05-05 | 2025-09-05 | 2025-09-08 | 2025-11-05 | 8600 | 4300 | 27.407 | 34 |
| bad_risk | 2 | 2025-05-05 | 2025-09-05 | 2025-09-08 | 2025-11-05 | 8600 | 4300 | 61.826 | 34 |
| optimal | 3 | 2025-05-05 | 2025-11-05 | 2025-11-06 | 2026-01-07 | 12900 | 4200 | 25.124 | 34 |
| bad_risk | 3 | 2025-05-05 | 2025-11-05 | 2025-11-06 | 2026-01-07 | 12900 | 4200 | 64.047 | 34 |
| optimal | 4 | 2025-05-05 | 2026-01-07 | 2026-01-08 | 2026-03-10 | 17100 | 4264 | 26.813 | 35 |
| bad_risk | 4 | 2025-05-05 | 2026-01-07 | 2026-01-08 | 2026-03-10 | 17100 | 4264 | 62.708 | 35 |
| optimal | 5 | 2025-05-05 | 2026-03-10 | 2026-03-11 | 2026-05-08 | 21364 | 4221 | 26.357 | 36 |
| bad_risk | 5 | 2025-05-05 | 2026-03-10 | 2026-03-11 | 2026-05-08 | 21364 | 4221 | 64.618 | 36 |

## Feature Diagnostics

| target | feature | coef_mean | coef_abs_mean | coef_std |
| --- | --- | --- | --- | --- |
| bad_risk | gap_abs_pct_in_day | 0.220178 | 0.220178 | 0.039617 |
| bad_risk | sector_cat_financials | 0.13111 | 0.13111 | 0.00925 |
| bad_risk | kumo_gap_negative_abs | 0.074953 | 0.074953 | 0.011981 |
| bad_risk | sector_cat_energy | 0.051758 | 0.067364 | 0.047521 |
| bad_risk | sector_cat_healthcare | 0.062569 | 0.062569 | 0.055997 |
| bad_risk | sector_cat_materials | 0.051931 | 0.051931 | 0.006226 |
| bad_risk | relvol_pct_in_day | 0.03176 | 0.047709 | 0.039971 |
| bad_risk | sector_cat_utilities | 0.04019 | 0.040684 | 0.025754 |
| bad_risk | sector_cat_industrials | 0.040125 | 0.040125 | 0.01464 |
| bad_risk | gap_pct_in_day | -0.037122 | 0.037122 | 0.019987 |
| bad_risk | rank_le_10 | -0.014422 | 0.030162 | 0.035408 |
| bad_risk | rank_le_20 | 0.029225 | 0.029225 | 0.020696 |
| bad_risk | rank_le_50 | 0.022147 | 0.022147 | 0.011686 |
| bad_risk | dollar_vol_pct_in_day | -0.005136 | 0.02181 | 0.023478 |
| bad_risk | kumo_rank_pct_in_day | -0.019767 | 0.019767 | 0.005267 |
| bad_risk | kumo_gap_abs | 0.019401 | 0.019401 | 0.007221 |
| bad_risk | kumo_rank_by_score | -0.018908 | 0.018908 | 0.006396 |
| bad_risk | kumo_rank_inverse | 0.018908 | 0.018908 | 0.006396 |
| bad_risk | score_x_rank_pct | 0.018645 | 0.018645 | 0.006137 |
| bad_risk | kumo_close_log | 0.004365 | 0.018348 | 0.021125 |
| bad_risk | gap_lt_minus5 | 0.009613 | 0.018325 | 0.018642 |
| bad_risk | relvol_x_gap_ok | -0.017412 | 0.017412 | 0.01012 |
| bad_risk | sector_cat_real_estate | 0.012156 | 0.017323 | 0.023081 |
| bad_risk | kumo_dollar_vol_log | 0.001068 | 0.014048 | 0.014379 |
| bad_risk | gap_between_minus2_5 | -0.013113 | 0.01371 | 0.009827 |
| bad_risk | score_x_gap_ok | -0.01166 | 0.013463 | 0.009952 |
| bad_risk | gap_gt_8 | 0.002494 | 0.011995 | 0.015988 |
| bad_risk | kumo_gap_positive | 0.009249 | 0.010758 | 0.007881 |
| bad_risk | kumo_volume_log | -0.000106 | 0.007954 | 0.008483 |
| bad_risk | score_pct_in_day | -0.007495 | 0.007758 | 0.008918 |
| bad_risk | score_ge_8 | 0.00543 | 0.007271 | 0.008681 |
| bad_risk | kumo_score | 0.00641 | 0.00641 | 0.007718 |
| bad_risk | kumo_gap_pct | -0.000779 | 0.006375 | 0.009021 |
| bad_risk | score_ge_7 | 0.003638 | 0.004354 | 0.008201 |
| bad_risk | kumo_vol_ratio_20d | 0.001906 | 0.003639 | 0.004229 |
| bad_risk | is_kumo_top_n | 0.000585 | 0.000585 | 0.00117 |
| bad_risk | has_company_sector | 0.0 | 0.0 | 0.0 |
| bad_risk | has_company_industry | 0.0 | 0.0 | 0.0 |
| bad_risk | has_sector_proxy | 0.0 | 0.0 | 0.0 |
| bad_risk | sector_cat_communication_services | 0.0 | 0.0 | 0.0 |

## Notes

- `prior_467_*` scores are comparison baselines only; they are not model features.
- `daily_rank_examples.csv` shows rows the #492 model moves into or out of top 10 vs Kumo rank.
- This is scan-time only. Intraday entry/exit policy remains #491/#490.
