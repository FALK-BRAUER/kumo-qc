# Scanner Opportunity Path Labels #464

This report adds future path labels to the #463 label-free opportunity panel.
The first entry assumption is `next_regular_open`; additional trigger research belongs to #465.

## Inputs

- Panel: `/Users/falk/projects/kumo-qc-464-path-labels/sweeps/reports/scanner_opportunity_panel_463/opportunity_panel.csv.gz`
- Parquet root: `/Users/falk/projects/kumo-trader/data/intraday`

## Label Output

- Rows: `313332`
- Dates: `321`
- Symbols: `3796`
- Available 20d rows: `312076`

## Coverage

| path_status | rows | symbols | dates | pct |
| --- | --- | --- | --- | --- |
| available_full_40d | 298006 | 3547 | 270 | 95.109 |
| truncated_calendar | 13275 | 868 | 48 | 4.237 |
| partial_symbol_missing | 1512 | 153 | 217 | 0.483 |
| missing_entry_bar | 484 | 244 | 115 | 0.154 |
| no_entry_date | 33 | 33 | 1 | 0.011 |
| truncated_calendar_and_symbol_missing | 22 | 1 | 22 | 0.007 |

## Source Outcome Summary

| source_flag | rows | available_rows | runner_pct | normal_winner_pct | bad_trade_pct | extreme_path_pct | avg_ret_20d_close_pct | avg_mfe_20d_pct | avg_mae_20d_pct | t4_s2_target_before_stop_pct | t4_s2_stop_before_target_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| kumo_scanner | 310389 | 310263 | 19.282 | 50.533 | 38.781 | 0.356 | 2.004 | 9.4641 | -6.7942 | 31.566 | 58.746 |
| kumo_top_n | 25500 | 25492 | 21.32 | 50.902 | 37.529 | 0.302 | 2.753 | 9.6819 | -6.4848 | 31.273 | 58.862 |
| george_scanner_positive | 511 | 507 | 22.091 | 48.718 | 45.562 | 0.197 | 0.8253 | 9.3212 | -7.7741 | 29.98 | 59.369 |
| george_watchlist | 201 | 200 | 23.5 | 53.5 | 53.0 | 0.0 | 0.438 | 11.1534 | -7.7451 | 32.0 | 60.0 |
| george_video_mention | 5629 | 5238 | 22.661 | 54.906 | 39.92 | 0.325 | 2.339 | 10.2756 | -7.4283 | 33.047 | 62.237 |

## Label Semantics

- `label_ret_*d_close_pct` is close return from next regular open to the horizon close.
- `label_mfe_*d_pct` and `label_mae_*d_pct` use regular-session daily highs/lows.
- Target/stop ordering uses daily high/low order by day. If both levels are touched on the
  same daily bar, the outcome is `ambiguous_same_day`.
- Runner, normal-winner, bad-trade, and extreme-path percentages are explicit flags and may
  overlap; `label_outcome_20d` is the compact priority bucket.
- `label_outcome_20d` is a compact research label, not a trading rule.
