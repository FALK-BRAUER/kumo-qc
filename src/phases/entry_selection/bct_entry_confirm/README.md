# entry_selection/bct_entry_confirm

The methodology **§4 Gate-2 ENTRY-CONFIRMATION** gate — the P&L unlock (#253 Phase-1). GATES the
qualified+ranked candidates (signal-phase `sized_orders` stubs) so a name FIRES only on a
CONFIRMED entry. #228 proved the qualify SCORER already matches methodology, so the −0.616 Sharpe
is the missing entry trigger — this phase adds it.

- **Holds:** `bct_entry_confirm.py` (the phase + the pure `evaluate_gate2` scorer + `ComponentScore`),
  its `.Params` (MACD periods, `volume_gate_mult`, `tenkan_pullback_tol`, `gap_up_threshold`,
  `min_confirm`), the `space()` sweep axes (4 → grid 81), and `COMPLEXITY` (`free_params=4`).
- **The 4 components (§2):** C1 Regime (price>cloud AND T>K) · C2 T-Bounce (pullback to Tenkan +
  reclaim, with degrade guards) · C3 MACD 12/26/9 (only neg-turning-down fails) · C4 Volume
  (≥1.0× 20-day avg = the GATE). SCORED X/4; qualify ≥`min_confirm`/4 with **regime + volume
  MANDATORY**. The X/4 score is published on `qc._entry_confirm[ticker]` for a future methodology sizer.
- **Reads:** maintained `qc._indicators` (`d_ichi`, `macd`, `macd_hist_window`, `vol_sma20`,
  `tbounce`) O(1)/candidate — NO per-bar history.
- **Methodology mapping + golden-master verdict + canonical-source FLAGS:**
  `research/methodology/bct-entry-confirm-reconciliation.md`.
- **Tests:** `tests/phases/entry_selection/bct_entry_confirm/` (FIRE/DECLINE/edge + the §4 Gate-2
  golden-master + determinism).
- **Does NOT:** Gate-1 rule-compliance, Gate-4 resistance-proximity, or Gate-5 order mechanics —
  those are phase-2 variants (#148/#150/#64 selection; #149/LimitPullback timing). This phase is the
  COPYABLE reference those variants follow.
