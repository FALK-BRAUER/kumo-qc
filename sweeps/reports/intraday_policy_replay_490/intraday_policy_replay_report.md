# Intraday Policy Replay Economics #490

This is the correction pass after the #490 supervised baseline: it turns predicted actions into a same-day trade ledger.
Entry/exit prices are completed-bar checkpoint marks from the #491 intraday panel, not broker fill simulation.

## Inputs

- Panel: `/Users/falk/projects/kumo-qc-490-replay-shaped-policy/sweeps/reports/intraday_decision_panel_491/intraday_decision_panel.csv.gz`
- Model artifact: `/Users/falk/projects/kumo-qc-490-replay-shaped-policy/sweeps/reports/intraday_entry_exit_policy_490/model_artifact.json`
- Parquet root: `/Users/falk/projects/kumo-trader/data/intraday`

## Summary

| variant | eligible_candidates | trades | entry_rate_pct | bad_entry_rate_pct | optimal_entry_rate_pct | runner_entry_rate_pct | sum_intraday_ret_pct | avg_intraday_ret_pct | win_rate_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| baseline_rules | 21512 | 13025 | 60.548 | 52.065 | 80.604 | 75.869 | -125.777 | -0.0097 | 47.255 |
| model_policy | 21512 | 7469 | 34.72 | 31.483 | 53.661 | 72.544 | 190.9062 | 0.0256 | 41.05 |

## Result Read

- Model trades `7469` candidates versus baseline `13025`.
- Bad-entry rate changes by `-20.582` points versus baseline.
- Optimal-entry rate changes by `-26.943` points; runner-entry rate changes by `-3.325` points.
- Same-day summed return changes by `316.6832` points; average trade return changes by `0.0353` points.
- Read: useful diagnostic signal, not a promotion result until replayed through local LEAN order semantics.

## Grouped Diagnostics

| variant | group_col | group_value | eligible_candidates | trades | entry_rate_pct | bad_entry_rate_pct | avg_intraday_ret_pct | win_rate_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| baseline_rules | scanner_source_bucket | both_george_and_kumo | 362 | 150 | 41.436 | 33.051 | 0.309 | 60.0 |
| baseline_rules | scanner_source_bucket | george_only | 345 | 0 | 0.0 | 0.0 | 0.0 | 0.0 |
| baseline_rules | scanner_source_bucket | kumo_only | 20332 | 12608 | 62.011 | 52.884 | -0.0138 | 47.002 |
| baseline_rules | scanner_source_bucket | kumo_with_george_video_context | 473 | 267 | 56.448 | 47.423 | 0.0074 | 52.06 |
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
