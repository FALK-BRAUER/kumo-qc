# Scanner Alternate Entry Replay #465

This report replays scanner opportunities with changed entry prices and post-entry paths.
It is still a research harness, not a LEAN/QC deployment artifact.

## Inputs

- Panel: `/Users/falk/projects/kumo-qc-465-alt-entry-replay/sweeps/reports/scanner_opportunity_panel_463/opportunity_panel.csv.gz`
- Parquet root: `/Users/falk/projects/kumo-trader/data/intraday`
- Candidate filter: `kumo_top100_or_george`

## Read

- Replayed candidate rows: `26124` opportunities x `4` assumptions = `104496` rows.
- Best replay assumption by average 20d close return: `pullback_1pct_reclaim`.
- Delayed entries use only post-entry same-day bars; first-hour and pullback entries are
  entered at the trigger bar close, while breakout uses a prior-session-high stop proxy.
- No-entry rows are kept in trigger-rate statistics but excluded from return percentages.

## Entry Assumption Summary

| entry_assumption | candidate_rows | triggered_rows | trigger_rate_pct | available_20d_rows | avg_ret_20d_close_pct | candidate_weighted_avg_ret_20d_pct | median_ret_20d_close_pct | runner_pct | bad_trade_pct | target4_before_stop2_pct | stop2_before_target4_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| pullback_1pct_reclaim | 26124 | 4708 | 18.022 | 4698 | 4.4367 | 0.7979 | 1.8174 | 37.654 | 41.89 | 32.865 | 62.431 |
| next_open | 26124 | 26111 | 99.95 | 26026 | 2.6916 | 2.6815 | 1.0368 | 21.382 | 37.789 | 31.315 | 58.945 |
| prior_session_high_breakout | 26124 | 14949 | 57.223 | 14895 | 2.5252 | 1.4398 | 0.842 | 20.879 | 38.342 | 30.641 | 59.644 |
| first_hour_confirm | 26124 | 13211 | 50.57 | 13169 | 2.4398 | 1.2299 | 0.9423 | 20.404 | 38.522 | 32.523 | 58.85 |

## Source Summary

| source_flag | entry_assumption | candidate_rows | triggered_rows | trigger_rate_pct | avg_ret_20d_close_pct | candidate_weighted_avg_ret_20d_pct | runner_pct | bad_trade_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| george_scanner_or_watchlist | first_hour_confirm | 712 | 362 | 50.843 | 1.2287 | 0.6212 | 23.056 | 43.889 |
| george_scanner_or_watchlist | next_open | 712 | 707 | 99.298 | 0.7153 | 0.7072 | 22.585 | 47.869 |
| george_scanner_or_watchlist | prior_session_high_breakout | 712 | 453 | 63.624 | 0.7147 | 0.4517 | 23.778 | 46.0 |
| george_scanner_or_watchlist | pullback_1pct_reclaim | 712 | 149 | 20.927 | -0.2619 | -0.0548 | 30.872 | 51.678 |
| kumo_scanner | pullback_1pct_reclaim | 25778 | 4631 | 17.965 | 4.5381 | 0.8135 | 37.827 | 41.636 |
| kumo_scanner | next_open | 25778 | 25766 | 99.953 | 2.7178 | 2.7078 | 21.333 | 37.64 |
| kumo_scanner | prior_session_high_breakout | 25778 | 14739 | 57.177 | 2.5541 | 1.4552 | 20.801 | 38.197 |
| kumo_scanner | first_hour_confirm | 25778 | 13048 | 50.617 | 2.4524 | 1.2374 | 20.304 | 38.441 |
| kumo_top100 | pullback_1pct_reclaim | 25500 | 4578 | 17.953 | 4.6005 | 0.8241 | 37.938 | 41.506 |
| kumo_top100 | next_open | 25500 | 25492 | 99.969 | 2.753 | 2.7432 | 21.381 | 37.54 |
| kumo_top100 | prior_session_high_breakout | 25500 | 14554 | 57.075 | 2.5874 | 1.4716 | 20.83 | 38.137 |
| kumo_top100 | first_hour_confirm | 25500 | 12900 | 50.588 | 2.487 | 1.2542 | 20.381 | 38.383 |

## Trigger Failures

| entry_assumption | label_trigger_status | label_trigger_reason | rows |
| --- | --- | --- | --- |
| first_hour_confirm | no_entry_trigger | first-hour close did not confirm above open | 12899 |
| first_hour_confirm | missing_entry_intraday | no regular-session intraday bars | 9 |
| first_hour_confirm | no_entry_date | scan date has no following parquet calendar day | 4 |
| first_hour_confirm | no_entry_trigger | no first-hour window | 1 |
| next_open | missing_entry_intraday | no regular-session intraday bars | 9 |
| next_open | no_entry_date | scan date has no following parquet calendar day | 4 |
| prior_session_high_breakout | no_entry_trigger | did not cross prior-session high | 11162 |
| prior_session_high_breakout | missing_entry_intraday | no regular-session intraday bars | 9 |
| prior_session_high_breakout | no_entry_date | scan date has no following parquet calendar day | 4 |
| pullback_1pct_reclaim | no_entry_trigger | no 1pct pullback reclaim | 21403 |
| pullback_1pct_reclaim | missing_entry_intraday | no regular-session intraday bars | 9 |
| pullback_1pct_reclaim | no_entry_date | scan date has no following parquet calendar day | 4 |

## Caveats

- Intrabar event ordering is unknown. Delayed triggers avoid counting pre-entry same-day bars.
- This pass uses the practical `kumo_top100_or_george` default subset unless configured
  otherwise; it is not a full 313k-row all-panel replay by default.
- Breakout is approximated as a prior-session-high stop entry, not full Ichimoku/cloud logic.
