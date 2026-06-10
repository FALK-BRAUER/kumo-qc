# Combined Real-Strategy Scanner FY2025 Leaderboard

Merges the three valid rows from the six-worker attempt with the nine valid rows from the three-worker retry. Invalid six-worker rows are excluded because LEAN exited non-zero after Docker memory pressure.

Generated: 2026-06-10T03:58:51.503504+00:00

## Read

- Best overall: `giveback_no_bull_scanner_top20` at 12.890% return, 17.300% DD, Sharpe 0.707.
- Across all three real strategy families, `top20` is the best scanner setting by total return.
- The top20 edge mostly comes from less negative unrealized marks, not higher closed PnL. Closed PnL is often slightly lower than scanner-off control.
- `top15` is usually too restrictive. `top25` adds back activity but generally does not beat top20.
- `strategies.realized_giveback_no_bull` winner: `top20` at 12.890% return, 17.300% DD, delta vs off +2.303% return and -0.100% DD.
- `strategies.realized_target_04_fast_take` winner: `top20` at 12.872% return, 17.100% DD, delta vs off +3.142% return and -0.600% DD.
- `strategies.realized_target_08_let_run` winner: `top20` at 12.352% return, 17.000% DD, delta vs off +2.006% return and -0.400% DD.

## Leaderboard

| rank | variant | ret % | DD % | Sharpe | orders | realized net | unrealized | closed win % | delta ret vs off | delta DD vs off | delta realized | delta unrealized |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | giveback_no_bull_scanner_top20 | 12.890 | 17.300 | 0.707 | 304 | 23,404.53 | -10,230.71 | 91.5 | +2.303 | -0.100 | -1221.40 | +3532.65 |
| 2 | target04_fast_take_scanner_top20 | 12.872 | 17.100 | 0.702 | 262 | 23,466.43 | -10,354.65 | 98.3 | +3.142 | -0.600 | -498.10 | +3640.09 |
| 3 | target08_let_run_scanner_top20 | 12.352 | 17.000 | 0.682 | 229 | 22,095.78 | -9,536.02 | 90.4 | +2.006 | -0.400 | -1827.72 | +3809.96 |
| 4 | giveback_no_bull_scanner_top25 | 11.040 | 17.400 | 0.580 | 305 | 25,299.86 | -13,977.48 | 95.0 | +0.453 | +0.000 | +673.93 | -214.12 |
| 5 | giveback_no_bull_scanner_off | 10.587 | 17.400 | 0.557 | 299 | 24,625.93 | -13,763.36 | 94.9 | +0.000 | +0.000 | +0.00 | +0.00 |
| 6 | target08_let_run_scanner_off | 10.346 | 17.400 | 0.538 | 255 | 23,923.50 | -13,345.98 | 93.1 | +0.000 | +0.000 | +0.00 | +0.00 |
| 7 | target08_let_run_scanner_top25 | 10.116 | 17.300 | 0.528 | 251 | 23,801.84 | -13,458.06 | 93.0 | -0.230 | -0.100 | -121.66 | -112.08 |
| 8 | target04_fast_take_scanner_top25 | 10.080 | 17.300 | 0.526 | 275 | 24,261.74 | -13,929.90 | 97.6 | +0.350 | -0.400 | +297.21 | +64.84 |
| 9 | target04_fast_take_scanner_off | 9.730 | 17.700 | 0.503 | 263 | 23,964.53 | -13,994.74 | 96.7 | +0.000 | +0.000 | +0.00 | +0.00 |
| 10 | giveback_no_bull_scanner_top15 | 8.597 | 14.900 | 0.523 | 252 | 19,398.03 | -10,564.69 | 90.7 | -1.990 | -2.500 | -5227.90 | +3198.67 |
| 11 | target04_fast_take_scanner_top15 | 8.009 | 12.000 | 0.556 | 185 | 17,071.78 | -8,894.86 | 96.4 | -1.721 | -5.700 | -6892.75 | +5099.88 |
| 12 | target08_let_run_scanner_top15 | 7.589 | 15.600 | 0.458 | 179 | 14,707.72 | -6,956.95 | 91.4 | -2.757 | -1.800 | -9215.78 | +6389.03 |

## Source Runs

- `scanner_ranker_real_strategy_fy2025_453`: workers=6, 3 valid / 12 attempted; other rows invalid after Docker memory pressure/non-zero LEAN exits.
- `scanner_ranker_real_strategy_fy2025_453_retry_w3`: workers=3, 9 valid / 9 attempted; recovered the failed cells.
