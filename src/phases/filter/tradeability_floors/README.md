# phases/filter/tradeability_floors

The tradeability **filter** phase (#233): eligibility floors, runs before the universe.

- **What it holds:** `tradeability_floors.py` (consumer phase) + its test mirror.
- **Model:** a name is eligible on date D iff latest close ≥ `min_price` (10.0) AND
  trailing-`adv_window` (20d) mean dollar volume ≥ `min_avg_dollar_volume` (5M). Pure
  eligibility — no rank, no cap, no Ichimoku. Emits `bar_state.eligible`.
- **Artifact:** consumes the precomputed `scripts/build_filter.py` output
  (`date → {ticker: dv}`); the floor math lives in the precompute, params carried for
  provenance. Fail-loud: `_eligible` None → raise; missing date → empty (no raise).
- **What goes here:** changes to the floor consumption / fail-loud semantics only. Rank,
  cap, and selection do NOT go here.
