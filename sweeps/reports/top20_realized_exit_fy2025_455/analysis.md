# Top20 Realization Sweep Analysis

Generated from `sweeps/reports/top20_realized_exit_fy2025_455/summary.csv`.

## Read

- All 18 FY2025 cells completed successfully with `workers=3`.
- The age-60 cap is the only variation that improves total return and drawdown in all three families.
- The age-60 improvement is mostly a year-end unrealized-drag reduction, not a realized-PnL improvement.
- Stale-MFE exits are rejected: they add churn, lower closed win rate, and usually hurt return/DD.
- Tighter MFE giveback variants do not generalize. `giveback_no_bull_top20_mfe_gb06` improved realized PnL, but with worse drawdown and worse open drag; the same idea failed on target08.
- This sweep is an exit-realization diagnostic on the existing top20 real-strategy setup. It is not the final scanner/intraday architecture proof.

## Leader Read

| variant | ret % | DD % | orders | realized net | unrealized | closed win % |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| target08_let_run_top20_age60 | 15.969 | 13.300 | 487 | 20361.48 | -3924.68 | 57.3 |
| target04_fast_take_top20_age60 | 13.087 | 13.100 | 548 | 17498.75 | -3883.65 | 59.8 |
| giveback_no_bull_top20_age60 | 13.062 | 14.600 | 675 | 21680.59 | -7964.47 | 69.4 |
| target08_let_run_top20_base | 12.645 | 17.100 | 242 | 22623.79 | -9758.50 | 90.9 |
| giveback_no_bull_top20_mfe_gb06 | 12.076 | 16.500 | 314 | 25408.05 | -13038.32 | 92.5 |

## Family Deltas Versus Top20 Base

| family | variant | dRet % | dDD % | dRealized | dUnrealized | dOrders | win % |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| giveback | age60 | +1.724 | -0.800 | -1999.24 | +4081.74 | +359 | 69.4 |
| target04 | age60 | +2.608 | -2.600 | -3018.02 | +5925.82 | +299 | 59.8 |
| target08 | age60 | +3.324 | -3.800 | -2262.31 | +5833.82 | +245 | 57.3 |
| giveback | stale20 | -2.014 | +1.200 | -3824.14 | +1968.13 | +158 | 70.0 |
| target04 | stale20 | -2.660 | +0.500 | -6750.02 | +4241.61 | +151 | 68.4 |
| target08 | stale20 | -1.366 | +0.800 | -7827.49 | +6662.88 | +201 | 60.2 |
| giveback | mfe_gb06 | +0.738 | +1.100 | +1728.22 | -992.11 | -2 | 92.5 |
| target04 | mfe_gb06 | +1.311 | +1.200 | +3189.08 | -1864.80 | +14 | 99.2 |
| target08 | mfe_gb06 | -5.316 | -1.200 | -2945.34 | -2389.40 | -19 | 94.1 |

Positive `dUnrealized` means the open-book mark improved versus the family base.

## Interpretation

`age60` is a useful risk-control diagnostic because it cuts stale open-book losses and lowers DD.
It does not yet prove better trade selection or realized edge: realized net falls in all three
families, order count jumps sharply, and closed win rate falls hard.

The result supports follow-up issue #469, not a champion switch:

1. Persist scanner rank/score/features into the intraday candidate snapshot.
2. Add rank-aware intraday confirmation: high-rank names can use a simpler gap/hold trigger, while
   marginal ranks need stronger first-hour confirmation.
3. Add first-hour/hourly path features: opening range, gap fill, VWAP/close location, hold above
   intraday Tenkan/VWAP, and first-hour MFE/MAE.
4. Use scanner score/rank and sector/industry breadth as sizing and revalidation context.
5. Test rank/rotation exits separately from pure PnL/MFE exits.

The current ranker is being used as a ranking/Top-X gate. Downstream phases do not yet consume
`_scanner_ranker_scores` or `_scanner_ranker_features`, so this sweep cannot answer whether scanner
rank should adjust entry timing, sizing, or exits.
