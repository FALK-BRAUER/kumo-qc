# #268 side-finding — CONFIRMED intra-day DOUBLE-REBALANCE (separate bug, parity-neutral)

**Verdict: REAL double-rebalance, NOT a benign dedup/no-op.** Flagged for its own ticket — it
is NOT the #268 parity cause (it is present on BOTH sides, so it cancels in local-vs-cloud), but
it materially over-trades the champion on both sides.

## Evidence (local BT order-events, 2026-05-31_23-36-54)
Per trading day the engine submits entries on TWO time slices, the second picking DIFFERENT names:

```
2025-01-02 BUY submits (UTC):
  21:00Z (16:00 ET, equity close):  C CEG GS JPM KMI META MRVL SPOT T TSM   (n=10)
  21:15Z (16:15 ET, VIX CT close):  AXP AZO DASH EQT EXPE HPE KR MCO NET RBLX (n=10)
  batch1 ∩ batch2 = 0  → 20 DISTINCT entries that day

2025-01-14:  21:00Z {BSX,DAL,UAL} + 21:15Z {ET,MMM,WMB}  → 6 distinct
```

## Mechanism
- The algorithm subscribes the **VIX index** (`Index-usa-VIX`), which the market-hours DB places on
  **Central Time** → its session-close slice arrives at **16:15 ET**, 15 min after the 16:00-ET
  equity-close slice.
- `on_data` runs the FULL phase pipeline (universe→signal→sizing→entry) **unconditionally on every
  slice**. So it rebalances at 16:00 (equity close) AND again at 16:15 (VIX close).
- The 16:15 batch is the **next-ranked N**: the 16:00 batch's orders are pending → the signal
  phase's `get_open_orders` check excludes them → the second pass selects the next qualifiers.
  Net effect: the strategy enters ~2× the intended names per active day.

## Why it does NOT explain #268
Both LOCAL and CLOUD subscribe VIX and both double-rebalance (cloud shows the same 20:15/21:15Z
second bucket). So it is PARITY-NEUTRAL — it cancels in the local-vs-cloud diff and is not the
breadth residual (that is the 1-bar fill-grid offset; see 268-breadth-turnover-2025.md). But it
DOES inflate the absolute champion trade count on both sides (20 vs an intended 10/day on active
days) → a real strategy-behavior bug worth its own fix.

## Recommended fix (separate ticket — HELD, champion-behavior change)
Add a **once-per-day rebalance gate**: run the entry pipeline only on the first (or the
equity-close) slice of each trading day, not on every slice. Options: gate on `qc.time.date()`
changing, or restrict the rebalance to the primary-equity-close slice / a scheduled event, or
exclude the VIX slice from triggering the entry pipeline (VIX is a regime input, not a trade
trigger). This changes the champion's measured behavior on BOTH sides → needs a fresh baseline +
HQ gate; do NOT fold it into the #268 timing fix (orthogonal). Verify post-fix that entries drop
to one batch/day and the trade count roughly halves on active days.
