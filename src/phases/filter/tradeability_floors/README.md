# phases/filter/tradeability_floors

The tradeability **filter** phase (#233 / #238): eligibility floors, runs before the universe.

- **What it holds:** `tradeability_floors.py` (consumer phase) + its test mirror.
- **Model:** a name is eligible on date D iff latest close ≥ `min_price` (10.0) AND
  trailing-`adv_window` (20d) mean dollar volume ≥ `min_avg_dollar_volume` (100M). The floor
  math is applied LIVE inside `runtime.universe_select.select_live_universe`; this phase
  EMITS the live-selected eligible set (`qc._ranked_today` ∩ active, sorted) as
  `bar_state.eligible`. No rank, no cap, no Ichimoku.
- **Live, not artifact (#238):** the precomputed `qc._eligible` file is RETIRED (the universe
  is computed live from QC's coarse feed). Params carried for provenance (they MUST mirror
  the lean_entry universe knobs). Fail-loud: `_ranked_today` None → raise; empty → empty list
  (no raise).
- **What goes here:** changes to the floor consumption / fail-loud semantics only. Rank,
  cap, and selection do NOT go here.
