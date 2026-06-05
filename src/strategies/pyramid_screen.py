"""#340-C SIZING SCREEN factory — champion_pyramid (S1 + StagedRiskPyramid) parametrized by the add
SIZING variant only. SAME Pe-trigger / max_adds / gross-cap / S1 core across all variants, so the
screen ISOLATES sizing (V1 flat-$200 vs V2 position-fraction vs V3 conviction-weighted). champion_
pyramid.py is left UNTOUCHED (its Pe-rampup CONFIG keeps the 4c2fc8e40607 #340-B/gate-2 baseline hash);
the screen's three variants get their own config hashes via this factory.
"""
from __future__ import annotations

from engine.config import Slot, StrategyConfig
from phases.adds.staged_risk_pyramid.staged_risk_pyramid import StagedRiskPyramid
from phases.diagnostics.chart_emit.chart_emit import ChartEmit
from phases.diagnostics.version_marker.version_marker import VersionMarker
from phases.entry_selection.bct_intraday_gap_vol_confirm.bct_intraday_gap_vol_confirm import BctIntradayGapVolConfirm
from phases.entry_selection.preflight_staleness.preflight_staleness import PreFlightStaleness
from phases.entry_timing.confirmed_market_entry.confirmed_market_entry import ConfirmedMarketEntry
from phases.exit.cloud_adherence_trail.cloud_adherence_trail import CloudAdherenceTrail
from phases.portfolio_risk.gross_exposure_cap.gross_exposure_cap import GrossExposureCap
from phases.protective_stop.cloud_protective_stop.cloud_protective_stop import CloudProtectiveStop
from phases.regime.spy_200ma.spy_200ma import SpySma200
from phases.regime.vix_percentile.vix_percentile import VixPercentile
from phases.signal.bct_score_full.bct_score_full import BctScoreFull
from phases.sizing.flat_pct_heatcap.flat_pct_heatcap import FlatPctHeatcap
from phases.universe.dv_rank_cap.dv_rank_cap import DvRankCap


def make_config(variant: str) -> StrategyConfig:
    """S1 + StagedRiskPyramid with the given add-sizing `variant` (the ONLY axis the screen varies)."""
    return StrategyConfig(
        name=f"pyramid-screen-{variant}",
        version="1.0.0",
        is_fixture=False,
        continuous_weekly=True,
        phases={
            "universe": Slot(impl=DvRankCap, params=DvRankCap.Params()),
            "signal": Slot(impl=BctScoreFull, params=BctScoreFull.Params(min_score=7, parabolic_threshold=0.25)),
            "regime": [
                Slot(impl=SpySma200, params=SpySma200.Params()),
                Slot(impl=VixPercentile, params=VixPercentile.Params(vix_percentile_enabled=False)),
            ],
            "sizing": Slot(impl=FlatPctHeatcap, params=FlatPctHeatcap.Params(position_pct=0.05, resolution="intraday")),
            "portfolio_risk": Slot(impl=GrossExposureCap,
                                   params=GrossExposureCap.Params(max_gross_pct=1.0, resolution="intraday")),
            "exit_hard": [Slot(impl=CloudAdherenceTrail, params=CloudAdherenceTrail.Params())],
            "entry_selection": [
                Slot(impl=PreFlightStaleness, params=PreFlightStaleness.Params()),
                Slot(impl=BctIntradayGapVolConfirm, params=BctIntradayGapVolConfirm.Params()),
            ],
            "entry_timing": Slot(impl=ConfirmedMarketEntry, params=ConfirmedMarketEntry.Params()),
            "protective_stop": Slot(impl=CloudProtectiveStop, params=CloudProtectiveStop.Params()),
            # the ONLY axis under test — the add SIZING variant (same trigger, same max_adds):
            "adds": Slot(impl=StagedRiskPyramid, params=StagedRiskPyramid.Params(variant=variant, max_adds=2)),
            "diagnostics": [
                Slot(impl=VersionMarker, params=VersionMarker.Params()),
                Slot(impl=ChartEmit, params=ChartEmit.Params()),
            ],
        },
    )
