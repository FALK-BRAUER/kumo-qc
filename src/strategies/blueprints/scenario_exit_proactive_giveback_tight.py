"""#398 FY2025 variant: proactive exit with tighter giveback capture."""
from __future__ import annotations

from phases.exit.proactive_strength_exit.proactive_strength_exit import ProactiveStrengthExit
from strategies.blueprints.scenario_exit_george_factory import george_exit_config

CONFIG = george_exit_config(
    name="scenario-exit-proactive-giveback-tight",
    proactive=ProactiveStrengthExit.Params(
        target_pct=0.10,
        min_peak_pct=0.04,
        giveback_from_peak_pct=0.015,
    ),
)
LEAN_ENTRY = True
