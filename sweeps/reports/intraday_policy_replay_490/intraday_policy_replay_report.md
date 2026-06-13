# Intraday Policy Replay Economics #490

This is the correction pass after the #490 supervised baseline: it turns predicted actions into a same-day trade ledger.
Entry/exit prices are completed-bar checkpoint marks from the #491 intraday panel, not broker fill simulation.

## Inputs

- Panel: `/Users/falk/projects/kumo-qc-490-dual-head-policy/sweeps/reports/intraday_decision_panel_491/intraday_decision_panel.csv.gz`
- Model artifact: `/Users/falk/projects/kumo-qc-490-dual-head-policy/sweeps/reports/intraday_entry_exit_policy_490/model_artifact.json`
- Dual-head model artifact: `/Users/falk/projects/kumo-qc-490-dual-head-policy/sweeps/reports/intraday_entry_exit_policy_490_dual_head/model_artifact.json`
- Scan-time predictions: `/Users/falk/projects/kumo-qc-490-dual-head-policy/sweeps/reports/scan_time_scanner_ranker_492/oof_predictions.csv.gz`
- Parquet root: `/Users/falk/projects/kumo-trader/data/intraday`

## Summary

| variant | eligible_candidates | trades | entry_rate_pct | bad_entry_rate_pct | optimal_entry_rate_pct | runner_entry_rate_pct | sum_intraday_ret_pct | avg_intraday_ret_pct | win_rate_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| baseline_rules | 21512 | 13025 | 60.548 | 52.065 | 80.604 | 75.869 | -125.777 | -0.0097 | 47.255 |
| dual_head_policy | 21512 | 7142 | 33.2 | 30.096 | 50.928 | 72.695 | 335.525 | 0.047 | 40.437 |
| entry_policy_v2 | 21512 | 9535 | 44.324 | 36.914 | 64.817 | 76.121 | 175.6031 | 0.0184 | 42.202 |
| entry_policy_v3 | 21512 | 9562 | 44.45 | 37.057 | 64.94 | 76.322 | 171.8302 | 0.018 | 42.209 |
| model_policy | 21512 | 7469 | 34.72 | 31.483 | 53.661 | 72.544 | 190.9062 | 0.0256 | 41.05 |

## Result Read

- `model_policy` trades `7469` candidates versus baseline `13025`.
- `model_policy` bad-entry rate changes by `-20.582` points versus baseline.
- `model_policy` optimal-entry rate changes by `-26.943` points; runner-entry rate changes by `-3.325` points.
- `model_policy` same-day summed return changes by `316.6832` points; average trade return changes by `0.0353` points.
- `entry_policy_v2` trades `9535` candidates versus baseline `13025`.
- `entry_policy_v2` bad-entry rate changes by `-15.151` points versus baseline.
- `entry_policy_v2` optimal-entry rate changes by `-15.787` points; runner-entry rate changes by `0.252` points.
- `entry_policy_v2` same-day summed return changes by `301.3801` points; average trade return changes by `0.0281` points.
- `entry_policy_v3` trades `9562` candidates versus baseline `13025`.
- `entry_policy_v3` bad-entry rate changes by `-15.008` points versus baseline.
- `entry_policy_v3` optimal-entry rate changes by `-15.664` points; runner-entry rate changes by `0.453` points.
- `entry_policy_v3` same-day summed return changes by `297.6072` points; average trade return changes by `0.0277` points.
- `dual_head_policy` trades `7142` candidates versus baseline `13025`.
- `dual_head_policy` bad-entry rate changes by `-21.969` points versus baseline.
- `dual_head_policy` optimal-entry rate changes by `-29.676` points; runner-entry rate changes by `-3.174` points.
- `dual_head_policy` same-day summed return changes by `461.3020` points; average trade return changes by `0.0567` points.
- Promotion gate for `entry_policy_v2`: `iterate` (bad delta `-15.151`, optimal capture `64.817`, runner capture `76.121`).
- Promotion gate for `entry_policy_v3`: `iterate` (bad delta `-15.008`, optimal capture `64.94`, runner capture `76.322`).
- Promotion gate for `dual_head_policy`: `iterate` (bad delta `-21.969`, optimal capture `50.928`, runner capture `72.695`).
- Read: useful diagnostic signal, not a promotion result until replayed through local LEAN order semantics.

