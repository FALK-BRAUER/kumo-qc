# Monster Run Decomposition

This report uses tracked `trades_all.csv` artifacts. It does not use the missing ignored
`sweeps/runs/` result JSONs for the scanner-ranker headline run, so it is a first baseline
on available realized-trade variants rather than the final champion/top20 trade-path dataset.

## Inputs

- `/Users/falk/projects/kumo-qc-459-monster-run-decomposition/sweeps/reports/george_range_30/trades_all.csv`
- `/Users/falk/projects/kumo-qc-459-monster-run-decomposition/sweeps/reports/george_combo_30_cached_storage_w3/trades_all.csv`

## Key Findings

- Best closed-PnL variant in this slice: `giveback_tight_no_bull` with 24815.075 closed PnL.
- Highest monster-run dependence: `target_08_let_run` with 41.934% of closed net PnL from monster trades.
- Lowest monster-run dependence: `target_04_fast_take` with 23.145% of closed net PnL from monster trades.
- Top-10 positive trades contribute 21.582% to 27.035% of positive closed PnL across these variants.
- `open_or_censored_pnl` is zero here because these tracked `trades_all.csv` artifacts do not include mark-to-market PnL for open rows; use #456 to rebuild a full path dataset.


## Variant Summary

| variant_id | source_rows | closed_trades | open_or_censored_trades | closed_pnl | open_or_censored_pnl | win_rate_pct | avg_return_pct | median_return_pct | avg_duration_days | median_duration_days | p90_duration_days | top1_positive_pnl_share_pct | top5_positive_pnl_share_pct | top10_positive_pnl_share_pct | top1_net_pnl_share_pct | top5_net_pnl_share_pct | top10_net_pnl_share_pct | monster_trades | monster_pnl | monster_pnl_share_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| giveback_tight_no_bull | 140 | 117 | 23 | 24815.075 | 0.0 | 93.162 | 5.313 | 5.837 | 46.052 | 18.979 | 144.558 | 5.07 | 14.651 | 23.373 | 5.258 | 15.194 | 24.24 | 12 | 6818.57 | 27.478 |
| target_04_fast_take | 134 | 111 | 23 | 24386.274 | 0.0 | 98.198 | 5.516 | 5.003 | 47.967 | 20.0 | 150.958 | 4.264 | 13.312 | 21.582 | 4.283 | 13.371 | 21.679 | 11 | 5644.184 | 23.145 |
| combo_gb_buy005 | 141 | 119 | 22 | 23919.226 | 0.0 | 92.437 | 5.047 | 5.337 | 42.354 | 20.0 | 121.342 | 5.375 | 15.89 | 24.82 | 5.582 | 16.502 | 25.776 | 11 | 6558.778 | 27.421 |
| target_08_let_run | 123 | 100 | 23 | 23379.544 | 0.0 | 89.0 | 5.893 | 6.251 | 51.309 | 26.021 | 146.058 | 4.322 | 16.748 | 26.591 | 4.552 | 17.641 | 28.009 | 18 | 9804.002 | 41.934 |
| p_only_base | 133 | 110 | 23 | 23377.371 | 0.0 | 85.455 | 5.389 | 6.08 | 47.457 | 18.5 | 153.458 | 4.391 | 14.959 | 24.708 | 4.468 | 15.221 | 25.141 | 12 | 6676.956 | 28.562 |
| combo_t08_buy005 | 114 | 91 | 23 | 23048.769 | 0.0 | 89.011 | 6.437 | 7.908 | 53.93 | 28.0 | 130.958 | 4.37 | 16.765 | 27.035 | 4.618 | 17.715 | 28.567 | 17 | 9493.581 | 41.189 |

## Hold Bucket PnL

| variant_id | 0-3d | 11-30d | 31-60d | 4-10d | 60d+ |
| --- | --- | --- | --- | --- | --- |
| combo_gb_buy005 | 1447.566 | 10001.984 | 3792.685 | 4527.086 | 4149.905 |
| combo_t08_buy005 | 240.796 | 8439.462 | 6765.864 | 2422.503 | 5180.143 |
| giveback_tight_no_bull | 1526.19 | 10484.558 | 4030.652 | 3825.306 | 4948.368 |
| p_only_base | 1399.268 | 9852.092 | 3868.464 | 2618.799 | 5638.749 |
| target_04_fast_take | 3093.379 | 8549.509 | 4919.014 | 3518.385 | 4305.988 |
| target_08_let_run | 958.258 | 9330.158 | 6049.87 | 1498.928 | 5542.329 |

## Top Trades

