# phases/universe/dv_rank_cap

The universe phase: **exposes the live-selected ranked order** (#220 / #238 / Y). Before signal.

- **What it holds:** `dv_rank_cap.py` (the exposer phase) + its test mirror.
- **Model (Y, Falk):** consumes `qc._ranked_today` — the floored+ranked+capped selection
  computed once-daily at the SELECTION GATE (`lean_entry._coarse_selection`: `build_bar_metrics`
  → `apply_floors` → `rank_and_cap`, then subscribe only the qualifying set). Emits
  `ranked_candidates` IN RANK ORDER ∩ the truly-subscribed active set — the #182 fix (iterate
  the ranked list, never the active set). NO stored universe file (the 326 scar).
- **Upstream:** `REQUIRES_UPSTREAM = []` — it reads qc runtime state (`_ranked_today`, set by
  the selection gate before the engine runs), not an upstream bar_state output.
- **Fail-loud:** `_ranked_today` None → raise `UniverseLoadError` (selection-gate wiring bug;
  never pass-through-all); empty → empty candidates (no raise).
- **Diff-ladder:** logs a per-bar `TRACKED_CANDIDATES` rung (count + sha256 of the emitted
  ranked_candidates) — distinct from the once-daily `ACTIVE_SET` selection rung (lean_entry).
- **No `coarse_max` param:** the floors + DV rank + cap all live at the selection gate
  (`lean_entry`, single source). Narrow the universe by raising a floor or lowering
  `lean_entry.COARSE_MAX`, never a position/slot count.
- **What goes here:** order-preservation + fail-loud consumption only. Floors + rank + cap are
  at the selection gate; selection lives in `signal/bct_score_full`.
