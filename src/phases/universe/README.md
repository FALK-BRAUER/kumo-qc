# phases/universe

Universe-kind phases: **rank + cap** the filter's eligible set into the scan list.

- **What it holds:** universe phases (`<impl>/<impl>.py` + test mirror). Currently
  `dv_rank_cap` (rank by dollar-volume DESC, cap to `coarse_max`, #220).
- **What goes here:** ranking criteria + scan-breadth caps over the *already-eligible* set,
  emitting `ranked_candidates` in rank order. Order must be deterministic + identical
  local+cloud (the #182 fix).
- **What doesn't:** tradeability floors (→ `filter`), signal scoring/selection (→ `signal`),
  position/slot counts (forbidden — `coarse_max` is scan breadth, not a position cap).
