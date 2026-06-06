"""#398 FY2025 variant: fast scratch plus lower proactive target."""
from __future__ import annotations

from phases.exit.proactive_strength_exit.proactive_strength_exit import ProactiveStrengthExit
from phases.exit.scratch_flat_exit.scratch_flat_exit import ScratchFlatExit
from strategies.blueprints.scenario_exit_george_factory import george_exit_config

CONFIG = george_exit_config(
    name="scenario-exit-proactive-scratch-fast",
    scratch=ScratchFlatExit.Params(
        no_progress_days=2,
        min_mfe_pct=0.015,
        scratch_band_pct=0.0075,
        max_loss_after_mfe_pct=0.015,
    ),
    proactive=ProactiveStrengthExit.Params(
        target_pct=0.05,
        min_peak_pct=0.04,
        giveback_from_peak_pct=0.02,
    ),
)
LEAN_ENTRY = True
