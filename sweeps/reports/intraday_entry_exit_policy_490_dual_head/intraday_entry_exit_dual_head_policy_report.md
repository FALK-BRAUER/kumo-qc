# Intraday Entry/Exit Dual-Head Policy #490

This trains separate bad-risk and winner-preservation heads instead of forcing entry labels into one softmax class race.
The artifact is consumed by the #490 replay script as `dual_head_policy`.

## Inputs

- Panel: `/Users/falk/projects/kumo-qc-490-dual-head-policy/sweeps/reports/intraday_decision_panel_491/intraday_decision_panel.csv.gz`

## Summary Metrics

| head_name | rows | positive_class | positive_rate_pct | accuracy_pct | macro_f1 | positive_precision_pct | positive_recall_pct |
| --- | --- | --- | --- | --- | --- | --- | --- |
| entry_bad_risk_head | 129120 | bad_entry_risk | 58.611 | 61.317 | 0.5889 | 65.176 | 73.012 |
| entry_ready_head | 129120 | entry_ready | 22.701 | 74.72 | 0.5755 | 40.588 | 24.496 |
| entry_winner_preservation_head | 129120 | winner_preserve | 23.815 | 74.122 | 0.5896 | 43.302 | 28.003 |
| management_exit_risk_head | 117372 | exit_risk | 66.701 | 67.652 | 0.6437 | 76.988 | 73.461 |
| management_runner_preservation_head | 117372 | runner_preserve | 25.744 | 72.812 | 0.5795 | 45.122 | 25.947 |

## Action Metrics

| head_name | action | support | predicted | precision_pct | recall_pct | f1 |
| --- | --- | --- | --- | --- | --- | --- |
| entry_bad_risk_head | bad_entry_risk | 75678 | 84777 | 65.176 | 73.012 | 0.6887 |
| entry_bad_risk_head | not_bad_entry_risk | 53442 | 44343 | 53.941 | 44.757 | 0.4892 |
| entry_ready_head | entry_ready | 29311 | 17690 | 40.588 | 24.496 | 0.3055 |
| entry_ready_head | not_entry_ready | 99809 | 111430 | 80.139 | 89.47 | 0.8455 |
| entry_winner_preservation_head | not_winner_preserve | 98370 | 109234 | 79.733 | 88.538 | 0.839 |
| entry_winner_preservation_head | winner_preserve | 30750 | 19886 | 43.302 | 28.003 | 0.3401 |
| management_exit_risk_head | exit_risk | 78288 | 74701 | 76.988 | 73.461 | 0.7518 |
| management_exit_risk_head | not_exit_risk | 39084 | 42671 | 51.309 | 56.018 | 0.5356 |
| management_runner_preservation_head | not_runner_preserve | 87156 | 99997 | 77.623 | 89.06 | 0.8295 |
| management_runner_preservation_head | runner_preserve | 30216 | 17375 | 45.122 | 25.947 | 0.3295 |

## Source/Month/Fold Diagnostics

