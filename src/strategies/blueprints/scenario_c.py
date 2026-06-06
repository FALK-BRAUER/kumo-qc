"""#386 Scenario C - "Conviction-Core / Support-ATR".

Scenario C keeps A's conviction-core daily family, then swaps stop/exit behavior and tightens several
params. This proves fine-grained slot modularity: A and C share the engine and most structural phases,
while the stop and exit modules can change independently.

is_fixture=True: the intraday trigger/sizer are still the M1 proof modules, not the final deployable
entry logic.
"""
from __future__ import annotations

from engine.config import Slot, StrategyConfig
from phases.arm.stub_arm.stub_arm import StubArm
from phases.diagnostics.chart_emit.chart_emit import ChartEmit
from phases.diagnostics.version_marker.version_marker import VersionMarker
from phases.entry_selection.resistance_proximity_filter.resistance_proximity_filter import ResistanceProximityFilter
from phases.entry_trigger.stub_trigger.stub_trigger import StubEntryTrigger
from phases.exit.multi_metric_confirm_exit.multi_metric_confirm_exit import MultiMetricConfirmExit
from phases.intraday_sizing.stub_intraday_sizer.stub_intraday_sizer import StubIntradaySizer
from phases.ranking.score_dv_ranking.score_dv_ranking import ScoreDvRanking
from phases.regime.market_breadth_gate.market_breadth_gate import MarketBreadthGate
from phases.signal.tier1_high_conviction.tier1_high_conviction import Tier1HighConviction
from phases.stops_initial.support_atr_stop.support_atr_stop import SupportAtrStop
from phases.universe.dv_rank_cap.dv_rank_cap import DvRankCap

CONFIG = StrategyConfig(
    name="scenario-c-support-atr",
    version="1.0.0",
    is_fixture=True,
    continuous_weekly=True,
    phases={
        "universe": Slot(impl=DvRankCap, params=DvRankCap.Params()),
        "signal": Slot(impl=Tier1HighConviction, params=Tier1HighConviction.Params()),
        "regime": [Slot(impl=MarketBreadthGate, params=MarketBreadthGate.Params(
            pct_threshold=0.40,
            missing_breadth_blocks=False,
        ))],
        "ranking": Slot(impl=ScoreDvRanking, params=ScoreDvRanking.Params()),
        "entry_selection": Slot(impl=ResistanceProximityFilter, params=ResistanceProximityFilter.Params(buffer_pct=0.02)),
        "arm": Slot(impl=StubArm, params=StubArm.Params()),
        "entry_trigger": Slot(impl=StubEntryTrigger, params=StubEntryTrigger.Params(near_pct=0.015)),
        "intraday_sizing": Slot(impl=StubIntradaySizer, params=StubIntradaySizer.Params(position_pct=0.04)),
        "stops_initial": Slot(impl=SupportAtrStop, params=SupportAtrStop.Params(atr_mult=0.5)),
        "exit_hard": [Slot(impl=MultiMetricConfirmExit, params=MultiMetricConfirmExit.Params(confirm_n=2))],
        "diagnostics": [
            Slot(impl=VersionMarker, params=VersionMarker.Params()),
            Slot(impl=ChartEmit, params=ChartEmit.Params()),
        ],
    },
)
LEAN_ENTRY = True
