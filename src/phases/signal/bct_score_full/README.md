# signal/bct_score_full

The canonical BCT **SIGNAL / QUALIFY** phase — *"does this name qualify?"* Scores each
universe candidate against George's 8-condition BCT Blue Flag checklist (weekly + daily
Ichimoku, ADX(9), 200-MA) via `score_symbol_native` (`phases/shared/oracle_helpers.py`),
keeps those with `score ≥ min_score`, blocks parabolic over-extensions, and emits
entry-priority-ordered `OrderIntent` stubs for the sizing phase.

- **Holds:** `bct_score_full.py` (the phase), its `.Params` (`min_score`,
  `parabolic_threshold`), the `space()` sweep axes, and the `COMPLEXITY` declaration.
- **Methodology mapping + golden-master verdict:** `research/methodology/bct-signal-reconciliation.md`.
- **Tests:** `tests/phases/signal/bct_score_full/` (FIRE/DECLINE/edge + the #228 methodology
  golden-master); scorer condition-logic in `tests/phases/shared/test_score_symbol_native.py`.
- **Does NOT:** entry timing (T-Bounce / MACD / volume = a separate `entry_timing` phase),
  sizing, or universe selection. **DO NOT modify the scorer logic** — champion-parity gated.
