# phases/universe/dv_rank_cap

The universe phase: **ranks + caps the filter's eligible set** (#220 / #238 / R1). Before signal.

- **What it holds:** `dv_rank_cap.py` (the rank+cap phase) + its test mirror.
- **Model (R1 un-fuse):** consumes `bar_state.eligible` (emitted by the FILTER phase,
  tradeability_floors) and ranks it via `runtime.universe_select.rank_and_cap`: dollar-volume
  DESC (ties ticker ASC) using `qc._trailing_dv`, capped to `qc.COARSE_MAX`. Emits
  `ranked_candidates` IN RANK ORDER — the #182 fix (iterate the ranked list, never the active
  set). NO stored universe file (the 326 scar).
- **Upstream:** `REQUIRES_UPSTREAM = ["filter"]` — the engine validates against phase KINDS
  (not provides-strings); "filter" PROVIDES "eligible" and precedes "universe" in PHASE_ORDER.
- **#238 dedup:** this phase carries NO `coarse_max` param — the cap (scan breadth, NOT a
  position count) is the single `lean_entry.COARSE_MAX`, read off qc; a second copy here was
  dead + drift-prone.
- **What goes here:** rank-order + cap consumption only. Floors are in the filter phase;
  selection lives in `signal/bct_score_full`. Narrow the universe by raising a floor (filter)
  or lowering `lean_entry.COARSE_MAX`, never a position/slot count.
