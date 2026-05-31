# phases/universe/dv_rank_cap

The universe phase: **exposes the live-selected ranked order** (#220 / #238). Before signal.

- **What it holds:** `dv_rank_cap.py` (consumer phase) + its test mirror.
- **Model:** consumes the LIVE ranked order `qc._ranked_today` — computed once-daily by
  `runtime.lean_entry._coarse_selection` via `runtime.universe_select.select_live_universe`
  (filter floors → rank by dollar-volume DESC, ties ticker ASC → cap to `lean_entry.COARSE_MAX`).
  NO stored universe file (the 326 scar). Emits `ranked_candidates` IN RANK ORDER — the #182
  fix (iterate the live ranked list, never the active set).
- **#238 dedup:** this phase carries NO `coarse_max` param — the cap (scan breadth, NOT a
  position count) is the single `lean_entry.COARSE_MAX` applied in the live selection; a second
  copy here was dead + drift-prone.
- **What goes here:** order-preservation + fail-loud consumption only. Floors + rank + cap are
  in `select_live_universe`; selection lives in `signal/bct_score_full`. Narrow the universe by
  raising a floor or lowering `lean_entry.COARSE_MAX`, never a position/slot count.
