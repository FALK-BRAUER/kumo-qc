# Intraday Entry/Exit Policy #490

This trains first-pass dependency-free softmax policies on the #491 intraday decision panel.
Entry and position-management policies are trained separately with expanding-window date validation.

## Inputs

- Panel: `/Users/falk/projects/kumo-qc-490-intraday-entry-exit-policy/sweeps/reports/intraday_decision_panel_491/intraday_decision_panel.csv.gz`

## Summary Metrics

| policy_name | score_type | rows | accuracy_pct | macro_f1 |
| --- | --- | --- | --- | --- |
| entry_policy | predicted_action | 129120 | 58.187 | 0.4482 |
| entry_policy | baseline_action | 129120 | 32.196 | 0.3275 |
| management_policy | predicted_action | 117372 | 59.38 | 0.4151 |
| management_policy | baseline_action | 117372 | 20.611 | 0.195 |

## Action Metrics

| policy_name | score_type | action | support | predicted | precision_pct | recall_pct | f1 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| entry_policy | predicted_action | avoid_bad_entry | 75678 | 95926 | 63.951 | 81.062 | 0.715 |
| entry_policy | predicted_action | enter_now | 29311 | 20807 | 40.506 | 28.754 | 0.3363 |
| entry_policy | predicted_action | wait | 24131 | 12387 | 43.247 | 22.2 | 0.2934 |
| entry_policy | baseline_action | avoid_bad_entry | 75678 | 18055 | 82.62 | 19.711 | 0.3183 |
| entry_policy | baseline_action | enter_now | 29311 | 35661 | 33.748 | 41.06 | 0.3705 |
| entry_policy | baseline_action | wait | 24131 | 75404 | 19.389 | 60.586 | 0.2938 |
| management_policy | predicted_action | do_not_cut_runner | 937 | 2961 | 26.106 | 82.497 | 0.3966 |
| management_policy | predicted_action | exit_loser | 18025 | 24232 | 71.207 | 95.728 | 0.8167 |
| management_policy | predicted_action | hold_or_wait | 8868 | 12515 | 33.04 | 46.628 | 0.3868 |
| management_policy | predicted_action | hold_winner | 29279 | 10106 | 41.183 | 14.215 | 0.2113 |
| management_policy | predicted_action | protect_profit | 142 | 0 | 0.0 | 0.0 | 0.0 |
| management_policy | predicted_action | scratch_or_reduce | 60121 | 67558 | 64.198 | 72.14 | 0.6794 |
| management_policy | baseline_action | do_not_cut_runner | 937 | 0 | 0.0 | 0.0 | 0.0 |
| management_policy | baseline_action | exit_loser | 18025 | 9008 | 97.469 | 48.71 | 0.6496 |
| management_policy | baseline_action | hold_or_wait | 8868 | 92222 | 9.466 | 98.444 | 0.1727 |
| management_policy | baseline_action | hold_winner | 29279 | 15742 | 42.352 | 22.771 | 0.2962 |
| management_policy | baseline_action | protect_profit | 142 | 400 | 3.5 | 9.859 | 0.0517 |
| management_policy | baseline_action | scratch_or_reduce | 60121 | 0 | 0.0 | 0.0 | 0.0 |

## Source/Month/Fold Diagnostics

