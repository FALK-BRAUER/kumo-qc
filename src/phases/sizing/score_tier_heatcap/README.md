# sizing/score_tier_heatcap

The **score-aware sizer** — the impl that makes the entry-confirm **X/4 score BIND on SIZE** (the
methodology sizing tiers). This is where the §4 Gate-2 score earns its keep: 4/4 names claim more
capital than 2/4 names, instead of `flat_pct_heatcap`'s flat `position_pct` for every confirmed name.

- **Holds:** `score_tier_heatcap.py` (the `ScoreTierHeatcap` phase + the pure `_tier` curve), its
  `.Params` (`position_pct` + the three tier fractions `full`/`three_quarter`/`half` + `min_score`),
  the `space()` sweep axes (5 → grid 243), and `COMPLEXITY` (`free_params=5`).
- **The tier curve (methodology §4):** reads each candidate's X/4 from `qc._entry_confirm[ticker]`
  (case-insensitive on the canonical ticker) → tier multiplier:
  **4/4 → `full` (1.00) · 3/4 → `three_quarter` (0.75) · 2/4 → `half` (0.50) · <`min_score` → 0.0
  (no entry)**. Per-name target = `position_pct × tier × portfolio_value`.
- **Heat-cap composition:** the tier sets the PER-NAME target; the committed-cash gross heat-cap
  (carried VERBATIM from `flat_pct_heatcap`) then BOUNDS total exposure — ranked candidates fill at
  their tier target until cash is exhausted (oracle break, not continue). Smaller tiers let more
  names fit; a 4/4 name claims more cash than a 2/4 name; both are cash-bounded.
- **Missing-score edge (FLAGGED contract decision):** a candidate with NO `qc._entry_confirm` entry
  (the scorer didn't run / wasn't wired) is **DECLINED** (tier 0.0 = no entry), NOT sized flat. A
  wiring bug must fail VISIBLY (zero orders → liveness CI #251 trips), never masquerade as flat
  sizing. The score is the single source of authority; absence of a score = absence of authority
  to enter.
- **Defaults are methodology-canonical:** `position_pct=0.10` (== champion-entry's flat size, so a
  4/4 name sizes IDENTICALLY to flat; the delta is 3/4 & 2/4 size DOWN), tiers `1.00/0.75/0.50`,
  `min_score=2`. Tier fractions are PARAMS (sweepable) so the curve can steepen/flatten without
  forking the impl.
- **Tests:** `tests/phases/sizing/score_tier_heatcap/` (FIRE 4/4·3/4·2/4 + DECLINE <2/missing +
  heat-cap composition + edge + the tier→size golden-master + determinism).
- **Charter:** single code path (local == cloud); the heat-cap is the only exposure rule (KEPT);
  NO count caps / time exits / fixed slots.