## Grouped Diagnostics

| variant | group_col | group_value | eligible_candidates | trades | entry_rate_pct | bad_entry_rate_pct | avg_intraday_ret_pct | win_rate_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| baseline_rules | scanner_source_bucket | both_george_and_kumo | 362 | 150 | 41.436 | 33.051 | 0.309 | 60.0 |
| baseline_rules | scanner_source_bucket | george_only | 345 | 0 | 0.0 | 0.0 | 0.0 | 0.0 |
| baseline_rules | scanner_source_bucket | kumo_only | 20332 | 12608 | 62.011 | 52.884 | -0.0138 | 47.002 |
| baseline_rules | scanner_source_bucket | kumo_with_george_video_context | 473 | 267 | 56.448 | 47.423 | 0.0074 | 52.06 |
| dual_head_policy | scanner_source_bucket | both_george_and_kumo | 362 | 99 | 27.348 | 33.051 | 0.454 | 45.455 |
| dual_head_policy | scanner_source_bucket | george_only | 345 | 115 | 33.333 | 38.843 | 0.1155 | 37.391 |
| dual_head_policy | scanner_source_bucket | kumo_only | 20332 | 6690 | 32.904 | 29.488 | 0.0445 | 40.433 |
| dual_head_policy | scanner_source_bucket | kumo_with_george_video_context | 473 | 238 | 50.317 | 50.515 | -0.085 | 39.916 |
| entry_policy_v2 | scanner_source_bucket | both_george_and_kumo | 362 | 98 | 27.072 | 34.746 | 0.3933 | 43.878 |
| entry_policy_v2 | scanner_source_bucket | george_only | 345 | 115 | 33.333 | 44.628 | 0.1732 | 42.609 |
| entry_policy_v2 | scanner_source_bucket | kumo_only | 20332 | 9058 | 44.55 | 36.464 | 0.0165 | 42.239 |
| entry_policy_v2 | scanner_source_bucket | kumo_with_george_video_context | 473 | 264 | 55.814 | 53.265 | -0.123 | 40.152 |
| entry_policy_v3 | scanner_source_bucket | both_george_and_kumo | 362 | 98 | 27.072 | 34.746 | 0.3933 | 43.878 |
| entry_policy_v3 | scanner_source_bucket | george_only | 345 | 115 | 33.333 | 44.628 | 0.1732 | 42.609 |
| entry_policy_v3 | scanner_source_bucket | kumo_only | 20332 | 9085 | 44.683 | 36.613 | 0.0161 | 42.245 |
| entry_policy_v3 | scanner_source_bucket | kumo_with_george_video_context | 473 | 264 | 55.814 | 53.265 | -0.123 | 40.152 |
| model_policy | scanner_source_bucket | both_george_and_kumo | 362 | 95 | 26.243 | 32.203 | 0.4116 | 44.211 |
| model_policy | scanner_source_bucket | george_only | 345 | 115 | 33.333 | 44.628 | 0.1732 | 42.609 |
| model_policy | scanner_source_bucket | kumo_only | 20332 | 6995 | 34.404 | 30.82 | 0.0235 | 41.015 |
| model_policy | scanner_source_bucket | kumo_with_george_video_context | 473 | 264 | 55.814 | 53.265 | -0.123 | 40.152 |
| baseline_rules | month | 2025-07 | 1497 | 949 | 63.393 | 57.222 | -0.0547 | 45.311 |
| baseline_rules | month | 2025-08 | 2100 | 1413 | 67.286 | 56.661 | 0.0925 | 51.097 |
| baseline_rules | month | 2025-09 | 2100 | 1345 | 64.048 | 52.305 | -0.0076 | 45.204 |
| baseline_rules | month | 2025-10 | 2299 | 1347 | 58.591 | 50.823 | -0.2592 | 39.866 |
| baseline_rules | month | 2025-11 | 1900 | 1349 | 71.0 | 61.475 | -0.1654 | 44.403 |
| baseline_rules | month | 2025-12 | 2198 | 1383 | 62.921 | 50.676 | 0.0104 | 43.89 |
| baseline_rules | month | 2026-01 | 1999 | 1255 | 62.781 | 48.87 | 0.0959 | 52.908 |
| baseline_rules | month | 2026-02 | 2011 | 1376 | 68.424 | 62.885 | 0.0375 | 53.052 |
| baseline_rules | month | 2026-03 | 2306 | 800 | 34.692 | 33.569 | -0.1185 | 42.25 |
| baseline_rules | month | 2026-04 | 2138 | 1348 | 63.05 | 57.759 | 0.1347 | 49.703 |
| baseline_rules | month | 2026-05 | 914 | 440 | 48.14 | 0.0 | 0.2325 | 54.545 |
| baseline_rules | month | 2026-06 | 50 | 20 | 40.0 | 0.0 | 0.1184 | 50.0 |
| dual_head_policy | month | 2025-07 | 1497 | 369 | 24.649 | 21.667 | -0.0029 | 43.36 |
| dual_head_policy | month | 2025-08 | 2100 | 606 | 28.857 | 23.52 | 0.1391 | 42.574 |
| dual_head_policy | month | 2025-09 | 2100 | 675 | 32.143 | 26.907 | 0.0973 | 39.407 |
| dual_head_policy | month | 2025-10 | 2299 | 747 | 32.492 | 32.595 | -0.3004 | 32.798 |
| dual_head_policy | month | 2025-11 | 1900 | 811 | 42.684 | 36.951 | -0.0258 | 39.334 |
| dual_head_policy | month | 2025-12 | 2198 | 561 | 25.523 | 21.241 | 0.0331 | 37.433 |
| dual_head_policy | month | 2026-01 | 1999 | 589 | 29.465 | 29.913 | -0.0455 | 37.861 |
| dual_head_policy | month | 2026-02 | 2011 | 830 | 41.273 | 38.205 | 0.0253 | 42.892 |
| dual_head_policy | month | 2026-03 | 2306 | 957 | 41.5 | 35.633 | 0.0384 | 37.827 |
| dual_head_policy | month | 2026-04 | 2138 | 735 | 34.378 | 20.69 | 0.3569 | 48.299 |
| dual_head_policy | month | 2026-05 | 914 | 258 | 28.228 | 0.0 | 0.4524 | 51.163 |
| dual_head_policy | month | 2026-06 | 50 | 4 | 8.0 | 0.0 | 0.8644 | 50.0 |
| entry_policy_v2 | month | 2025-07 | 1497 | 676 | 45.157 | 39.444 | -0.0216 | 41.124 |
| entry_policy_v2 | month | 2025-08 | 2100 | 961 | 45.762 | 32.072 | 0.0381 | 44.121 |
| entry_policy_v2 | month | 2025-09 | 2100 | 1047 | 49.857 | 35.96 | 0.0802 | 41.834 |
| entry_policy_v2 | month | 2025-10 | 2299 | 1080 | 46.977 | 41.283 | -0.1553 | 37.407 |
| entry_policy_v2 | month | 2025-11 | 1900 | 1008 | 53.053 | 43.165 | -0.0722 | 42.56 |
| entry_policy_v2 | month | 2025-12 | 2198 | 903 | 41.083 | 29.515 | -0.089 | 37.763 |
| entry_policy_v2 | month | 2026-01 | 1999 | 960 | 48.024 | 34.174 | 0.0197 | 47.5 |
| entry_policy_v2 | month | 2026-02 | 2011 | 956 | 47.539 | 43.269 | 0.0019 | 40.377 |
| entry_policy_v2 | month | 2026-03 | 2306 | 962 | 41.717 | 35.578 | 0.0623 | 43.139 |
| entry_policy_v2 | month | 2026-04 | 2138 | 721 | 33.723 | 19.828 | 0.2908 | 47.712 |
| entry_policy_v2 | month | 2026-05 | 914 | 258 | 28.228 | 0.0 | 0.391 | 42.248 |
| entry_policy_v2 | month | 2026-06 | 50 | 3 | 6.0 | 0.0 | -0.1872 | 0.0 |
| entry_policy_v3 | month | 2025-07 | 1497 | 681 | 45.491 | 39.815 | -0.0238 | 41.116 |
| entry_policy_v3 | month | 2025-08 | 2100 | 962 | 45.81 | 32.155 | 0.0403 | 44.387 |
| entry_policy_v3 | month | 2025-09 | 2100 | 1049 | 49.952 | 36.044 | 0.0778 | 41.754 |
| entry_policy_v3 | month | 2025-10 | 2299 | 1088 | 47.325 | 41.681 | -0.1569 | 37.408 |
| entry_policy_v3 | month | 2025-11 | 1900 | 1011 | 53.211 | 43.331 | -0.07 | 42.631 |
| entry_policy_v3 | month | 2025-12 | 2198 | 908 | 41.31 | 29.674 | -0.089 | 37.555 |
| entry_policy_v3 | month | 2026-01 | 1999 | 962 | 48.124 | 34.261 | 0.0186 | 47.505 |
| entry_policy_v3 | month | 2026-02 | 2011 | 957 | 47.588 | 43.269 | 0.0022 | 40.439 |
| entry_policy_v3 | month | 2026-03 | 2306 | 962 | 41.717 | 35.578 | 0.0623 | 43.139 |
| entry_policy_v3 | month | 2026-04 | 2138 | 721 | 33.723 | 19.828 | 0.2908 | 47.712 |
| entry_policy_v3 | month | 2026-05 | 914 | 258 | 28.228 | 0.0 | 0.391 | 42.248 |
| entry_policy_v3 | month | 2026-06 | 50 | 3 | 6.0 | 0.0 | -0.1872 | 0.0 |
| model_policy | month | 2025-07 | 1497 | 406 | 27.121 | 23.611 | -0.019 | 39.655 |
| model_policy | month | 2025-08 | 2100 | 665 | 31.667 | 25.987 | 0.0283 | 39.398 |
| model_policy | month | 2025-09 | 2100 | 727 | 34.619 | 29.17 | 0.1364 | 40.715 |
| model_policy | month | 2025-10 | 2299 | 862 | 37.495 | 36.116 | -0.1871 | 37.239 |
| model_policy | month | 2025-11 | 1900 | 879 | 46.263 | 40.017 | -0.0718 | 42.435 |
| model_policy | month | 2025-12 | 2198 | 614 | 27.934 | 23.15 | -0.0957 | 37.459 |
| model_policy | month | 2026-01 | 1999 | 619 | 30.965 | 29.565 | -0.0037 | 44.103 |
| model_policy | month | 2026-02 | 2011 | 834 | 41.472 | 37.628 | -0.0033 | 38.609 |
| model_policy | month | 2026-03 | 2306 | 953 | 41.327 | 35.144 | 0.0653 | 43.127 |
| model_policy | month | 2026-04 | 2138 | 667 | 31.197 | 19.54 | 0.3075 | 46.477 |
| model_policy | month | 2026-05 | 914 | 240 | 26.258 | 0.0 | 0.426 | 44.583 |
| model_policy | month | 2026-06 | 50 | 3 | 6.0 | 0.0 | -0.1872 | 0.0 |

## Read

- This evaluates economic behavior from decisions; it is still not QC Cloud or multi-day LEAN parity.
- The replay is same-day checkpoint based, so it can expose bad entry/exiting behavior but not full swing trade lifecycle.
- A promotable policy still needs local LEAN integration under #484 and George-fair labels under #489.
