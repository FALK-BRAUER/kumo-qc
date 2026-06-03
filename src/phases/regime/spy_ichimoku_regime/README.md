# spy_ichimoku_regime

A `regime`-kind phase: gates new entries on the **SPY daily Ichimoku** being bullish
(Tenkan > Kijun and price ≥ cloud-bottom). George's Ichimoku frame applied to the index.

- **What's here:** `spy_ichimoku_regime.py` (the `SpyIchimokuRegime` phase), its `__init__.py`.
- **Why it exists:** #342 — the SPY-200MA gate did not catch the Jan 3-14 2025 chop (SPY was above
  its 200MA). SPY Tenkan < Kijun did, for the whole window. This gate blocks that regime.
- **What does NOT go here:** per-stock signal logic (that's `phases/signal/`), VIX gating
  (`phases/regime/vix_percentile/`), or the SPY-200MA gate (`phases/regime/spy_200ma/`).
- **Contract:** enabled + can't-assess → fail-CLOSED (block, #261-7); `enabled=False` → skip.
  SPY series via `qc.history` (single code path local+cloud).