| head_name | group_col | group_value | rows | accuracy_pct |
| --- | --- | --- | --- | --- |
| entry_bad_risk_head | scanner_source_bucket | both_george_and_kumo | 2172 | 32.182 |
| entry_bad_risk_head | scanner_source_bucket | george_only | 2076 | 32.563 |
| entry_bad_risk_head | scanner_source_bucket | kumo_only | 122034 | 62.4 |
| entry_bad_risk_head | scanner_source_bucket | kumo_with_george_video_context | 2838 | 58.104 |
| entry_bad_risk_head | month | 2025-07 | 9000 | 62.111 |
| entry_bad_risk_head | month | 2025-08 | 12600 | 67.571 |
| entry_bad_risk_head | month | 2025-09 | 12600 | 66.825 |
| entry_bad_risk_head | month | 2025-10 | 13800 | 66.464 |
| entry_bad_risk_head | month | 2025-11 | 11400 | 66.07 |
| entry_bad_risk_head | month | 2025-12 | 13200 | 65.644 |
| entry_bad_risk_head | month | 2026-01 | 12000 | 68.725 |
| entry_bad_risk_head | month | 2026-02 | 12066 | 64.86 |
| entry_bad_risk_head | month | 2026-03 | 13836 | 73.786 |
| entry_bad_risk_head | month | 2026-04 | 12828 | 32.975 |
| entry_bad_risk_head | month | 2026-05 | 5490 | 13.916 |
| entry_bad_risk_head | month | 2026-06 | 300 | 1.333 |
| entry_bad_risk_head | fold_490_dual | 1.0 | 27600 | 65.779 |
| entry_bad_risk_head | fold_490_dual | 2.0 | 27600 | 66.138 |
| entry_bad_risk_head | fold_490_dual | 3.0 | 27600 | 67.04 |
| entry_bad_risk_head | fold_490_dual | 4.0 | 28332 | 69.755 |
| entry_bad_risk_head | fold_490_dual | 5.0 | 17988 | 25.006 |
| entry_winner_preservation_head | scanner_source_bucket | both_george_and_kumo | 2172 | 85.589 |
| entry_winner_preservation_head | scanner_source_bucket | george_only | 2076 | 86.079 |
| entry_winner_preservation_head | scanner_source_bucket | kumo_only | 122034 | 73.95 |
| entry_winner_preservation_head | scanner_source_bucket | kumo_with_george_video_context | 2838 | 63.989 |
| entry_winner_preservation_head | month | 2025-07 | 9000 | 78.867 |
| entry_winner_preservation_head | month | 2025-08 | 12600 | 74.238 |
| entry_winner_preservation_head | month | 2025-09 | 12600 | 72.373 |
| entry_winner_preservation_head | month | 2025-10 | 13800 | 77.362 |
| entry_winner_preservation_head | month | 2025-11 | 11400 | 69.868 |
| entry_winner_preservation_head | month | 2025-12 | 13200 | 67.826 |
| entry_winner_preservation_head | month | 2026-01 | 12000 | 62.475 |
| entry_winner_preservation_head | month | 2026-02 | 12066 | 73.032 |
| entry_winner_preservation_head | month | 2026-03 | 13836 | 77.942 |
| entry_winner_preservation_head | month | 2026-04 | 12828 | 81.096 |
| entry_winner_preservation_head | month | 2026-05 | 5490 | 86.703 |
| entry_winner_preservation_head | month | 2026-06 | 300 | 95.0 |
| entry_winner_preservation_head | fold_490_dual | 1.0 | 27600 | 74.62 |
| entry_winner_preservation_head | fold_490_dual | 2.0 | 27600 | 74.822 |
| entry_winner_preservation_head | fold_490_dual | 3.0 | 27600 | 65.877 |
| entry_winner_preservation_head | fold_490_dual | 4.0 | 28332 | 75.208 |
| entry_winner_preservation_head | fold_490_dual | 5.0 | 17988 | 83.222 |
| entry_ready_head | scanner_source_bucket | both_george_and_kumo | 2172 | 88.49 |
| entry_ready_head | scanner_source_bucket | george_only | 2076 | 86.85 |
| entry_ready_head | scanner_source_bucket | kumo_only | 122034 | 74.514 |
| entry_ready_head | scanner_source_bucket | kumo_with_george_video_context | 2838 | 64.2 |
| entry_ready_head | month | 2025-07 | 9000 | 79.411 |
| entry_ready_head | month | 2025-08 | 12600 | 74.635 |
| entry_ready_head | month | 2025-09 | 12600 | 72.754 |
| entry_ready_head | month | 2025-10 | 13800 | 78.536 |
| entry_ready_head | month | 2025-11 | 11400 | 69.851 |
| entry_ready_head | month | 2025-12 | 13200 | 67.924 |
| entry_ready_head | month | 2026-01 | 12000 | 63.033 |
| entry_ready_head | month | 2026-02 | 12066 | 73.148 |
| entry_ready_head | month | 2026-03 | 13836 | 77.436 |
| entry_ready_head | month | 2026-04 | 12828 | 83.209 |
| entry_ready_head | month | 2026-05 | 5490 | 89.654 |
| entry_ready_head | month | 2026-06 | 300 | 98.0 |
| entry_ready_head | fold_490_dual | 1.0 | 27600 | 74.957 |
| entry_ready_head | fold_490_dual | 2.0 | 27600 | 75.562 |
| entry_ready_head | fold_490_dual | 3.0 | 27600 | 66.199 |
| entry_ready_head | fold_490_dual | 4.0 | 28332 | 74.996 |
| entry_ready_head | fold_490_dual | 5.0 | 17988 | 85.707 |
| management_exit_risk_head | scanner_source_bucket | both_george_and_kumo | 894 | 77.069 |
| management_exit_risk_head | scanner_source_bucket | george_only | 918 | 77.233 |
| management_exit_risk_head | scanner_source_bucket | kumo_only | 112746 | 67.602 |
| management_exit_risk_head | scanner_source_bucket | kumo_with_george_video_context | 2814 | 63.539 |
| management_exit_risk_head | month | 2025-07 | 13049 | 64.296 |
| management_exit_risk_head | month | 2025-08 | 12533 | 67.757 |
| management_exit_risk_head | month | 2025-09 | 12446 | 67.178 |
| management_exit_risk_head | month | 2025-10 | 13682 | 68.565 |
| management_exit_risk_head | month | 2025-11 | 11258 | 66.948 |
| management_exit_risk_head | month | 2025-12 | 13021 | 66.255 |
| management_exit_risk_head | month | 2026-01 | 11905 | 69.341 |
| management_exit_risk_head | month | 2026-02 | 12035 | 65.077 |
| management_exit_risk_head | month | 2026-03 | 13769 | 72.569 |
| management_exit_risk_head | month | 2026-04 | 3674 | 69.08 |
| management_exit_risk_head | fold_490_dual | 1.0 | 23185 | 65.862 |
| management_exit_risk_head | fold_490_dual | 2.0 | 23171 | 68.094 |
| management_exit_risk_head | fold_490_dual | 3.0 | 23079 | 66.415 |

