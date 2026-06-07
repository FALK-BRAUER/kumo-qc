"""#398 FY2025 variant: scratch stack with tighter post-MFE loss control."""
from __future__ import annotations

from phases.exit.proactive_strength_exit.proactive_strength_exit import ProactiveStrengthExit
from phases.exit.scratch_flat_exit.scratch_flat_exit import ScratchFlatExit
from strategies.blueprints.scenario_exit_george_factory import george_exit_config

CONFIG = george_exit_config(
    name="scenario-exit-proactive-scratch-tight-risk",
    scratch=ScratchFlatExit.Params(
        no_progress_days=3,
        min_mfe_pct=0.02,
        scratch_band_pct=0.003,
        max_loss_after_mfe_pct=0.01,
    ),
    proactive=ProactiveStrengthExit.Params(
        target_pct=0.06,
        min_peak_pct=0.05,
        giveback_from_peak_pct=0.015,
    ),
)
LEAN_ENTRY = True
