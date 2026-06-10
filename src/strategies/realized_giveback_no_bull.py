"""Realized strategy candidate from #451: tight giveback without bullish-structure veto.

This is the first follow-up candidate after the scanner-overlay work showed misleading headline
returns dominated by unrealized PnL. It promotes the best realized #408 George-range variant into
a reproducible, non-fixture strategy module:

- `giveback_tight_no_bull`
- FY2025 closed-trade PnL: +$24,815.07 in the archived sweep diagnostics
- closed win rate: 93.2% over 117 closed trades

It is not the production champion. It is the next strategy candidate to rerun with realized vs
unrealized diagnostics before any champion decision.
"""
from __future__ import annotations

from phases.exit.proactive_strength_exit.proactive_strength_exit import ProactiveStrengthExit
from strategies.realized_george_factory import realized_george_config

CONFIG = realized_george_config(
    name="realized-giveback-no-bull",
    proactive=ProactiveStrengthExit.Params(
        target_pct=0.06,
        min_peak_pct=0.04,
        giveback_from_peak_pct=0.015,
        require_still_bullish=False,
    ),
)

LEAN_ENTRY = True
