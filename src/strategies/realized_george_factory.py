"""Shared builder for non-fixture realized George-range strategy candidates."""
from __future__ import annotations

from engine.config import Slot, StrategyConfig
from phases.arm.stub_arm.stub_arm import StubArm
from phases.diagnostics.chart_emit.chart_emit import ChartEmit
from phases.diagnostics.version_marker.version_marker import VersionMarker
from phases.entry_selection.resistance_proximity_filter.resistance_proximity_filter import (
    ResistanceProximityFilter,
)
from phases.entry_trigger.stub_trigger.stub_trigger import StubEntryTrigger
from phases.exit.proactive_strength_exit.proactive_strength_exit import ProactiveStrengthExit
from phases.intraday_sizing.stub_intraday_sizer.stub_intraday_sizer import StubIntradaySizer
from phases.ranking.score_dv_ranking.score_dv_ranking import ScoreDvRanking
from phases.regime.market_breadth_gate.market_breadth_gate import MarketBreadthGate
from phases.signal.tier1_high_conviction.tier1_high_conviction import Tier1HighConviction
from phases.stops_initial.support_atr_stop.support_atr_stop import SupportAtrStop
from phases.trail.position_path_tracker.position_path_tracker import PositionPathTracker
from phases.universe.dv_rank_cap.dv_rank_cap import DvRankCap


def realized_george_config(
    *,
    name: str,
    proactive: ProactiveStrengthExit.Params,
) -> StrategyConfig:
    """Build a deployable #408-style realized candidate.

    The archived scenario blueprints are fixtures. This builder keeps the same George-range phase
    stack, but makes the resulting configs non-fixtures so they can be tested as real candidates.
    """
    return StrategyConfig(
        name=name,
        version="1.0.0",
        is_fixture=False,
        continuous_weekly=True,
        phases={
            "universe": Slot(impl=DvRankCap, params=DvRankCap.Params()),
            "signal": Slot(impl=Tier1HighConviction, params=Tier1HighConviction.Params()),
            "regime": [
                Slot(
                    impl=MarketBreadthGate,
                    params=MarketBreadthGate.Params(
                        pct_threshold=0.40,
                        missing_breadth_blocks=False,
                    ),
                )
            ],
            "ranking": Slot(impl=ScoreDvRanking, params=ScoreDvRanking.Params()),
            "entry_selection": Slot(
                impl=ResistanceProximityFilter,
                params=ResistanceProximityFilter.Params(buffer_pct=0.02),
            ),
            "arm": Slot(impl=StubArm, params=StubArm.Params()),
            "entry_trigger": Slot(impl=StubEntryTrigger, params=StubEntryTrigger.Params(near_pct=0.015)),
            "intraday_sizing": Slot(
                impl=StubIntradaySizer,
                params=StubIntradaySizer.Params(position_pct=0.04),
            ),
            "stops_initial": Slot(impl=SupportAtrStop, params=SupportAtrStop.Params(atr_mult=0.5)),
            "trail": Slot(impl=PositionPathTracker, params=PositionPathTracker.Params()),
            "exit_hard": [Slot(impl=ProactiveStrengthExit, params=proactive)],
            "diagnostics": [
                Slot(impl=VersionMarker, params=VersionMarker.Params()),
                Slot(impl=ChartEmit, params=ChartEmit.Params()),
            ],
        },
    )