| policy_name | group_col | group_value | rows | model_accuracy_pct | baseline_accuracy_pct |
| --- | --- | --- | --- | --- | --- |
| entry_policy | scanner_source_bucket | both_george_and_kumo | 2172 | 30.018 | 44.061 |
| entry_policy | scanner_source_bucket | george_only | 2076 | 33.478 | 54.913 |
| entry_policy | scanner_source_bucket | kumo_only | 122034 | 59.172 | 31.685 |
| entry_policy | scanner_source_bucket | kumo_with_george_video_context | 2838 | 55.462 | 28.471 |
| entry_policy | month | 2025-07 | 9000 | 64.256 | 25.489 |
| entry_policy | month | 2025-08 | 12600 | 64.421 | 31.452 |
| entry_policy | month | 2025-09 | 12600 | 63.246 | 34.643 |
| entry_policy | month | 2025-10 | 13800 | 69.783 | 31.391 |
| entry_policy | month | 2025-11 | 11400 | 65.061 | 30.298 |
| entry_policy | month | 2025-12 | 13200 | 59.765 | 31.947 |
| entry_policy | month | 2026-01 | 12000 | 57.808 | 34.417 |
| entry_policy | month | 2026-02 | 12066 | 68.225 | 22.725 |
| entry_policy | month | 2026-03 | 13836 | 75.954 | 18.459 |
| entry_policy | month | 2026-04 | 12828 | 20.432 | 48.028 |
| entry_policy | month | 2026-05 | 5490 | 0.492 | 57.741 |
| entry_policy | month | 2026-06 | 300 | 0.0 | 63.333 |
| entry_policy | fold_490 | 1.0 | 27600 | 63.692 | 30.591 |
| entry_policy | fold_490 | 2.0 | 27600 | 67.514 | 31.359 |
| entry_policy | fold_490 | 3.0 | 27600 | 59.362 | 32.344 |
| entry_policy | fold_490 | 4.0 | 28332 | 71.894 | 21.809 |
| entry_policy | fold_490 | 5.0 | 17988 | 12.036 | 52.079 |
| management_policy | scanner_source_bucket | both_george_and_kumo | 894 | 65.101 | 18.009 |
| management_policy | scanner_source_bucket | george_only | 918 | 66.993 | 25.272 |
| management_policy | scanner_source_bucket | kumo_only | 112746 | 59.354 | 20.747 |
| management_policy | scanner_source_bucket | kumo_with_george_video_context | 2814 | 56.148 | 14.463 |
| management_policy | month | 2025-07 | 13049 | 60.602 | 18.791 |
| management_policy | month | 2025-08 | 12533 | 57.313 | 25.596 |
| management_policy | month | 2025-09 | 12446 | 56.259 | 27.27 |
| management_policy | month | 2025-10 | 13682 | 64.391 | 24.324 |
| management_policy | month | 2025-11 | 11258 | 59.851 | 20.297 |
| management_policy | month | 2025-12 | 13021 | 52.277 | 21.842 |
| management_policy | month | 2026-01 | 11905 | 50.886 | 21.1 |
| management_policy | month | 2026-02 | 12035 | 62.867 | 12.987 |
| management_policy | month | 2026-03 | 13769 | 68.727 | 14.293 |
| management_policy | month | 2026-04 | 3674 | 58.819 | 17.338 |
| management_policy | fold_490 | 1.0 | 23185 | 59.09 | 21.41 |
| management_policy | fold_490 | 2.0 | 23171 | 59.881 | 26.477 |
| management_policy | fold_490 | 3.0 | 23079 | 58.027 | 22.358 |
| management_policy | fold_490 | 4.0 | 23372 | 52.867 | 19.69 |
| management_policy | fold_490 | 5.0 | 24565 | 66.652 | 13.556 |

## Fold Summary

