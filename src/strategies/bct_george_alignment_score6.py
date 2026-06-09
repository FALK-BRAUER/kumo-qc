"""bct-george-alignment-score6 — opt-in "almost BCT" scanner-alignment experiment.

This config is the score-6 sibling of `bct_george_alignment`: same phase stack and same
George-style ranking, but `BctScoreFull(min_score=6)` admits the "almost BCT" lane that George
often appears to select from. It is intentionally NOT the active CHAMPION and does not change
`dist/`.
"""
from __future__ import annotations

from engine.config import Slot, StrategyConfig
from phases.signal.bct_score_full.bct_score_full import BctScoreFull
from strategies.bct_george_alignment import CONFIG as SCORE7_CONFIG

_PHASES = dict(SCORE7_CONFIG.phases)
_PHASES["signal"] = Slot(
    impl=BctScoreFull,
    params=BctScoreFull.Params(min_score=6, parabolic_threshold=0.25),
)

CONFIG = StrategyConfig(
    name="bct-george-alignment-score6",
    version="0.1.0",
    is_fixture=False,
    continuous_weekly=SCORE7_CONFIG.continuous_weekly,
    phases=_PHASES,
)

LEAN_ENTRY = True
