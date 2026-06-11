# Scanner Trade Universe #482

This report synthesizes George/Kumo scanner opportunities with realistic-entry replay,
exit-policy outcomes, and ranker scores.

## Inputs

- Panel: `/Users/falk/projects/kumo-qc-482-scanner-trade-universe/sweeps/reports/scanner_opportunity_panel_463/opportunity_panel.csv.gz`
- Entry labels: `/Users/falk/projects/kumo-qc-482-scanner-trade-universe/sweeps/reports/scanner_entry_replay_465/alternate_entry_labels.csv.gz`
- Exit labels: `/Users/falk/projects/kumo-qc-482-scanner-trade-universe/sweeps/reports/scanner_exit_policies_466/exit_policy_labels.csv.gz`
- Ranker predictions: `/Users/falk/projects/kumo-qc-482-scanner-trade-universe/sweeps/reports/scanner_opportunity_ranker_467/oof_predictions.csv.gz`

## Coverage

- Opportunities: `26124`
- Dates: `275`
- Symbols: `1547`
- Classification version: `scanner_trade_universe_v1`

## Trade Buckets

| trade_bucket | rows |
| --- | --- |
| bad | 15427 |
| optimal | 6238 |
| watch | 4459 |

## Source Summary

| source_bucket | opportunities | triggered_rows | optimal_rows | bad_rows | watch_rows | avg_best_entry_ret20_pct | avg_best_deployable_exit_total40_pct | trigger_rate_pct | optimal_pct | bad_pct | watch_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| kumo_only | 24817 | 22591 | 6005 | 14820 | 3992 | 2.3392 | 6.3757 | 91.03 | 24.197 | 59.717 | 16.086 |
| kumo_with_george_video_context | 595 | 562 | 174 | 368 | 53 | 2.9891 | 7.7988 | 94.454 | 29.244 | 61.849 | 8.908 |
| both_george_and_kumo | 366 | 149 | 30 | 118 | 218 | 0.9335 | 4.2028 | 40.71 | 8.197 | 32.24 | 59.563 |
| george_only | 346 | 153 | 29 | 121 | 196 | 0.2784 | 5.897 | 44.22 | 8.382 | 34.971 | 56.647 |

## Caveats

- `best_entry_*` is selected from #465 realistic entry replay assumptions.
- `best_deployable_exit_*` currently comes from #466 exit-policy labels, which were built
  on next-open path labels. The artifact marks this with `exit_policy_entry_assumption`.
- `optimal` and `bad` are research labels, not a live trading rule.
