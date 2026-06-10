# #455 Top20 Realized PnL Diagnostics

## Read

- `top20` is the only scanner setting analyzed here; each row is compared with its scanner-off control.
- Per-symbol open PnL is an allocation estimate from each variant's aggregate LEAN `Unrealized` statistic, proportional to open lot cost. Treat it as a drag locator, not exact accounting.
- Current order tags do not include LambdaMART scanner score/rank. Rank-bucket diagnostics use the existing `decision_rank` tag, not the learned scanner score.
- `giveback_no_bull_scanner_top20`: realized `23404.53`, unrealized `-10230.71`, open lots `20`, worst allocated open `ORCL -556.87`.
- `target04_fast_take_scanner_top20`: realized `23466.43`, unrealized `-10354.65`, open lots `22`, worst allocated open `NVDA -518.45`.
- `target08_let_run_scanner_top20`: realized `22095.78`, unrealized `-9536.02`, open lots `21`, worst allocated open `NVDA -503.59`.
- Removed symbols with negative off-control contribution: `0`. Added symbols with negative top20 contribution: `0`. Shared symbols with negative top20 open allocation: `63`.
- Entry-date changes are material: `147` off-control entries are absent in top20, and `133` top20 entries are absent in scanner-off controls.
- Oldest open lot at year-end: `giveback_no_bull_scanner_off HD` from `2025-01-22`, age `343` days.

## Variant Summary

| variant | ret % | DD % | realized | unrealized | open lots | worst open est | exit reasons |
| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `giveback_no_bull_scanner_off` | 10.587 | 17.4 | 24625.93 | -13763.36 | 23 | AMZN -664.04 | giveback:43;target:24;unknown:71 |
| `giveback_no_bull_scanner_top20` | 12.89 | 17.3 | 23404.53 | -10230.71 | 20 | ORCL -556.87 | giveback:65;target:32;unknown:45 |
| `target04_fast_take_scanner_off` | 9.73 | 17.7 | 23964.53 | -13994.74 | 23 | XOM -691.10 | giveback:2;target:40;unknown:78 |
| `target04_fast_take_scanner_top20` | 12.872 | 17.1 | 23466.43 | -10354.65 | 22 | NVDA -518.45 | giveback:2;target:56;unknown:62 |
| `target08_let_run_scanner_off` | 10.346 | 17.4 | 23923.50 | -13345.98 | 23 | AMZN -658.00 | giveback:55;target:34;unknown:27 |
| `target08_let_run_scanner_top20` | 12.352 | 17.0 | 22095.78 | -9536.02 | 21 | NVDA -503.59 | giveback:36;target:14;unknown:54 |

## Largest Negative Top20 Open Allocations

| variant | symbol | entry date | age days | rank | allocation est |
| --- | --- | ---: | ---: | ---: | ---: |
| `target04_fast_take_scanner_off` | XOM | 2025-11-12 | 49 | 95.000 | -691.10 |
| `target04_fast_take_scanner_off` | NVDA | 2025-10-30 | 62 | 3.000 | -687.24 |
| `target04_fast_take_scanner_off` | AMD | 2025-10-29 | 63 | 4.000 | -681.22 |
| `target04_fast_take_scanner_off` | ABBV | 2025-10-02 | 90 | 122.000 | -667.26 |
| `giveback_no_bull_scanner_off` | AMZN | 2025-11-04 | 57 | 6.000 | -664.04 |
| `giveback_no_bull_scanner_off` | ORCL | 2025-10-24 | 68 | 12.000 | -664.03 |
| `giveback_no_bull_scanner_off` | NVDA | 2025-10-30 | 62 | 3.000 | -658.66 |
| `target08_let_run_scanner_off` | AMZN | 2025-11-04 | 57 | 6.000 | -658.00 |
| `target04_fast_take_scanner_off` | MRK | 2025-11-26 | 35 | 95.000 | -656.73 |
| `target04_fast_take_scanner_off` | AMZN | 2025-11-04 | 57 | 6.000 | -654.36 |
| `target08_let_run_scanner_off` | NVDA | 2025-10-30 | 62 | 3.000 | -652.67 |
| `target04_fast_take_scanner_off` | ORCL | 2025-10-14 | 78 | 10.000 | -650.63 |
| `giveback_no_bull_scanner_off` | AMD | 2025-10-28 | 64 | 4.000 | -649.32 |
| `target04_fast_take_scanner_off` | JPM | 2025-12-24 | 7 | 36.000 | -647.88 |
| `giveback_no_bull_scanner_off` | AVGO | 2025-11-28 | 33 | 14.000 | -646.74 |

## Largest Entry-Date Deltas