| policy_name | fold | train_start | train_end | valid_start | valid_end | train_rows | valid_rows |
| --- | --- | --- | --- | --- | --- | --- | --- |
| entry_policy | 1 | 2025-05-05 | 2025-07-10 | 2025-07-11 | 2025-09-15 | 27600 | 27600 |
| entry_policy | 2 | 2025-05-05 | 2025-09-15 | 2025-09-16 | 2025-11-18 | 55200 | 27600 |
| entry_policy | 3 | 2025-05-05 | 2025-11-18 | 2025-11-19 | 2026-01-27 | 82800 | 27600 |
| entry_policy | 4 | 2025-05-05 | 2026-01-27 | 2026-01-28 | 2026-04-01 | 110400 | 28332 |
| entry_policy | 5 | 2025-05-05 | 2026-04-01 | 2026-04-02 | 2026-06-04 | 138732 | 17988 |
| management_policy | 1 | 2025-05-05 | 2025-06-30 | 2025-07-01 | 2025-08-25 | 23201 | 23185 |
| management_policy | 2 | 2025-05-05 | 2025-08-25 | 2025-08-26 | 2025-10-20 | 46386 | 23171 |
| management_policy | 3 | 2025-05-05 | 2025-10-20 | 2025-10-21 | 2025-12-15 | 69557 | 23079 |
| management_policy | 4 | 2025-05-05 | 2025-12-15 | 2025-12-16 | 2026-02-11 | 92636 | 23372 |
| management_policy | 5 | 2025-05-05 | 2026-02-11 | 2026-02-12 | 2026-04-09 | 116008 | 24565 |

## Feature Diagnostics

