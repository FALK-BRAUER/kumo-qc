# phases/filter/tradeability_floors

The tradeability **filter** phase (#233 / #238 / R1): eligibility floors, applied FIRST.

- **What it holds:** `tradeability_floors.py` (the real floor phase) + its test mirror.
- **Model (R1 un-fuse):** the shared upstream (`runtime.lean_entry._coarse_selection`) builds
  `qc._bar_metrics = {ticker: (close, trailing_dv)}` once-daily (prefilter survivors + RAW
  trailing metrics, NO floors). This phase APPLIES the floors via
  `runtime.universe_select.apply_floors`: a name is eligible iff `close ≥ min_price` (10.0)
  AND `trailing_dv ≥ min_avg_dollar_volume` (100M). It emits the floored set ∩ active
  (case-insensitive, canonical uppercase, sorted) as `bar_state.eligible`. No rank, no cap,
  no Ichimoku — rank+cap is the universe phase's job.
- **Params:** `min_price` + `min_avg_dollar_volume` are FUNCTIONAL (drive the floor);
  `adv_window` (20) is PROVENANCE of the upstream trailing window (mirrors
  `lean_entry.ADV_WINDOW`; the mean is computed in `build_bar_metrics`, not here).
- **Fail-loud:** `_bar_metrics` None → raise (shared-upstream wiring bug; the guard lives here,
  the first consumer of the upstream metrics); empty `{}` → empty eligible (no raise).
- **What goes here:** changes to the floor math / fail-loud semantics only. Rank, cap, and
  selection do NOT go here.