| variant_id | symbol | entry_date | exit_date | duration_days | pnl | return_pct |
| --- | --- | --- | --- | --- | --- | --- |
| combo_gb_buy005 | ORCL | 2025-07-21 | 2025-09-11 | 51.9375 | 1335.2893599999998 | 33.826 |
| combo_gb_buy005 | AMD | 2025-08-18 | 2025-10-07 | 50.0 | 886.0155000000002 | 20.761 |
| combo_gb_buy005 | AVGO | 2025-09-03 | 2025-09-08 | 5.0 | 614.8325498000005 | 14.705 |
| combo_gb_buy005 | AMD | 2025-01-22 | 2025-06-25 | 153.95833333333334 | 576.45555825 | 14.156 |
| combo_gb_buy005 | GOOGL | 2025-11-17 | 2025-11-25 | 8.0 | 534.4995517499996 | 12.27 |
| combo_gb_buy005 | GOOGL | 2025-08-13 | 2025-09-04 | 22.0 | 508.2603 | 12.45 |
| combo_gb_buy005 | NVDA | 2025-10-13 | 2025-10-29 | 16.0 | 460.2465599999998 | 10.652 |
| combo_gb_buy005 | AMD | 2025-10-09 | 2025-10-27 | 18.0 | 428.17079500000045 | 9.581 |
| combo_gb_buy005 | ABBV | 2025-09-26 | 2025-10-02 | 6.0 | 423.98349999999994 | 9.655 |
| combo_gb_buy005 | AMD | 2025-06-25 | 2025-07-16 | 21.0 | 397.6517299999996 | 10.07 |
| combo_gb_buy005 | TSLA | 2025-01-03 | 2025-01-06 | 3.0 | 393.3729479999999 | 10.253 |
| combo_gb_buy005 | TSLA | 2025-09-26 | 2025-10-02 | 6.0 | 374.0059500000001 | 8.639 |
| combo_gb_buy005 | AMD | 2025-10-07 | 2025-10-09 | 2.0 | 368.6725999999999 | 8.466 |
| combo_gb_buy005 | ORCL | 2025-06-17 | 2025-07-03 | 16.0 | 364.44883499999975 | 9.512 |
| combo_gb_buy005 | ORCL | 2025-01-23 | 2025-06-13 | 140.95833333333334 | 360.4869400000002 | 8.853 |
| combo_gb_buy005 | GOOGL | 2025-09-04 | 2025-09-16 | 11.74652777777778 | 359.4263138999998 | 8.607 |
| combo_gb_buy005 | ORCL | 2025-01-03 | 2025-01-23 | 20.0 | 356.2605600000006 | 8.905 |
| combo_gb_buy005 | MSFT | 2025-06-25 | 2025-08-01 | 37.0 | 327.7008599999999 | 8.296 |
| combo_gb_buy005 | AMD | 2025-07-16 | 2025-07-28 | 11.8125 | 325.93937999999963 | 8.012 |
| combo_gb_buy005 | NVDA | 2025-06-30 | 2025-07-16 | 15.73611111111111 | 321.7583200000004 | 7.803 |
| combo_t08_buy005 | ORCL | 2025-08-04 | 2025-09-16 | 43.0 | 1064.3259199999998 | 26.89 |
| combo_t08_buy005 | AMD | 2025-07-29 | 2025-10-07 | 70.0 | 855.196235 | 20.941 |
| combo_t08_buy005 | TSLA | 2025-05-16 | 2025-09-15 | 122.0 | 808.3159694500002 | 21.029 |
| combo_t08_buy005 | AMD | 2025-06-16 | 2025-06-25 | 9.0 | 684.7331699999999 | 17.274 |
| combo_t08_buy005 | GOOGL | 2025-09-16 | 2025-10-30 | 44.0 | 670.6247303499995 | 15.654 |
| combo_t08_buy005 | GOOGL | 2025-10-30 | 2025-11-25 | 26.041666666666668 | 609.0868267499997 | 14.226 |
| combo_t08_buy005 | AVGO | 2025-07-31 | 2025-09-08 | 39.0 | 490.2756391000004 | 12.371 |
| combo_t08_buy005 | AMD | 2025-07-16 | 2025-07-29 | 12.8125 | 485.1099499999999 | 11.925 |
| combo_t08_buy005 | TSLA | 2025-09-15 | 2025-10-02 | 17.0 | 460.9494000000001 | 10.866 |
| combo_t08_buy005 | ORCL | 2025-02-19 | 2025-06-13 | 113.71875 | 455.6845150000005 | 11.458 |
| combo_t08_buy005 | AMD | 2025-10-09 | 2025-10-28 | 19.0 | 452.0526550000002 | 10.115 |
| combo_t08_buy005 | GOOGL | 2025-08-25 | 2025-09-04 | 9.99652777777778 | 442.8276 | 10.676 |
| combo_t08_buy005 | ABBV | 2025-03-10 | 2025-10-02 | 205.98958333333337 | 430.29090999999994 | 11.748 |
| combo_t08_buy005 | AVGO | 2025-01-03 | 2025-06-04 | 151.95833333333334 | 418.8781895 | 10.562 |
| combo_t08_buy005 | AMD | 2025-06-25 | 2025-07-16 | 21.0 | 397.6517299999996 | 10.07 |
| combo_t08_buy005 | ORCL | 2025-06-18 | 2025-07-03 | 15.0 | 397.5853949999999 | 10.468 |
| combo_t08_buy005 | NVDA | 2025-08-21 | 2025-10-10 | 49.99652777777778 | 380.6582800000003 | 9.358 |
| combo_t08_buy005 | LLY | 2025-11-12 | 2025-11-26 | 14.0 | 378.14071980000017 | 9.389 |
| combo_t08_buy005 | GOOGL | 2025-06-20 | 2025-07-22 | 31.993055555555557 | 377.80270000000024 | 9.857 |
| combo_t08_buy005 | V | 2025-01-07 | 2025-01-31 | 23.94097222222222 | 377.25966000000017 | 9.985 |

## Read

- `top*_positive_pnl_share_pct` is the cleanest monster-run concentration signal.
- `monster_pnl_share_pct` uses closed trades with return >= 10% or PnL above the variant's
  90th percentile of positive PnL.
- The patient 8% target variants show materially higher monster-run exposure than faster
  target/giveback variants. That supports a two-persona exit design: protect likely runners,
  but allow faster realization on ordinary swings.
- The 11-30 day bucket is the strongest common PnL bucket in this available slice; George-style
  fast exits should not be interpreted as same-day-only exits.
- Actual George hold/exit evidence still belongs in #461; this report only compares
  available strategy variants that approximate faster profit capture versus let-run behavior.