| base | symbol | date | relation | delta closed | delta open est | off entries | top20 entries |
| --- | --- | ---: | --- | ---: | ---: | ---: | ---: |
| `realized_giveback_no_bull` | AMD | 2025-08-18 | added_by_top20 | 874.65 | 0.00 | 0 | 1 |
| `realized_target_08_let_run` | AMD | 2025-08-15 | added_by_top20 | 837.67 | 0.00 | 0 | 1 |
| `realized_giveback_no_bull` | AMD | 2025-08-14 | removed_by_top20 | -763.51 | 0.00 | 1 | 0 |
| `realized_target_08_let_run` | AMD | 2025-08-14 | removed_by_top20 | -763.51 | 0.00 | 1 | 0 |
| `realized_target_08_let_run` | TSLA | 2025-05-30 | removed_by_top20 | -724.79 | 0.00 | 1 | 0 |
| `realized_target_04_fast_take` | XOM | 2025-11-12 | removed_by_top20 | 0.00 | 691.10 | 1 | 0 |
| `realized_target_04_fast_take` | AMD | 2025-10-29 | removed_by_top20 | 0.00 | 681.22 | 1 | 0 |
| `realized_target_04_fast_take` | ORCL | 2025-10-14 | removed_by_top20 | 0.00 | 650.63 | 1 | 0 |
| `realized_target_08_let_run` | AMD | 2025-10-29 | removed_by_top20 | 0.00 | 642.75 | 1 | 0 |
| `realized_target_08_let_run` | TSLA | 2025-12-19 | removed_by_top20 | 0.00 | 635.22 | 1 | 0 |
| `realized_giveback_no_bull` | AAPL | 2025-12-03 | removed_by_top20 | 0.00 | 632.82 | 1 | 0 |
| `realized_target_08_let_run` | MRK | 2025-12-01 | removed_by_top20 | 0.00 | 630.42 | 1 | 0 |
| `realized_giveback_no_bull` | LLY | 2025-12-01 | removed_by_top20 | 0.00 | 630.26 | 1 | 0 |
| `realized_target_08_let_run` | GOOGL | 2025-08-20 | added_by_top20 | 629.69 | 0.00 | 0 | 1 |
| `realized_giveback_no_bull` | NVDA | 2025-10-15 | removed_by_top20 | -620.25 | 0.00 | 1 | 0 |
| `realized_giveback_no_bull` | JPM | 2025-12-29 | removed_by_top20 | 0.00 | 620.20 | 1 | 0 |
| `realized_target_08_let_run` | AAPL | 2025-12-04 | removed_by_top20 | 0.00 | 613.90 | 1 | 0 |
| `realized_target_08_let_run` | GOOGL | 2025-11-25 | removed_by_top20 | 0.00 | 610.61 | 1 | 0 |
| `realized_target_04_fast_take` | NFLX | 2025-06-27 | removed_by_top20 | 0.00 | 601.36 | 1 | 0 |
| `realized_target_04_fast_take` | HD | 2025-01-28 | removed_by_top20 | 0.00 | 579.37 | 1 | 0 |

## Largest Symbol Deltas

| base | symbol | relation | delta closed | delta open est | off entries | top20 entries |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| `realized_target_08_let_run` | TSLA | shared | -1240.17 | 635.22 | 12 | 4 |
| `realized_target_08_let_run` | NFLX | shared | -1116.65 | 578.26 | 8 | 1 |
| `realized_target_04_fast_take` | NFLX | shared | -929.81 | 601.36 | 8 | 1 |
| `realized_giveback_no_bull` | NFLX | shared | -252.35 | 570.42 | 10 | 7 |
| `realized_giveback_no_bull` | XOM | shared | -235.13 | 552.33 | 3 | 1 |
| `realized_giveback_no_bull` | V | shared | -91.94 | 533.67 | 5 | 8 |
| `realized_target_04_fast_take` | TSLA | shared | -518.25 | 91.34 | 9 | 10 |
| `realized_target_04_fast_take` | GOOGL | shared | 334.05 | 157.92 | 11 | 11 |
| `realized_target_08_let_run` | GOOGL | shared | 347.25 | 142.00 | 12 | 12 |
| `realized_target_08_let_run` | NVDA | shared | -328.52 | 149.08 | 7 | 9 |
| `realized_target_04_fast_take` | AMD | shared | 286.31 | 174.13 | 14 | 14 |
| `realized_target_08_let_run` | AMD | shared | 263.60 | 146.22 | 14 | 12 |
| `realized_target_04_fast_take` | META | shared | 243.36 | 148.59 | 6 | 8 |
| `realized_giveback_no_bull` | GOOGL | shared | -275.74 | 99.44 | 10 | 14 |
| `realized_giveback_no_bull` | AMD | shared | 267.47 | 104.78 | 12 | 13 |
| `realized_target_08_let_run` | AMZN | shared | -164.15 | 178.50 | 3 | 3 |
| `realized_giveback_no_bull` | META | shared | -218.21 | 91.75 | 8 | 8 |
| `realized_target_04_fast_take` | AMZN | shared | -135.32 | 160.72 | 3 | 3 |
| `realized_target_08_let_run` | MRK | shared | 160.02 | 135.57 | 2 | 3 |
| `realized_giveback_no_bull` | AMZN | shared | -153.33 | 138.09 | 3 | 3 |
