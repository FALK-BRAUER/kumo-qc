# phases/sizing/

The **sizing** phase kind: turn confirmed+ranked candidates into concrete `OrderIntent`s — *how
much capital does each name get?* Runs after `entry_timing`, before the exits. The CHARTER rule:
exposure is governed by a **% gross-exposure heat-cap** (cash), NEVER by count caps / fixed slots /
time exits.

- **Holds:** one subdir per impl (`<impl>/<impl>.py` + `README.md`), plus `library.py` — the
  `SIZING_PHASES` catalog (typed tuple of DIRECT CLASS REFS for sweep discovery; ADR D3).
- **Members:**
  - `flat_pct_heatcap` — the champion-asis sizer: flat `position_pct` per name + committed-cash
    heat-cap. IGNORES the X/4 entry-confirm score.
  - `score_tier_heatcap` — the score-aware sizer: the published X/4 (`qc._entry_confirm`) BINDS on
    size via the methodology tiers (4/4 full · 3/4 75% · 2/4 50% · <2 no-entry), COMPOSED WITH the
    same committed-cash heat-cap. The reference for score-driven sizing.
- **Contract:** reads `ctx.bar_state.sized_orders` (stubs from upstream), fills each at its target
  value bounded by the cash heat-cap, writes back the filled `OrderIntent`s; `blocked` always False;
  declares `PHASE_KIND="sizing"`, a `version_marker`, `Params.space()`, and `COMPLEXITY`.
- **Does NOT:** select/confirm candidates (`signal`/`entry_selection`), order mechanics
  (`entry_timing`), or exits. No count caps, no fixed slots, no time exits (charter).
