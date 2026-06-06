"""#398 FY2025 variant: patient scratch plus wider profit target."""
from __future__ import annotations

from phases.exit.proactive_strength_exit.proactive_strength_exit import ProactiveStrengthExit
from phases.exit.scratch_flat_exit.scratch_flat_exit import ScratchFlatExit
from strategies.blueprints.scenario_exit_george_factory import george_exit_config

CONFIG = george_exit_config(
    name="scenario-exit-proactive-scratch-patient",
    scratch=ScratchFlatExit.Params(
        no_progress_days=5,
        min_mfe_pct=0.03,
        scratch_band_pct=0.004,
        max_loss_after_mfe_pct=0.025,
    ),
    proactive=ProactiveStrengthExit.Params(
        target_pct=0.08,
        min_peak_pct=0.06,
        giveback_from_peak_pct=0.035,
    ),
)
LEAN_ENTRY = True
