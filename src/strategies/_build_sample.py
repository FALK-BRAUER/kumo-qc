"""Build-closure test strategy (underscore = not a real strategy).

Enables sample_bct (signal), DISABLES sample_off (regime). The packager must:
- include phase_signal_sample_bct + its transitive shared helper + engine
- EXCLUDE sample_off (disabled)
"""
from __future__ import annotations

from engine.config import Slot, StrategyConfig
from phases.regime.sample_off.sample_off import SampleOff
from phases.signal.sample_bct.sample_bct import SampleBct

CONFIG = StrategyConfig(
    name="_build_sample",
    version="0.0.0",
    # is_fixture: a build-packager test sample (not a champion) — declares itself a fixture
    # to pass the #272 fail-loud entry+exit gate.
    is_fixture=True,
    phases={
        "signal": Slot(impl=SampleBct, params=SampleBct.Params(min_score=7)),
        "regime": Slot(impl=SampleOff, params=SampleOff.Params(enabled=False), enabled=False),
    },
)