| policy_name | action | feature | coef_mean | coef_abs_mean |
| --- | --- | --- | --- | --- |
| entry_policy | avoid_bad_entry | mae_from_open_pct | -0.347881 | 0.347881 |
| entry_policy | avoid_bad_entry | return_from_open_pct | -0.180608 | 0.180608 |
| entry_policy | avoid_bad_entry | last_15m_range_pct | 0.139578 | 0.139578 |
| entry_policy | avoid_bad_entry | last_hour_range_pct | 0.127617 | 0.127617 |
| entry_policy | avoid_bad_entry | is_etf_intraday_available | 0.099859 | 0.099859 |
| entry_policy | avoid_bad_entry | is_etf_last_15m_available | 0.075394 | 0.075394 |
| entry_policy | avoid_bad_entry | mfe_from_open_pct | 0.067383 | 0.067383 |
| entry_policy | avoid_bad_entry | distance_from_vwap_pct | -0.065143 | 0.065143 |
| entry_policy | avoid_bad_entry | kumo_rank_by_score | -0.061953 | 0.061953 |
| entry_policy | avoid_bad_entry | gap_from_prior_close_pct | 0.050552 | 0.050552 |
| entry_policy | avoid_bad_entry | last_hour_ret_pct | -0.045039 | 0.045039 |
| entry_policy | avoid_bad_entry | sector_financials | 0.039505 | 0.039505 |
| entry_policy | avoid_bad_entry | sector_tech | -0.037307 | 0.037307 |
| entry_policy | avoid_bad_entry | is_etf_last_hour_available | 0.036695 | 0.036695 |
| entry_policy | avoid_bad_entry | sector_healthcare | 0.03585 | 0.03585 |
| entry_policy | avoid_bad_entry | sector_utilities | 0.033113 | 0.033113 |
| entry_policy | avoid_bad_entry | sector_ai_semis | 0.026574 | 0.026574 |
| entry_policy | avoid_bad_entry | last_15m_ret_pct | -0.026424 | 0.026424 |
| entry_policy | avoid_bad_entry | etf_volume_so_far_log | -0.026156 | 0.026156 |
| entry_policy | avoid_bad_entry | sector_energy | 0.025675 | 0.025675 |
| entry_policy | avoid_bad_entry | is_intraday_available | 0.025605 | 0.025605 |
| entry_policy | avoid_bad_entry | etf_bars_completed | 0.023991 | 0.023991 |
| entry_policy | avoid_bad_entry | etf_mfe_from_open_pct | -0.023748 | 0.023748 |
| entry_policy | avoid_bad_entry | sector_industrials | 0.011543 | 0.023093 |
| entry_policy | avoid_bad_entry | last_15m_volume_log | 0.016038 | 0.022096 |
| entry_policy | avoid_bad_entry | checkpoint_open | 0.019091 | 0.019091 |
| entry_policy | avoid_bad_entry | etf_mae_from_open_pct | 0.018381 | 0.018381 |
| entry_policy | avoid_bad_entry | kumo_score | -0.018089 | 0.018089 |
| entry_policy | avoid_bad_entry | sector_materials | 0.017449 | 0.017449 |
| entry_policy | avoid_bad_entry | is_last_15m_available | -0.015902 | 0.015902 |
| entry_policy | avoid_bad_entry | volume_so_far_log | -0.014903 | 0.014903 |
| entry_policy | avoid_bad_entry | etf_last_15m_ret_pct | 0.013354 | 0.013354 |
| entry_policy | avoid_bad_entry | etf_distance_from_vwap_pct | -0.011484 | 0.011484 |
| entry_policy | avoid_bad_entry | source_bucket_kumo_only | -0.011329 | 0.011329 |
| entry_policy | avoid_bad_entry | etf_last_hour_ret_pct | 0.009844 | 0.009844 |
| entry_policy | avoid_bad_entry | sector_real_estate | 0.002036 | 0.009769 |
| entry_policy | avoid_bad_entry | is_last_hour_available | -0.009543 | 0.009543 |
| entry_policy | avoid_bad_entry | is_george_video_mention | 0.009513 | 0.009513 |
| entry_policy | avoid_bad_entry | source_bucket_kumo_with_george_video_context | 0.009404 | 0.009404 |
| entry_policy | avoid_bad_entry | checkpoint_close | -0.00796 | 0.008904 |
| entry_policy | avoid_bad_entry | bars_completed | -0.008082 | 0.008815 |
| entry_policy | avoid_bad_entry | george_rank | 0.004809 | 0.008774 |
| entry_policy | avoid_bad_entry | etf_return_from_open_pct | -0.006295 | 0.008048 |
| entry_policy | avoid_bad_entry | etf_last_15m_range_pct | -0.005163 | 0.007247 |
| entry_policy | avoid_bad_entry | checkpoint_after_15m | -0.00716 | 0.00716 |
| entry_policy | avoid_bad_entry | checkpoint_first_hour | -0.00676 | 0.00676 |
| entry_policy | avoid_bad_entry | last_hour_volume_log | 0.002474 | 0.006261 |
| entry_policy | avoid_bad_entry | checkpoint_midday | 0.005656 | 0.005656 |
| entry_policy | avoid_bad_entry | etf_last_15m_volume_log | -0.000314 | 0.0052 |
| entry_policy | avoid_bad_entry | etf_last_hour_range_pct | -0.002864 | 0.005124 |
| entry_policy | avoid_bad_entry | etf_last_hour_volume_log | -0.001096 | 0.004913 |
| entry_policy | avoid_bad_entry | is_george_scanner_positive | 0.003505 | 0.003505 |
| entry_policy | avoid_bad_entry | is_george_signal_seen | 0.003505 | 0.003505 |
| entry_policy | avoid_bad_entry | checkpoint_after_30m | -0.002868 | 0.002868 |
| entry_policy | avoid_bad_entry | is_kumo_top_n | -0.002608 | 0.002608 |
| entry_policy | avoid_bad_entry | session_open | 0.002357 | 0.002357 |
| entry_policy | avoid_bad_entry | current_price | 0.002274 | 0.002274 |
| entry_policy | avoid_bad_entry | source_bucket_both_george_and_kumo | 0.000852 | 0.000852 |
| entry_policy | avoid_bad_entry | is_kumo_scanner | 0.000238 | 0.000238 |
| entry_policy | avoid_bad_entry | is_kumo_signal_seen | 0.000238 | 0.000238 |

## Read

- Decision: iterate, do not promote yet.
- This is a first supervised policy baseline, not a deployment recommendation.
- Core features intentionally exclude route-label assumption counts and upstream learned opportunity scores.
- The report should be read against fold/month diagnostics before trusting aggregate metrics.
- Promotion requires local replay against actual order semantics and a cleaner Ichimoku/historical context pass.
- Feature names are guarded against oracle/future/label leakage.
