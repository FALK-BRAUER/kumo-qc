# Scanner Exit Policy Research #466

This report simulates realization policies on the #464 scanner opportunity paths.
Metrics include closed realized return plus open mark-to-market at the 40-session horizon.

## Inputs

- Labels: `/Users/falk/projects/kumo-qc-466-exit-policy-research/sweeps/reports/scanner_opportunity_paths_464/opportunity_path_labels.csv.gz`
- Panel metadata: `/Users/falk/projects/kumo-qc-466-exit-policy-research/sweeps/reports/scanner_opportunity_panel_463/opportunity_panel.csv.gz`
- Parquet root: `/Users/falk/projects/kumo-trader/data/intraday`
- Candidate filter: `kumo_top100_or_george`

## Read

- Opportunities: `23455`
- Policy rows: `187640`
- `hold_40d_mtm` is the runner-preservation baseline, not a deployable exit.
- No simple tested exit beats the hold baseline on total 40-session equity; the candidates
  below are LEAN/QC sweep candidates, not promotion recommendations.
- Stop/target conflicts on one daily bar are treated conservatively as stop-first.
- Sector ETF weakness is measured only where the #463 panel has a sector ETF proxy.

## Policy Summary

| policy_id | available_rows | closed_pct | open_at_horizon_pct | avg_realized_ret_pct | avg_open_mtm_ret_pct | avg_total_equity_ret_40d_pct | median_total_equity_ret_40d_pct | win_rate_pct | bad_total_le_minus6_pct | runner_preserved_pct | runner_cut_early_pct | objective_score |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| hold_40d_mtm | 23455 | 0.0 | 100.0 | 0.0 | 4.7113 | 4.7113 | 1.8809 | 59.002 | 20.009 | 100.0 | 0.0 | 6.0167 |
| time10_lt2_hard6 | 23455 | 74.641 | 25.359 | -2.2519 | 4.1855 | 1.9336 | -0.9378 | 40.78 | 33.566 | 49.944 | 45.919 | 0.4057 |
| giveback35_after8 | 23455 | 75.762 | 24.238 | 0.3439 | 0.931 | 1.2749 | 0.2494 | 50.795 | 42.0 | 22.203 | 72.935 | -0.7324 |
| swinglow3_after8 | 23455 | 77.664 | 22.336 | 0.6196 | 0.4457 | 1.0653 | -0.244 | 48.804 | 42.302 | 23.571 | 69.86 | -0.7327 |
| sector_etf_weak3d | 9112 | 78.15 | 21.85 | -1.2441 | 1.7214 | 0.4773 | -2.9953 | 36.6 | 40.748 | 37.763 | 50.464 | -1.1101 |
| partial_t4_trail8 | 23455 | 78.312 | 21.688 | -0.1059 | 0.6772 | 0.5713 | 0.1792 | 51.814 | 0.0 | 9.789 | 72.307 | -1.7132 |
| fixed_t8_s4 | 23455 | 85.244 | 14.756 | 0.1874 | 0.2808 | 0.4683 | -4.0 | 40.989 | 0.0 | 4.669 | 91.547 | -2.4341 |
| fixed_t4_s2 | 23455 | 96.009 | 3.991 | 0.0708 | 0.0203 | 0.0911 | -2.0 | 35.677 | 0.0 | 0.0 | 100.0 | -3.0882 |

## Recommended LEAN/QC Sweep Candidates

These are the best deployable candidates by the current objective. They deliberately
trade off total equity against realization, drawdown, and runner retention.

| policy_id | avg_realized_ret_pct | avg_total_equity_ret_40d_pct | runner_preserved_pct | runner_cut_early_pct | avg_giveback_from_peak_pct | objective_score |
| --- | --- | --- | --- | --- | --- | --- |
| time10_lt2_hard6 | -2.2519 | 1.9336 | 49.944 | 45.919 | 7.3973 | 0.4057 |
| giveback35_after8 | 0.3439 | 1.2749 | 22.203 | 72.935 | 5.9655 | -0.7324 |
| swinglow3_after8 | 0.6196 | 1.0653 | 23.571 | 69.86 | 6.6244 | -0.7327 |

## Source Summary

