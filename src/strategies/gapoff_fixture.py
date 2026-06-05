"""EXP-1 (Falk): gap-OFF — S1 stack with the intraday gap-vol-confirm REMOVED, entries fire via the
default market-on-open path (is_fixture=True bypasses the champion entry-confirm fail-loud guard). Tests
whether the intraday gap-confirm MATTERS: gap-off ≈ S1 → gap is a no-op (S1 = daily-score+gates+heatcap+
let-run, confirm is window-dressing); gap-off materially differs → the gap phase does real work. The ONLY
change vs S1 = drop BctIntradayGapVolConfirm + entry_timing MOO instead of ConfirmedMarketEntry.
"""
from __future__ import annotations
from engine.config import Slot, StrategyConfig
from phases.diagnostics.chart_emit.chart_emit import ChartEmit
from phases.diagnostics.version_marker.version_marker import VersionMarker
from phases.entry_selection.preflight_staleness.preflight_staleness import PreFlightStaleness
from phases.entry_timing.confirmed_market_entry.confirmed_market_entry import ConfirmedMarketEntry
from phases.exit.cloud_adherence_trail.cloud_adherence_trail import CloudAdherenceTrail
from phases.protective_stop.cloud_protective_stop.cloud_protective_stop import CloudProtectiveStop
from phases.regime.spy_200ma.spy_200ma import SpySma200
from phases.regime.vix_percentile.vix_percentile import VixPercentile
from phases.signal.bct_score_full.bct_score_full import BctScoreFull
from phases.sizing.flat_pct_heatcap.flat_pct_heatcap import FlatPctHeatcap
from phases.universe.dv_rank_cap.dv_rank_cap import DvRankCap

CONFIG = StrategyConfig(
    name="gapoff-fixture", version="1.0.0", is_fixture=True, continuous_weekly=True,
    phases={
        "universe": Slot(impl=DvRankCap, params=DvRankCap.Params()),
        "signal": Slot(impl=BctScoreFull, params=BctScoreFull.Params(min_score=7, parabolic_threshold=0.25)),
        "regime": [Slot(impl=SpySma200, params=SpySma200.Params()),
                   Slot(impl=VixPercentile, params=VixPercentile.Params(vix_percentile_enabled=False))],
        "sizing": Slot(impl=FlatPctHeatcap, params=FlatPctHeatcap.Params(position_pct=0.05, resolution="intraday")),
        "exit_hard": [Slot(impl=CloudAdherenceTrail, params=CloudAdherenceTrail.Params())],
        "entry_selection": [Slot(impl=PreFlightStaleness, params=PreFlightStaleness.Params())],
        "entry_timing": Slot(impl=ConfirmedMarketEntry, params=ConfirmedMarketEntry.Params()),
        "protective_stop": Slot(impl=CloudProtectiveStop, params=CloudProtectiveStop.Params()),
        "diagnostics": [Slot(impl=VersionMarker, params=VersionMarker.Params()),
                        Slot(impl=ChartEmit, params=ChartEmit.Params())],
    })
LEAN_ENTRY = True
