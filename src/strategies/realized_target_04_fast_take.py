"""Realized strategy candidate from #451: take strength earlier at +4%.

Archived FY2025 diagnostics for `target_04_fast_take` showed the highest closed-trade win rate
and profit factor in the George-range sweep. This module makes it a non-fixture candidate so it can
be combined with the opt-in LambdaMART scanner gate.
"""
from __future__ import annotations

from phases.exit.proactive_strength_exit.proactive_strength_exit import ProactiveStrengthExit
from strategies.realized_george_factory import realized_george_config

CONFIG = realized_george_config(
    name="realized-target-04-fast-take",
    proactive=ProactiveStrengthExit.Params(target_pct=0.04),
)

LEAN_ENTRY = True
