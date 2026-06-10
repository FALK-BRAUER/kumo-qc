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

CONFIG = StrategyConfig(
    name="realized-giveback-no-bull",
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
        "exit_hard": [
            Slot(
                impl=ProactiveStrengthExit,
                params=ProactiveStrengthExit.Params(
                    target_pct=0.06,
                    min_peak_pct=0.04,
                    giveback_from_peak_pct=0.015,
                    require_still_bullish=False,
                ),
            )
        ],
        "diagnostics": [
            Slot(impl=VersionMarker, params=VersionMarker.Params()),
            Slot(impl=ChartEmit, params=ChartEmit.Params()),
        ],
    },
)

LEAN_ENTRY = True
