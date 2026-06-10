"""Realized strategy candidate from #451: let winners run to +8%.

Archived FY2025 diagnostics for `target_08_let_run` gave fewer trades with a stronger average
closed return. This module is the patient contrast cell for scanner-gated strategy sweeps.
"""
from __future__ import annotations

from phases.exit.proactive_strength_exit.proactive_strength_exit import ProactiveStrengthExit
from strategies.realized_george_factory import realized_george_config

CONFIG = realized_george_config(
    name="realized-target-08-let-run",
    proactive=ProactiveStrengthExit.Params(target_pct=0.08),
)

LEAN_ENTRY = True