## Fold Summary

| head_name | fold | train_start | train_end | valid_start | valid_end | train_rows | valid_rows |
| --- | --- | --- | --- | --- | --- | --- | --- |
| entry_bad_risk_head | 1 | 2025-05-05 | 2025-07-10 | 2025-07-11 | 2025-09-15 | 27600 | 27600 |
| entry_bad_risk_head | 2 | 2025-05-05 | 2025-09-15 | 2025-09-16 | 2025-11-18 | 55200 | 27600 |
| entry_bad_risk_head | 3 | 2025-05-05 | 2025-11-18 | 2025-11-19 | 2026-01-27 | 82800 | 27600 |
| entry_bad_risk_head | 4 | 2025-05-05 | 2026-01-27 | 2026-01-28 | 2026-04-01 | 110400 | 28332 |
| entry_bad_risk_head | 5 | 2025-05-05 | 2026-04-01 | 2026-04-02 | 2026-06-04 | 138732 | 17988 |
| entry_winner_preservation_head | 1 | 2025-05-05 | 2025-07-10 | 2025-07-11 | 2025-09-15 | 27600 | 27600 |
| entry_winner_preservation_head | 2 | 2025-05-05 | 2025-09-15 | 2025-09-16 | 2025-11-18 | 55200 | 27600 |
| entry_winner_preservation_head | 3 | 2025-05-05 | 2025-11-18 | 2025-11-19 | 2026-01-27 | 82800 | 27600 |
| entry_winner_preservation_head | 4 | 2025-05-05 | 2026-01-27 | 2026-01-28 | 2026-04-01 | 110400 | 28332 |
| entry_winner_preservation_head | 5 | 2025-05-05 | 2026-04-01 | 2026-04-02 | 2026-06-04 | 138732 | 17988 |
| entry_ready_head | 1 | 2025-05-05 | 2025-07-10 | 2025-07-11 | 2025-09-15 | 27600 | 27600 |
| entry_ready_head | 2 | 2025-05-05 | 2025-09-15 | 2025-09-16 | 2025-11-18 | 55200 | 27600 |
| entry_ready_head | 3 | 2025-05-05 | 2025-11-18 | 2025-11-19 | 2026-01-27 | 82800 | 27600 |
| entry_ready_head | 4 | 2025-05-05 | 2026-01-27 | 2026-01-28 | 2026-04-01 | 110400 | 28332 |
| entry_ready_head | 5 | 2025-05-05 | 2026-04-01 | 2026-04-02 | 2026-06-04 | 138732 | 17988 |
| management_exit_risk_head | 1 | 2025-05-05 | 2025-06-30 | 2025-07-01 | 2025-08-25 | 23201 | 23185 |
| management_exit_risk_head | 2 | 2025-05-05 | 2025-08-25 | 2025-08-26 | 2025-10-20 | 46386 | 23171 |
| management_exit_risk_head | 3 | 2025-05-05 | 2025-10-20 | 2025-10-21 | 2025-12-15 | 69557 | 23079 |
| management_exit_risk_head | 4 | 2025-05-05 | 2025-12-15 | 2025-12-16 | 2026-02-11 | 92636 | 23372 |
| management_exit_risk_head | 5 | 2025-05-05 | 2026-02-11 | 2026-02-12 | 2026-04-09 | 116008 | 24565 |
| management_runner_preservation_head | 1 | 2025-05-05 | 2025-06-30 | 2025-07-01 | 2025-08-25 | 23201 | 23185 |
| management_runner_preservation_head | 2 | 2025-05-05 | 2025-08-25 | 2025-08-26 | 2025-10-20 | 46386 | 23171 |
| management_runner_preservation_head | 3 | 2025-05-05 | 2025-10-20 | 2025-10-21 | 2025-12-15 | 69557 | 23079 |
| management_runner_preservation_head | 4 | 2025-05-05 | 2025-12-15 | 2025-12-16 | 2026-02-11 | 92636 | 23372 |
| management_runner_preservation_head | 5 | 2025-05-05 | 2026-02-11 | 2026-02-12 | 2026-04-09 | 116008 | 24565 |

