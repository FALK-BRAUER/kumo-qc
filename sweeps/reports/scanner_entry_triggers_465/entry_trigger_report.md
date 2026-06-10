# Scanner Entry Trigger Analysis #465

This is the first #465 slice: leakage-safe next-open entry gates from the #464 path labels.
It does not replay alternate first-hour, breakout, or pullback entry prices yet.

## Inputs

- Labels: `/Users/falk/projects/kumo-qc-465-entry-triggers/sweeps/reports/scanner_opportunity_paths_464/opportunity_path_labels.csv.gz`

## Read

- Best simple gate by the current objective: `kumo_top20`.
- Kumo rank gates improve average return modestly, but do not solve bad-trade rate.
- Gap gates alone are noisy: moderate negative/positive gaps can produce higher upside,
  while very large gaps have worse average return and higher bad-trade rate.
- George scanner/watchlist rows are not automatically better under next-open entry; they need
  better confirmation or exit handling before being promoted.

## Gate Summary

| gate_id | available_rows | avg_ret_20d_close_pct | median_ret_20d_close_pct | good_pct | runner_pct | bad_trade_pct | target4_before_stop2_pct | stop2_before_target4_pct | objective_score |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| kumo_top20 | 5090 | 3.4937 | 1.1339 | 45.599 | 24.204 | 38.782 | 32.299 | 59.194 | 3.7413 |
| kumo_top20_gap_minus2_to_5 | 4707 | 3.1711 | 1.03 | 44.636 | 21.904 | 38.793 | 32.186 | 59.698 | 3.3943 |
| kumo_top50 | 12713 | 2.9659 | 1.0271 | 44.647 | 22.489 | 38.449 | 31.543 | 59.671 | 3.199 |
| kumo_top100 | 25410 | 2.753 | 1.0872 | 44.124 | 21.381 | 37.54 | 31.334 | 58.949 | 3.0065 |
| kumo_top50_gap_minus2_to_5 | 11892 | 2.72 | 0.9542 | 43.92 | 20.602 | 38.303 | 31.366 | 60.225 | 2.9421 |
| kumo_top100_gap_minus2_to_5 | 23828 | 2.5559 | 1.0272 | 43.361 | 19.511 | 37.389 | 31.19 | 59.468 | 2.803 |
| gap_not_extreme | 308293 | 2.0397 | 0.8617 | 42.811 | 19.058 | 38.651 | 31.682 | 58.961 | 2.1684 |
| kumo_score_ge7 | 69282 | 1.9917 | 0.967 | 41.561 | 19.478 | 37.16 | 30.027 | 57.516 | 2.1313 |
| next_open_all | 312076 | 2.0115 | 0.8531 | 42.824 | 19.362 | 38.802 | 31.597 | 58.837 | 2.1238 |
| gap_minus2_to_5 | 295331 | 1.9342 | 0.8555 | 42.478 | 18.153 | 38.396 | 31.546 | 59.061 | 2.0693 |
| gap_0_to_5 | 170805 | 1.913 | 0.8177 | 42.201 | 18.732 | 38.187 | 31.048 | 58.761 | 2.039 |
| george_scanner_or_watchlist | 704 | 0.7153 | -0.9664 | 38.92 | 22.585 | 47.869 | 30.54 | 59.801 | 0.2324 |
| george_scanner_or_watchlist_gap_minus2_to_5 | 632 | 0.5018 | -1.0338 | 37.816 | 20.57 | 48.418 | 30.38 | 59.968 | -0.0283 |

## Rank And Gap Buckets

| bucket | rows | avg_ret_20d_close_pct | median_ret_20d_close_pct | good_pct | runner_pct | bad_trade_pct |
| --- | --- | --- | --- | --- | --- | --- |
| rank_1_10 | 2547 | 3.5119 | 1.2216 | 44.994 | 23.125 | 38.477 |
| rank_11_20 | 2543 | 3.4755 | 1.03 | 46.205 | 25.285 | 39.088 |
| rank_21_50 | 7623 | 2.6135 | 0.9532 | 44.012 | 21.343 | 38.226 |
| rank_51_100 | 12697 | 2.5397 | 1.1456 | 43.601 | 20.273 | 36.631 |
| rank_101_250 | 38104 | 1.9403 | 1.0425 | 42.41 | 18.919 | 37.366 |
| rank_251_500 | 63532 | 1.4962 | 0.8734 | 41.441 | 18.759 | 38.566 |
| gap_lt_minus5 | 2580 | 0.202 | -0.7877 | 44.806 | 43.953 | 50.116 |
| gap_minus5_to_minus2 | 10824 | 5.0452 | 1.5624 | 51.515 | 39.339 | 43.237 |
| gap_minus2_to_0 | 132262 | 1.9685 | 0.8558 | 42.546 | 17.23 | 38.576 |
| gap_0_to_2 | 157585 | 1.7548 | 0.7918 | 41.524 | 17.026 | 37.769 |
| gap_2_to_5 | 13233 | 3.7942 | 1.5049 | 50.276 | 39.054 | 43.165 |
| gap_5_to_8 | 2155 | 1.3603 | -0.5141 | 44.64 | 41.253 | 50.812 |
| gap_gt_8 | 1203 | -1.3243 | -2.2535 | 41.978 | 44.555 | 53.367 |

## Recommendation

- First LEAN sweep candidate: `kumo_top20` or `kumo_top20_gap_minus2_to_5` as a small
  capital-allocation gate, not as a full solution.
- Do not spend ML effort on gap gates alone; the next research pass should replay first-hour
  confirmation and breakout/pullback entries with alternate entry prices.
