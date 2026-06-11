# Scanner Source Diagnostics #485

This report compares George and Kumo scanner source buckets using the #482 trade universe.

## Inputs

- Trade universe: `/Users/falk/projects/kumo-qc-485-source-diagnostics/sweeps/reports/scanner_trade_universe_482/scanner_trade_universe.csv.gz`

## Coverage

- Opportunities: `26124`
- Dates: `275`
- Symbols: `1547`

## Trade Buckets

| trade_bucket | rows |
| --- | --- |
| bad | 15427 |
| optimal | 6238 |
| watch | 4459 |

## Source Outcome Summary

| source_bucket | opportunities | dates | symbols | triggered_rows | optimal_rows | bad_rows | watch_rows | runner_rows | bad_entry_rows | avg_best_entry_ret20_pct | avg_best_entry_mfe20_pct | avg_best_entry_mae20_pct | avg_best_deployable_exit_total40_pct | avg_model_combined_score | median_kumo_rank | median_george_rank | trigger_rate_pct | optimal_pct | bad_pct | watch_pct | runner_pct | bad_entry_pct | share_of_all_opportunities_pct | share_of_all_optimal_pct | share_of_all_bad_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| kumo_only | 24817 | 255 | 1409 | 22591 | 6005 | 14820 | 3992 | 4596 | 8539 | 2.3392 | 9.3423 | -6.601 | 6.3757 | -0.0006 | 51.0 |  | 91.03 | 24.197 | 59.717 | 16.086 | 18.52 | 34.408 | 94.997 | 96.265 | 96.065 |
| kumo_with_george_video_context | 595 | 136 | 193 | 562 | 174 | 368 | 53 | 115 | 200 | 2.9891 | 8.9343 | -5.859 | 7.7988 | 0.0564 | 37.0 | 13.0 | 94.454 | 29.244 | 61.849 | 8.908 | 19.328 | 33.613 | 2.278 | 2.789 | 2.385 |
| both_george_and_kumo | 366 | 60 | 232 | 149 | 30 | 118 | 218 | 31 | 79 | 0.9335 | 8.9836 | -8.6287 | 4.2028 | 0.1685 | 100.0 | 5.0 | 40.71 | 8.197 | 32.24 | 59.563 | 8.47 | 21.585 | 1.401 | 0.481 | 0.765 |
| george_only | 346 | 49 | 238 | 153 | 29 | 121 | 196 | 42 | 72 | 0.2784 | 9.4082 | -10.2069 | 5.897 | 0.0569 |  | 7.0 | 44.22 | 8.382 | 34.971 | 56.647 | 12.139 | 20.809 | 1.324 | 0.465 | 0.784 |

## Denominator Diagnostics

| source_bucket | opportunities | missing_kumo_rank_rows | missing_kumo_score_rows | missing_model_score_rows | missing_deployable_exit_rows | strict_entry_rows | missing_kumo_rank_pct | missing_kumo_score_pct | missing_model_score_pct | missing_deployable_exit_pct | strict_entry_pct | diagnostic_note |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| kumo_only | 24817 | 0 | 0 | 6002 | 2226 | 17651 | 0.0 | 0.0 | 24.185 | 8.97 | 71.125 | Primary Kumo-centered denominator. |
| kumo_with_george_video_context | 595 | 0 | 0 | 126 | 33 | 420 | 0.0 | 0.0 | 21.176 | 5.546 | 70.588 | Kumo row with video context only; not George scanner/watchlist evidence. |
| both_george_and_kumo | 366 | 193 | 0 | 217 | 217 | 120 | 52.732 | 0.0 | 59.29 | 59.29 | 32.787 | Partially comparable, but many rows are targeted/George rows without full Kumo rank fields. |
| george_only | 346 | 346 | 346 | 193 | 193 | 121 | 100.0 | 100.0 | 55.78 | 55.78 | 34.971 | Not source-comparable: Kumo rank/score/model fields are structurally absent for George-only rows. |

## Top Reason Codes

| source_bucket | trade_bucket | reason_code | rows | bucket_trade_rows | pct_of_bucket_trade |
| --- | --- | --- | --- | --- | --- |
| kumo_only | bad | realistic_entry_triggered | 14820 | 14820 | 100.0 |
| kumo_only | bad | stop_before_target4_2 | 13283 | 14820 | 89.629 |
| kumo_only | bad | best_entry_bad_trade | 8539 | 14820 | 57.618 |
| kumo_only | bad | mae20_le_minus8 | 6154 | 14820 | 41.525 |
| kumo_only | optimal | normal_winner | 6005 | 6005 | 100.0 |
| kumo_only | optimal | realistic_entry_triggered | 6005 | 6005 | 100.0 |
| kumo_only | optimal | target4_before_stop2 | 5825 | 6005 | 97.002 |
| kumo_only | optimal | ret20_ge_4 | 3901 | 6005 | 64.963 |
| kumo_only | optimal | mfe20_ge_8 | 3533 | 6005 | 58.834 |
| kumo_only | watch | no_realistic_entry_triggered | 2226 | 3992 | 55.762 |
| kumo_only | optimal | runner_candidate | 2040 | 6005 | 33.972 |
| kumo_only | watch | realistic_entry_triggered | 1766 | 3992 | 44.238 |
| kumo_with_george_video_context | bad | realistic_entry_triggered | 368 | 368 | 100.0 |
| kumo_with_george_video_context | bad | stop_before_target4_2 | 344 | 368 | 93.478 |
| both_george_and_kumo | watch | no_realistic_entry_triggered | 217 | 218 | 99.541 |
| kumo_with_george_video_context | bad | best_entry_bad_trade | 200 | 368 | 54.348 |
| george_only | watch | no_realistic_entry_triggered | 193 | 196 | 98.469 |
| kumo_with_george_video_context | optimal | normal_winner | 174 | 174 | 100.0 |
| kumo_with_george_video_context | optimal | realistic_entry_triggered | 174 | 174 | 100.0 |
| kumo_with_george_video_context | optimal | target4_before_stop2 | 172 | 174 | 98.851 |

## Miss / Trap Counts

- Missed optimal trades: `6208`
- High-risk false positives: `15427`
- Daily examples: `975`

## Key Findings

- Kumo-only rows provide `96.265`% of all optimal rows and `96.065`% of all bad rows inside this Kumo-centered artifact.
- The George-only optimal share (`0.465`%) is not a fair George-quality metric because the route/feature denominator is not source-balanced.
- Shared George+Kumo rows have `59.563`% watch rows and only `8.197`% optimal rows.
- Kumo rows with George video context have `29.244`% optimal rows, but video context is not scanner/watchlist evidence.

## Actionable Interpretation

- Do not use this report to conclude that George-only rows are weak; use it to show the current artifact is Kumo-centered.
- Before #483 trains a source-comparison model, rebuild a fair route panel for George scanner/watchlist rows with the same entry/exit label coverage as Kumo rows.
- If we proceed directly to #483 without that rebuild, scope it explicitly as a Kumo ranking/risk-filter model, not a George-vs-Kumo source model.
- Shared overlap is not sufficient as a buy signal in the current artifact; many shared rows never get a realistic entry or still classify as bad trades.
- George video-only context remains separated from George scanner/watchlist evidence.

## Caveats

- This analysis does not retrain or relabel; it consumes #482 labels.
- Exit-policy metrics inherit the #482 caveat that deployable exits are anchored to next-open path labels.
- Source-share percentages are not source-quality percentages because #482 inherits the #465 `kumo_top100_or_george` candidate filter and Kumo-ranker feature surface.
