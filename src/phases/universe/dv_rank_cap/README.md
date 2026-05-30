# phases/universe/dv_rank_cap

The universe phase: **rank + cap** (#220). Runs after the filter, before signal.

- **What it holds:** `dv_rank_cap.py` (consumer phase) + its test mirror.
- **Model:** consumes the precomputed ranked candidate artifact (built offline from the
  filter artifact: eligible set → rank by dollar-volume DESC, ties ticker ASC → cap to
  `coarse_max`, default 9999 = unbounded scan breadth). Emits `ranked_candidates` IN RANK
  ORDER — the #182 fix (iterate the precomputed list, never the active set).
- **What goes here:** rank/cap consumption + order-preservation + fail-loud semantics
  only. The tradeability floors live in `filter/tradeability_floors`; selection lives in
  `signal/bct_score_full`. Narrow the universe by raising a floor or lowering `coarse_max`,
  never a position/slot count.
