# Intraday Decision Panel #491

This artifact converts ranked scanner candidates into as-of decision rows for later
entry/exit policy training. Features are computed from completed 5-minute bars at or
before each checkpoint; oracle route fields are carried as labels only.

## Inputs

- Universe: `/Users/falk/projects/kumo-qc-491-intraday-decision-panel/sweeps/reports/scanner_trade_universe_482/scanner_trade_universe.csv.gz`
- Entry labels: `/Users/falk/projects/kumo-qc-491-intraday-decision-panel/sweeps/reports/scanner_entry_replay_465/alternate_entry_labels.csv.gz`
- Exit labels: `/Users/falk/projects/kumo-qc-491-intraday-decision-panel/sweeps/reports/scanner_exit_policies_466/exit_policy_labels.csv.gz`
- Parquet root: `/Users/falk/projects/kumo-trader/data/intraday`
- Candidate filter: `kumo_or_george`

## Output

- Rows: `297317`
- Entry-decision rows: `156744`
- Position-management rows: `140573`
- Opportunities: `26124`
- Dates: `275`
- Feature version: `intraday_decision_panel_491_v1`

## Label Summary

| row_type | action_label | rows | dates | symbols | pct |
| --- | --- | --- | --- | --- | --- |
| entry_decision | avoid_bad_entry | 92562 | 234 | 1252 | 59.053 |
| entry_decision | enter_now | 37294 | 234 | 838 | 23.793 |
| entry_decision | wait | 26864 | 260 | 692 | 17.139 |
| entry_decision | missing_intraday | 24 | 1 | 4 | 0.015 |
| position_management | scratch_or_reduce | 71686 | 234 | 1252 | 50.996 |
| position_management | hold_winner | 35988 | 234 | 838 | 25.601 |
| position_management | exit_loser | 20859 | 234 | 1053 | 14.839 |
| position_management | hold_or_wait | 10734 | 213 | 295 | 7.636 |
| position_management | do_not_cut_runner | 1134 | 178 | 194 | 0.807 |
| position_management | protect_profit | 172 | 61 | 86 | 0.122 |

## Checkpoint Summary

| row_type | checkpoint | rows | intraday_available_pct | avg_bars_completed |
| --- | --- | --- | --- | --- |
| entry_decision | open | 26124 | 99.95 | 0.0 |
| entry_decision | after_15m | 26124 | 99.95 | 2.99 |
| entry_decision | after_30m | 26124 | 99.95 | 5.978 |
| entry_decision | first_hour | 26124 | 99.95 | 11.958 |
| entry_decision | midday | 26124 | 99.95 | 29.874 |
| entry_decision | close | 26124 | 99.95 | 77.238 |
| position_management | open | 23414 | 100.0 | 0.0 |
| position_management | after_15m | 23419 | 100.0 | 2.992 |
| position_management | after_30m | 23420 | 100.0 | 5.981 |
| position_management | first_hour | 23428 | 100.0 | 11.962 |
| position_management | midday | 23437 | 100.0 | 29.884 |
| position_management | close | 23455 | 100.0 | 77.22 |

## Coverage

| row_type | feature_group | rows | available_rows | missing_rows | available_pct |
| --- | --- | --- | --- | --- | --- |
| entry_decision | etf_intraday_available | 156744 | 63510 | 93234 | 40.518 |
| entry_decision | etf_last_15m_available | 156744 | 52925 | 103819 | 33.765 |
| entry_decision | etf_last_hour_available | 156744 | 31755 | 124989 | 20.259 |
| entry_decision | ichimoku_15m_available | 156744 | 0 | 156744 | 0.0 |
| entry_decision | ichimoku_hour_available | 156744 | 0 | 156744 | 0.0 |
| entry_decision | intraday_available | 156744 | 156666 | 78 | 99.95 |
| entry_decision | last_15m_available | 156744 | 130335 | 26409 | 83.152 |
| entry_decision | last_hour_available | 156744 | 77856 | 78888 | 49.671 |
| position_management | etf_intraday_available | 140573 | 54621 | 85952 | 38.856 |
| position_management | etf_last_15m_available | 140573 | 45521 | 95052 | 32.382 |
| position_management | etf_last_hour_available | 140573 | 27319 | 113254 | 19.434 |
| position_management | ichimoku_15m_available | 140573 | 0 | 140573 | 0.0 |
| position_management | ichimoku_hour_available | 140573 | 0 | 140573 | 0.0 |
| position_management | intraday_available | 140573 | 140573 | 0 | 100.0 |
| position_management | last_15m_available | 140573 | 116959 | 23614 | 83.202 |
| position_management | last_hour_available | 140573 | 69868 | 70705 | 49.702 |

## Notes

- `entry_decision` labels are `enter_now`, `wait`, `avoid_bad_entry`, or `missing_intraday`.
- `position_management` labels are first-pass oracle supervision derived from #482 route buckets
  and the as-of position state. They are intentionally separated from entry rows.
- 15m/hour features are last completed 3-bar and 12-bar windows from the 5-minute feed.
- Ichimoku flags are exposed as coverage columns; historical 15m/hour warmup is not computed
  in this first #491 slice.
