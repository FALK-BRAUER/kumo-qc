# phases/universe

Universe-kind phases: **expose the live-selected ranked scan list** to the bar.

- **What it holds:** universe phases (`<impl>/<impl>.py` + test mirror). Currently
  `dv_rank_cap` (#220 / #238 / Y) — exposes `qc._ranked_today`, the floored+ranked+capped
  selection computed at the selection gate (`lean_entry._coarse_selection`), ∩ active in rank
  order.
- **What goes here:** consuming + order-preserving the live selection, emitting
  `ranked_candidates` in rank order. Order must be deterministic + identical local+cloud
  (the #182 fix).
- **What doesn't:** the tradeability floors + the DV rank + the cap (→ all at the SELECTION
  GATE, `lean_entry`, under Y — not a per-bar phase), signal scoring/selection (→ `signal`),
  position/slot counts (forbidden — `COARSE_MAX` is scan breadth, not a position cap).