## Feature Diagnostics

| policy_name | action | feature | coef_mean | coef_abs_mean |
| --- | --- | --- | --- | --- |
| entry_bad_risk_head | bad_entry_risk | mae_from_open_pct | -0.269095 | 0.269095 |
| entry_bad_risk_head | bad_entry_risk | return_from_open_pct | -0.174465 | 0.174465 |
| entry_bad_risk_head | bad_entry_risk | last_15m_range_pct | 0.094717 | 0.094717 |
| entry_bad_risk_head | bad_entry_risk | last_hour_range_pct | 0.085184 | 0.085184 |
| entry_bad_risk_head | bad_entry_risk | distance_from_vwap_pct | -0.064356 | 0.064356 |
| entry_bad_risk_head | bad_entry_risk | is_etf_intraday_available | 0.057034 | 0.057034 |
| entry_bad_risk_head | bad_entry_risk | sector_tech | -0.050157 | 0.050157 |
| entry_bad_risk_head | bad_entry_risk | last_hour_ret_pct | -0.045504 | 0.045504 |
| entry_bad_risk_head | bad_entry_risk | is_etf_last_15m_available | 0.04349 | 0.04349 |
| entry_bad_risk_head | bad_entry_risk | kumo_rank_by_score | -0.043293 | 0.043293 |
| entry_bad_risk_head | bad_entry_risk | gap_from_prior_close_pct | 0.037478 | 0.037478 |
| entry_bad_risk_head | bad_entry_risk | sector_financials | 0.032622 | 0.032622 |
| entry_bad_risk_head | bad_entry_risk | sector_utilities | 0.031191 | 0.031191 |
| entry_bad_risk_head | bad_entry_risk | last_15m_ret_pct | -0.02603 | 0.02603 |
| entry_bad_risk_head | bad_entry_risk | sector_healthcare | 0.024795 | 0.024795 |
| entry_bad_risk_head | bad_entry_risk | mfe_from_open_pct | 0.010648 | 0.022276 |
| entry_bad_risk_head | bad_entry_risk | sector_energy | 0.020064 | 0.021236 |
| entry_bad_risk_head | bad_entry_risk | sector_ai_semis | 0.019201 | 0.019201 |
| entry_bad_risk_head | bad_entry_risk | is_etf_last_hour_available | 0.018992 | 0.018992 |
| entry_bad_risk_head | bad_entry_risk | etf_mfe_from_open_pct | -0.017005 | 0.017005 |
| entry_bad_risk_head | bad_entry_risk | is_intraday_available | 0.015108 | 0.015108 |
| entry_bad_risk_head | bad_entry_risk | checkpoint_open | 0.014271 | 0.014271 |
| entry_bad_risk_head | bad_entry_risk | last_15m_volume_log | 0.00872 | 0.013964 |
| entry_bad_risk_head | bad_entry_risk | etf_volume_so_far_log | -0.013477 | 0.013477 |
| entry_bad_risk_head | bad_entry_risk | etf_last_15m_ret_pct | 0.012465 | 0.012465 |
| entry_bad_risk_head | bad_entry_risk | kumo_score | -0.006802 | 0.012394 |
| entry_bad_risk_head | bad_entry_risk | is_last_15m_available | -0.01238 | 0.01238 |
| entry_bad_risk_head | bad_entry_risk | volume_so_far_log | -0.012037 | 0.012037 |
| entry_bad_risk_head | bad_entry_risk | sector_industrials | -0.0018 | 0.01185 |
| entry_bad_risk_head | bad_entry_risk | etf_mae_from_open_pct | 0.011787 | 0.011787 |
| entry_bad_risk_head | bad_entry_risk | sector_real_estate | 0.001156 | 0.010941 |
| entry_bad_risk_head | bad_entry_risk | etf_distance_from_vwap_pct | -0.010338 | 0.010338 |
| entry_bad_risk_head | bad_entry_risk | etf_bars_completed | 0.010065 | 0.010065 |
| entry_bad_risk_head | bad_entry_risk | sector_materials | 0.009035 | 0.009035 |
| entry_bad_risk_head | bad_entry_risk | etf_last_15m_range_pct | -0.008252 | 0.008252 |
| entry_bad_risk_head | bad_entry_risk | etf_last_hour_ret_pct | 0.007891 | 0.007891 |
| entry_bad_risk_head | bad_entry_risk | george_rank | 0.003999 | 0.007582 |
| entry_bad_risk_head | bad_entry_risk | is_last_hour_available | -0.00748 | 0.00748 |
| entry_bad_risk_head | bad_entry_risk | etf_return_from_open_pct | -0.005783 | 0.007371 |
| entry_bad_risk_head | bad_entry_risk | bars_completed | -0.005874 | 0.006221 |
| entry_bad_risk_head | bad_entry_risk | checkpoint_close | -0.005113 | 0.006098 |
| entry_bad_risk_head | bad_entry_risk | checkpoint_first_hour | -0.005711 | 0.005711 |
| entry_bad_risk_head | bad_entry_risk | checkpoint_after_15m | -0.005255 | 0.005255 |
| entry_bad_risk_head | bad_entry_risk | etf_last_hour_range_pct | -0.003719 | 0.004439 |
| entry_bad_risk_head | bad_entry_risk | session_open | 0.004061 | 0.004061 |
| entry_bad_risk_head | bad_entry_risk | current_price | 0.003985 | 0.003985 |
| entry_bad_risk_head | bad_entry_risk | checkpoint_midday | 0.003976 | 0.003976 |
| entry_bad_risk_head | bad_entry_risk | source_bucket_kumo_only | -0.003064 | 0.003669 |
| entry_bad_risk_head | bad_entry_risk | etf_last_15m_volume_log | 0.002813 | 0.00293 |
| entry_bad_risk_head | bad_entry_risk | source_bucket_kumo_with_george_video_context | 0.001707 | 0.002857 |
| entry_bad_risk_head | bad_entry_risk | is_george_video_mention | 0.001808 | 0.002756 |
| entry_bad_risk_head | bad_entry_risk | etf_last_hour_volume_log | 0.002403 | 0.002403 |
| entry_bad_risk_head | bad_entry_risk | last_hour_volume_log | -0.001368 | 0.002353 |
| entry_bad_risk_head | bad_entry_risk | is_george_scanner_positive | 0.002182 | 0.002182 |
| entry_bad_risk_head | bad_entry_risk | is_george_signal_seen | 0.002182 | 0.002182 |
| entry_bad_risk_head | bad_entry_risk | checkpoint_after_30m | -0.002169 | 0.002169 |
| entry_bad_risk_head | bad_entry_risk | is_kumo_top_n | -0.001863 | 0.001863 |
| entry_bad_risk_head | bad_entry_risk | source_bucket_both_george_and_kumo | 0.000915 | 0.000915 |
| entry_bad_risk_head | bad_entry_risk | is_kumo_scanner | -0.000307 | 0.000307 |
| entry_bad_risk_head | bad_entry_risk | is_kumo_signal_seen | -0.000307 | 0.000307 |
| entry_bad_risk_head | bad_entry_risk | source_bucket_george_only | 0.000307 | 0.000307 |
| entry_bad_risk_head | bad_entry_risk | george_watchlist_rank | 0.0 | 0.0 |
| entry_bad_risk_head | bad_entry_risk | is_etf_ichimoku_15m_available | 0.0 | 0.0 |
| entry_bad_risk_head | bad_entry_risk | is_etf_ichimoku_hour_available | 0.0 | 0.0 |
| entry_bad_risk_head | bad_entry_risk | is_george_watchlist | 0.0 | 0.0 |
| entry_bad_risk_head | bad_entry_risk | is_ichimoku_15m_available | 0.0 | 0.0 |
| entry_bad_risk_head | bad_entry_risk | is_ichimoku_hour_available | 0.0 | 0.0 |
| entry_bad_risk_head | bad_entry_risk | position_bars_completed_since_entry | 0.0 | 0.0 |
| entry_bad_risk_head | bad_entry_risk | position_current_return_pct | 0.0 | 0.0 |
| entry_bad_risk_head | bad_entry_risk | position_drawdown_from_peak_pct | 0.0 | 0.0 |
| entry_bad_risk_head | bad_entry_risk | position_mae_so_far_pct | 0.0 | 0.0 |
| entry_bad_risk_head | bad_entry_risk | position_mfe_so_far_pct | 0.0 | 0.0 |
| entry_bad_risk_head | bad_entry_risk | position_minutes_since_entry | 0.0 | 0.0 |
| entry_bad_risk_head | bad_entry_risk | sector_communication_services | 0.0 | 0.0 |
| entry_bad_risk_head | bad_entry_risk | sector_consumer_cyclical | 0.0 | 0.0 |
| entry_bad_risk_head | bad_entry_risk | sector_consumer_defensive | 0.0 | 0.0 |
| entry_bad_risk_head | not_bad_entry_risk | mae_from_open_pct | 0.269095 | 0.269095 |
| entry_bad_risk_head | not_bad_entry_risk | return_from_open_pct | 0.174465 | 0.174465 |
| entry_bad_risk_head | not_bad_entry_risk | last_15m_range_pct | -0.094717 | 0.094717 |
| entry_bad_risk_head | not_bad_entry_risk | last_hour_range_pct | -0.085184 | 0.085184 |

## Read

- Decision comes from replay economics, not classifier accuracy alone.
- Entry heads separate bad-entry risk, winner preservation, and entry timing.
- Management heads separate exit pressure from runner preservation.
- Feature names reuse the existing #490 leakage guard.
