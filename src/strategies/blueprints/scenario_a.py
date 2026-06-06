"""#386 Scenario A — "Conviction-Core / Cloud-Adherence" (defensive let-run).

The #254-catalog composition for A (modularization proof): a DAY-phase pipeline of Tier-1 conviction
selection + breadth-gated regime + resistance-proximity filtering + cloud-adherence exits, fired on the
two-clock intraday entry (shared with C). vs B = a different module in every slot. The engine/framework
is BYTE-IDENTICAL across A/B/C — only this {slot: module(params)} map differs.

is_fixture=True: the intraday entry mechanism is the M1 stub (StubEntryTrigger/StubIntradaySizer) — the
proof is the DAY-phase modular variation, not a deployable strategy (M-series tunes the real intraday).
"""
from __future__ import annotations

from engine.config import Slot, StrategyConfig
from phases.diagnostics.chart_emit.chart_emit import ChartEmit
from phases.diagnostics.version_marker.version_marker import VersionMarker
# day-phase catalog modules (the A-specific composition)
from phases.universe.dv_rank_cap.dv_rank_cap import DvRankCap
from phases.signal.tier1_high_conviction.tier1_high_conviction import Tier1HighConviction
from phases.regime.market_breadth_gate.market_breadth_gate import MarketBreadthGate
from phases.ranking.score_dv_ranking.score_dv_ranking import ScoreDvRanking
from phases.entry_selection.resistance_proximity_filter.resistance_proximity_filter import ResistanceProximityFilter
from phases.exit.cloud_adherence_trail.cloud_adherence_trail import CloudAdherenceTrail  # trail
from phases.exit.cloud_breach_exit.cloud_breach_exit import CloudBreachExit  # exit
# two-clock carry + the shared intraday entry (M1 stubs; the day-phase variation is the isolated proof)
from phases.arm.stub_arm.stub_arm import StubArm
from phases.entry_trigger.stub_trigger.stub_trigger import StubEntryTrigger
from phases.intraday_sizing.stub_intraday_sizer.stub_intraday_sizer import StubIntradaySizer

CONFIG = StrategyConfig(
    name="scenario-a-conviction-core",
    version="1.0.0",
    is_fixture=True,
    continuous_weekly=True,
    phases={
        # --- DAY decision chain (the A-specific catalog modules) ---
        "universe": Slot(impl=DvRankCap, params=DvRankCap.Params()),
        "signal": Slot(impl=Tier1HighConviction, params=Tier1HighConviction.Params()),
        "regime": [Slot(impl=MarketBreadthGate, params=MarketBreadthGate.Params(pct_threshold=0.50))],
        "ranking": Slot(impl=ScoreDvRanking, params=ScoreDvRanking.Params()),
        "entry_selection": Slot(impl=ResistanceProximityFilter, params=ResistanceProximityFilter.Params(buffer_pct=0.03)),
        "arm": Slot(impl=StubArm, params=StubArm.Params()),
        # --- INTRADAY execution (shared A/C two-clock entry; the day-phase variation is the proof) ---
        "entry_trigger": Slot(impl=StubEntryTrigger, params=StubEntryTrigger.Params()),
        "intraday_sizing": Slot(impl=StubIntradaySizer, params=StubIntradaySizer.Params()),
        # stops_initial CloudBottomStop deferred (two-clock post-fire stop module — built next)
        # --- exits (day) ---
        "exit_hard": [Slot(impl=CloudAdherenceTrail, params=CloudAdherenceTrail.Params()),
                      Slot(impl=CloudBreachExit, params=CloudBreachExit.Params())],
        "diagnostics": [Slot(impl=VersionMarker, params=VersionMarker.Params()),
                        Slot(impl=ChartEmit, params=ChartEmit.Params())],
    },
)
LEAN_ENTRY = True
