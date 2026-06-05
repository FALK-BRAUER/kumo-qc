"""#TL score-threshold screen factory — S1 champion with a parametrized BCT min_score (signal SUPPLY,
NOT the dead entry-FEATURE selection #349). Lower min_score = MORE score-N candidates from the SAME
326-ticker local universe = more shots at the fat tail without skipping/perturbing held names (the
locally-testable proxy for universe-expansion, which is cloud-only at the 326 local cap). gross-cap
still governs sizing. The ONLY change vs S1 is signal.min_score. champion modules UNTOUCHED.
"""
from __future__ import annotations

from engine.config import Slot, StrategyConfig
from phases.diagnostics.chart_emit.chart_emit import ChartEmit
from phases.diagnostics.version_marker.version_marker import VersionMarker
from phases.entry_selection.bct_intraday_gap_vol_confirm.bct_intraday_gap_vol_confirm import BctIntradayGapVolConfirm
from phases.entry_selection.preflight_staleness.preflight_staleness import PreFlightStaleness
from phases.entry_timing.confirmed_market_entry.confirmed_market_entry import ConfirmedMarketEntry
from phases.exit.cloud_adherence_trail.cloud_adherence_trail import CloudAdherenceTrail
from phases.protective_stop.cloud_protective_stop.cloud_protective_stop import CloudProtectiveStop
from phases.regime.spy_200ma.spy_200ma import SpySma200
from phases.regime.vix_percentile.vix_percentile import VixPercentile
from phases.signal.bct_score_full.bct_score_full import BctScoreFull
from phases.sizing.flat_pct_heatcap.flat_pct_heatcap import FlatPctHeatcap
from phases.universe.dv_rank_cap.dv_rank_cap import DvRankCap


def make_config(min_score: int = 7) -> StrategyConfig:
    """S1 champion with signal min_score = `min_score` (the ONLY change vs S1)."""
    return StrategyConfig(
        name=f"score-screen-s{min_score}",
        version="1.0.0",
        is_fixture=False,
        continuous_weekly=True,
        phases={
            "universe": Slot(impl=DvRankCap, params=DvRankCap.Params()),
            "signal": Slot(impl=BctScoreFull, params=BctScoreFull.Params(min_score=min_score, parabolic_threshold=0.25)),
            "regime": [
                Slot(impl=SpySma200, params=SpySma200.Params()),
                Slot(impl=VixPercentile, params=VixPercentile.Params(vix_percentile_enabled=False)),
            ],
            "sizing": Slot(impl=FlatPctHeatcap, params=FlatPctHeatcap.Params(position_pct=0.05, resolution="intraday")),
            "exit_hard": [Slot(impl=CloudAdherenceTrail, params=CloudAdherenceTrail.Params())],
            "entry_selection": [
                Slot(impl=PreFlightStaleness, params=PreFlightStaleness.Params()),
                Slot(impl=BctIntradayGapVolConfirm, params=BctIntradayGapVolConfirm.Params()),
            ],
            "entry_timing": Slot(impl=ConfirmedMarketEntry, params=ConfirmedMarketEntry.Params()),
            "protective_stop": Slot(impl=CloudProtectiveStop, params=CloudProtectiveStop.Params()),
            "diagnostics": [
                Slot(impl=VersionMarker, params=VersionMarker.Params()),
                Slot(impl=ChartEmit, params=ChartEmit.Params()),
            ],
        },
    )
