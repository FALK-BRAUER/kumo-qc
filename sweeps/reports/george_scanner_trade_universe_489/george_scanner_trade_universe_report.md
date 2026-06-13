# George Scanner Trade Universe #489

This report builds a George-first scanner/watchlist trade universe from #463 evidence,
joins #465 realistic-entry labels and #466 deployable exit-policy outcomes, and applies
the #482 optimal/bad/watch classification logic.

George video mentions are context only. They are not treated as George scanner evidence.
Kumo rank, score, and model fields are not required and are not used for classification.

## Inputs

- Panel: `/Users/falk/projects/kumo-qc-489-george-scanner-trade-universe/sweeps/reports/scanner_opportunity_panel_463/opportunity_panel.csv.gz`
- Entry labels: `/Users/falk/projects/kumo-qc-489-george-scanner-trade-universe/sweeps/reports/scanner_entry_replay_465/alternate_entry_labels.csv.gz`
- Exit labels: `/Users/falk/projects/kumo-qc-489-george-scanner-trade-universe/sweeps/reports/scanner_exit_policies_466/exit_policy_labels.csv.gz`
- Ranker/model predictions: not joined for #489.

## Coverage

- Opportunities: `712`
- Dates: `75`
- Symbols: `400`
- Classification version: `george_scanner_trade_universe_v1`

## Trade Buckets

| trade_bucket | rows |
| --- | --- |
| watch | 414 |
| bad | 239 |
| optimal | 59 |

## Source Buckets

| source_bucket | rows |
| --- | --- |
| both_george_and_kumo | 366 |
| george_only | 290 |
| george_with_video_context | 56 |

## Source Summary

| source_bucket | opportunities | dates | symbols | triggered_rows | deployable_exit_rows | optimal_rows | bad_rows | watch_rows | video_context_rows | missing_kumo_rank_rows | missing_kumo_score_rows | avg_best_entry_ret20_pct | avg_best_entry_mae20_pct | avg_best_deployable_exit_total40_pct | trigger_rate_pct | deployable_exit_coverage_pct | optimal_pct | bad_pct | watch_pct | missing_kumo_rank_pct | missing_kumo_score_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| both_george_and_kumo | 366 | 60 | 232 | 149 | 149 | 30 | 118 | 218 | 8 | 193 | 0 | 0.9335 | -8.6287 | 4.2028 | 40.71 | 40.71 | 8.197 | 32.24 | 59.563 | 52.732 | 0.0 |
| george_only | 290 | 49 | 199 | 153 | 153 | 29 | 121 | 140 | 0 | 290 | 290 | 0.2784 | -10.2069 | 5.897 | 52.759 | 52.759 | 10.0 | 41.724 | 48.276 | 100.0 | 100.0 |
| george_with_video_context | 56 | 2 | 54 | 0 | 0 | 0 | 0 | 56 | 56 | 56 | 56 |  |  |  | 0.0 | 0.0 | 0.0 | 0.0 | 100.0 | 100.0 | 100.0 |

## Coverage Gaps

| category | opportunities | included_in_universe | trainable_scanner_evidence | with_entry_labels | with_exit_policy_labels | in_universe | note |
| --- | --- | --- | --- | --- | --- | --- | --- |
| video_only_context_excluded | 5565 | False | False | 595 | 562 | 0 | George video mention without scanner/watchlist evidence; excluded from trainable universe. |
| candidate_missing_entry_labels | 0 | False | False | 0 | 0 | 0 | George candidates lacking #465 realistic-entry labels. |
| candidate_missing_exit_policy_labels | 410 | False | False | 410 | 0 | 410 | George candidates lacking #466 exit-policy labels. |
| universe_no_realistic_entry | 410 | True | True | 410 | 0 | 410 | Included candidates with no realistic entry trigger; labeled watch. |

## Top Reason Codes

| source_bucket | trade_bucket | reason_code | rows | bucket_trade_rows | pct_of_bucket_trade |
| --- | --- | --- | --- | --- | --- |
| both_george_and_kumo | watch | no_realistic_entry_triggered | 217 | 218 | 99.541 |
| george_only | watch | no_realistic_entry_triggered | 137 | 140 | 97.857 |
| george_only | bad | realistic_entry_triggered | 121 | 121 | 100.0 |
| both_george_and_kumo | bad | realistic_entry_triggered | 118 | 118 | 100.0 |
| george_only | bad | stop_before_target4_2 | 104 | 121 | 85.95 |
| both_george_and_kumo | bad | stop_before_target4_2 | 104 | 118 | 88.136 |
| both_george_and_kumo | bad | best_entry_bad_trade | 79 | 118 | 66.949 |
| george_only | bad | mae20_le_minus8 | 78 | 121 | 64.463 |
| george_only | bad | best_entry_bad_trade | 72 | 121 | 59.504 |
| both_george_and_kumo | bad | mae20_le_minus8 | 61 | 118 | 51.695 |
| george_with_video_context | watch | no_realistic_entry_triggered | 56 | 56 | 100.0 |
| both_george_and_kumo | optimal | realistic_entry_triggered | 30 | 30 | 100.0 |
| both_george_and_kumo | optimal | normal_winner | 30 | 30 | 100.0 |
| george_only | optimal | normal_winner | 29 | 29 | 100.0 |
| george_only | optimal | realistic_entry_triggered | 29 | 29 | 100.0 |
| both_george_and_kumo | optimal | target4_before_stop2 | 29 | 30 | 96.667 |
| george_only | optimal | target4_before_stop2 | 28 | 29 | 96.552 |
| george_only | optimal | mfe20_ge_8 | 23 | 29 | 79.31 |
| george_only | optimal | ret20_ge_4 | 19 | 29 | 65.517 |
| both_george_and_kumo | optimal | mfe20_ge_8 | 18 | 30 | 60.0 |

## #483 Training Readiness

- Optimal rows: `59`
- Bad rows: `239`
- Threshold used: `100` per class
- Status: `insufficient_labeled_examples`
- Conclusion: #483 should stay blocked for George-only training under the pragmatic >= 100 rows per class threshold.

## Caveats

- `best_entry_*` is selected from #465 realistic entry replay assumptions.
- `best_deployable_exit_*` comes from #466 exit-policy labels and preserves the same
  `exit_policy_entry_assumption` meaning used by #482.
- `optimal` and `bad` are research labels, not live trading rules.
- Future path, entry, and exit columns are labels only; they must not be used as model features.
