# Rank-Aware Sizing FY2025 Analysis

Generated from `sweeps/reports/rank_aware_sizing_fy2025_469/summary.csv`.

## Read

- All 8 FY2025 cells completed successfully with `workers=3`.
- Parity controls matched prior scanner-gate results:
  - Top20 flat: `29.133%` return, `18.800%` DD, Sharpe `1.065`, orders `78`.
  - Top50 flat: `25.676%` return, `19.800%` DD, Sharpe `0.995`, orders `72`.
- Top20 rank-aware sizing is rejected. It trails the flat top20 control across all tested curves.
- Top50 balanced is the only interesting variant:
  - `28.646%` return, `20.100%` DD, Sharpe `1.002`, orders `82`.
  - Versus top50 flat: `+2.970` return points, `+0.300` DD points, `-1854.77` realized,
    `+4829.88` unrealized, `+10` orders.
- Top50 balanced still does not beat top20 flat: `-0.487` return points, `+1.300` DD points, and
  worse realized net.
- Tail-tiny and top-heavy are rejected. Smaller tail sizing freed cash and allowed more entries,
  which increased churn rather than reducing risk.

## Deltas Versus Flat Controls

| variant | control | dRet % | dDD % | dRealized | dUnrealized | dOrders |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| top20_balanced | top20_flat | -6.116 | -0.100 | -301.88 | -5814.61 | -2 |
| top20_concentrated | top20_flat | -3.267 | +1.100 | -1243.42 | -2023.00 | +2 |
| top20_de_risked | top20_flat | -16.711 | +1.300 | -3384.01 | -13317.45 | +16 |
| top50_balanced | top50_flat | +2.970 | +0.300 | -1854.77 | +4829.88 | +10 |
| top50_tail_tiny | top50_flat | -6.024 | +0.600 | -2543.03 | -3458.23 | +34 |
| top50_top_heavy | top50_flat | -6.997 | +1.700 | -4502.90 | -2477.56 | +26 |

Positive `dUnrealized` means the open-book mark improved versus the control.

## Interpretation

Rank is useful beyond a hard Top-X gate only in the wider top50 case, and even there the gain is
mostly unrealized. The capital weighting did not convert the LambdaMART edge into better realized
PnL. The top20 gate remains the best total-return row in this family.

The next experiment should not keep shrinking lower-rank position sizes without an entry-count cap
or revalidation gate. Otherwise the heat-cap simply recycles freed cash into additional lower-quality
entries. A better next slice is top50 balanced plus one of:

1. max new entries per day after rank-aware sizing,
2. stricter revalidation for ranks greater than 20 before sizing,
3. realized-exit overlay on the top50 balanced row,
4. scanner-rank-aware add/hold revalidation for open positions.

No champion switch.
