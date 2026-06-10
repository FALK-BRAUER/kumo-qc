# Rank-Aware Intraday FY2025 Analysis

Generated from `sweeps/reports/rank_aware_intraday_fy2025_469/summary.csv`.

## Read

- All 8 FY2025 cells completed successfully with `workers=3`.
- Scanner rank context is now durable in the main LEAN result JSON entry tags:
  `scanner_rank` and `scanner_score` appear alongside the existing `decision_rank`.
- The top20 gate-only control remains the best row in this pack:
  `29.133%` return, `18.800%` DD, Sharpe `1.065`, orders `78`.
- Rank-aware top20 variants did not improve the current top20 gate. Loosening top ranks or
  tightening ranks 11-20 either added churn or cut useful trades.
- Rank-aware top50 default is useful: it improves top50 gate-only from `25.676%` to `27.473%`,
  lowers DD slightly from `19.800%` to `19.700%`, improves realized net by `$320.33`, and improves
  unrealized mark by `$1,476.81`.
- `top50_tail_strict` is identical to default in this run, which means the stricter tail did not
  bind on the actually-entered lower-rank candidates.
- `top50_mid30_tail` is rejected: more orders, worse return, worse DD, and worse realized/unrealized
  deltas versus top50 gate.

## Deltas Versus Gate Controls

| variant | control | dRet % | dDD % | dRealized | dUnrealized | dOrders |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| top20_bucket_default | top20_gate | -0.532 | +0.200 | -1369.60 | +838.97 | +2 |
| top20_bucket_strict_mid | top20_gate | -8.548 | +0.700 | -3644.20 | -4907.13 | -2 |
| top20_top5_only_loose | top20_gate | -3.086 | +0.700 | -1787.50 | -1292.59 | +6 |
| top50_bucket_default | top50_gate | +1.797 | -0.100 | +320.33 | +1476.81 | +2 |
| top50_tail_strict | top50_gate | +1.797 | -0.100 | +320.33 | +1476.81 | +2 |
| top50_mid30_tail | top50_gate | -3.541 | +1.100 | -1148.80 | -2387.97 | +8 |

Positive `dUnrealized` means the open-book mark improved versus the control.

## Interpretation

This does not justify a champion switch. The best total-return row remains the original top20 gate,
and all rows in this champion-intraday family still have negative realized net with positive
unrealized carrying the headline return.

The useful mechanism is narrower:

1. Using the rank beyond Top-X can help the wider top50 scanner gate.
2. The default bucket rule lets strong top-ranked names in slightly earlier while forcing rank >20
   to show stronger intraday evidence.
3. For top20, the same looseness seems unnecessary; the existing gate already concentrates enough.
4. Future rank-aware work should target sizing/revalidation or a scanner-aware arm/trigger module,
   not blindly swap this intraday confirmer into the realized George-range strategy family.

## Next Sweep

Recommended next set:

- Keep this branch's scanner context/tag plumbing.
- Add a rank-aware sizing/revalidation consumer for the current intraday champion stack:
  rank 1-10 modestly larger, rank 11-20 normal, rank >20 smaller or revalidated stricter.
- Separately design a scanner-context consumer for the realized `arm -> entry_trigger ->
  intraday_sizing` architecture instead of replacing its daily `entry_selection` slot with an
  intraday phase.
