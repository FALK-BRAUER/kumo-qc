# phases/filter

Filter-kind phases: the pre-universe **tradeability gate**. Runs before `universe`.

- **What it holds:** filter phases (`<impl>/<impl>.py` + test mirror). Currently
  `tradeability_floors` (price + dollar-volume eligibility floors, #233).
- **What goes here:** pure eligibility gates that decide whether a name is *tradeable*
  (liquid/priced enough), emitting `bar_state.eligible`. No rank, no cap, no Ichimoku.
- **What doesn't:** ranking/cap (→ `universe`), signal scoring/selection (→ `signal`),
  position-level eligibility (→ the entry-side `eligibility` kind, a different thing).