| source_flag | policy_id | avg_realized_ret_pct | avg_total_equity_ret_40d_pct | runner_preserved_pct | runner_cut_early_pct | objective_score |
| --- | --- | --- | --- | --- | --- | --- |
| george_scanner_or_watchlist | hold_40d_mtm | 0.0 | 5.6407 | 100.0 | 0.0 | 6.7521 |
| george_scanner_or_watchlist | sector_etf_weak3d | -0.1288 | -0.1489 | 26.471 | 58.824 | -1.8323 |
| george_scanner_or_watchlist | time10_lt2_hard6 | -3.8167 | -0.031 | 40.404 | 53.535 | -2.6504 |
| george_scanner_or_watchlist | swinglow3_after8 | -0.7073 | -0.596 | 14.141 | 82.828 | -3.518 |
| george_scanner_or_watchlist | fixed_t4_s2 | -0.2848 | -0.2771 | 0.0 | 100.0 | -3.6126 |
| george_scanner_or_watchlist | partial_t4_trail8 | -0.8625 | -0.7237 | 2.02 | 86.869 | -3.9076 |
| george_scanner_or_watchlist | giveback35_after8 | -1.3198 | -0.8252 | 10.101 | 85.859 | -4.1292 |
| george_scanner_or_watchlist | fixed_t8_s4 | -1.1126 | -1.0524 | 3.03 | 95.96 | -4.6275 |
| kumo_scanner | hold_40d_mtm | 0.0 | 4.696 | 100.0 | 0.0 | 6.0029 |
| kumo_scanner | time10_lt2_hard6 | -2.2407 | 1.9433 | 50.033 | 45.871 | 0.4237 |
| kumo_scanner | giveback35_after8 | 0.3504 | 1.2807 | 22.302 | 72.854 | -0.7192 |
| kumo_scanner | swinglow3_after8 | 0.6245 | 1.0718 | 23.635 | 69.782 | -0.7202 |
| kumo_scanner | sector_etf_weak3d | -1.2441 | 0.4773 | 37.763 | 50.464 | -1.1101 |
| kumo_scanner | partial_t4_trail8 | -0.1018 | 0.5783 | 9.85 | 72.188 | -1.6996 |
| kumo_scanner | fixed_t8_s4 | 0.1935 | 0.4755 | 4.681 | 91.515 | -2.4232 |
| kumo_scanner | fixed_t4_s2 | 0.073 | 0.0934 | 0.0 | 100.0 | -3.0849 |
| kumo_top100 | hold_40d_mtm | 0.0 | 4.7097 | 100.0 | 0.0 | 6.0174 |
| kumo_top100 | time10_lt2_hard6 | -2.2354 | 1.958 | 50.057 | 45.853 | 0.4415 |
| kumo_top100 | swinglow3_after8 | 0.6353 | 1.0838 | 23.66 | 69.741 | -0.7025 |
| kumo_top100 | giveback35_after8 | 0.3594 | 1.2924 | 22.324 | 72.821 | -0.7027 |
| kumo_top100 | sector_etf_weak3d | -1.2393 | 0.4923 | 37.801 | 50.466 | -1.0925 |
| kumo_top100 | partial_t4_trail8 | -0.0985 | 0.5836 | 9.875 | 72.169 | -1.692 |
| kumo_top100 | fixed_t8_s4 | 0.2001 | 0.4828 | 4.693 | 91.494 | -2.4126 |
| kumo_top100 | fixed_t4_s2 | 0.0746 | 0.095 | 0.0 | 100.0 | -3.0827 |

## Exit Reasons

| policy_id | policy_status | exit_reason | rows |
| --- | --- | --- | --- |
| fixed_t4_s2 | closed | stop | 14149 |
| fixed_t4_s2 | closed | target | 7783 |
| fixed_t4_s2 | open_at_horizon | horizon_mtm | 936 |
| fixed_t4_s2 | closed | ambiguous_stop_first | 587 |
| fixed_t8_s4 | closed | stop | 12874 |
| fixed_t8_s4 | closed | target | 7031 |
| fixed_t8_s4 | open_at_horizon | horizon_mtm | 3461 |
| fixed_t8_s4 | closed | ambiguous_stop_first | 89 |
| giveback35_after8 | closed | hard_stop | 9851 |
| giveback35_after8 | closed | giveback_stop | 7919 |
| giveback35_after8 | open_at_horizon | horizon_mtm | 5685 |
| hold_40d_mtm | open_at_horizon | horizon_mtm | 23455 |
| partial_t4_trail8 | closed | hard_stop | 10071 |
| partial_t4_trail8 | closed | trail_stop | 8007 |
| partial_t4_trail8 | open_at_horizon | horizon_mtm | 5087 |
| partial_t4_trail8 | closed | ambiguous_stop_first | 290 |
| sector_etf_weak3d | missing_policy_data | missing_sector_etf | 14343 |
| sector_etf_weak3d | closed | hard_stop | 3713 |
| sector_etf_weak3d | closed | sector_etf_3d_weakness | 3408 |
| sector_etf_weak3d | open_at_horizon | horizon_mtm | 1991 |
| swinglow3_after8 | closed | hard_stop | 9922 |
| swinglow3_after8 | closed | swing_low_break | 8294 |
| swinglow3_after8 | open_at_horizon | horizon_mtm | 5239 |
| time10_lt2_hard6 | closed | time_stop_under_threshold | 9634 |
| time10_lt2_hard6 | closed | hard_stop | 7873 |
| time10_lt2_hard6 | open_at_horizon | horizon_mtm | 5948 |

## Deployability Notes

- Fixed target/stop, partial target + trail, giveback trail, swing-low trail, and time stop
  need only price bars and are deployable in local LEAN and QC Cloud.
- Sector ETF weakness requires an ETF proxy map to be present in the candidate metadata and
  the ETF symbols to be subscribed in LEAN/QC.
- A true cloud/Kijun trail should be tested in LEAN with indicator state; this raw-bar harness
  uses `swinglow3_after8` as the deployable price-only proxy.
