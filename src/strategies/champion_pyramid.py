"""champion_pyramid (#340-B) — the S1 champion (champion_intraday_gapvol) + a StagedRiskPyramid ADD
phase (Pe-rampup, #172/#178) that pyramids INTO confirmed winners. CORE S1 UNTOUCHED — identical
universe/signal/regime/sizing/entry/exit/protective-stop; ADDITIVE only:
  + portfolio_risk = GrossExposureCap (REQUIRED once `adds` is wired — adds-without-gross-cap is a
    CharterViolation; this bounds the pyramid adds to 100% gross at FIRE_ADDS via bound_adds).
  + adds = StagedRiskPyramid (held position in profit + a fresh Tenkan>Kijun cross → staged-risk
    tranche $200/$400, capped at max_adds=2, add-to-winners-only).

Grades vs the S1 control (champion_intraday_gapvol) on the FY trio (Sharpe/Ret%/DD%) + the mandatory
survival-ledger: does it amplify the monsters (Σ open-paper ↑) WITHOUT deepening the realized-loser
tail or blowing DD past S1's 19.4%? (the hard accept/reject gate, mirror of the hard-stop verdict).
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

CONFIG = StrategyConfig(
    name="champion-pyramid",
    version="1.0.0",
    is_fixture=False,  # entry-confirm + exit wired → passes the #272 gate
    continuous_weekly=True,  # #336/#339 S1 corrected-weekly
    phases={
        # --- S1 champion (UNTOUCHED) ---
        "universe": Slot(impl=DvRankCap, params=DvRankCap.Params()),
        "signal": Slot(impl=BctScoreFull, params=BctScoreFull.Params(min_score=7, parabolic_threshold=0.25)),
        "regime": [
            Slot(impl=SpySma200, params=SpySma200.Params()),
            Slot(impl=VixPercentile, params=VixPercentile.Params(vix_percentile_enabled=False)),
        ],
        "sizing": Slot(impl=FlatPctHeatcap, params=FlatPctHeatcap.Params(position_pct=0.05, resolution="intraday")),
        # REQUIRED for adds: the gross-exposure ceiling that bound_adds enforces at FIRE_ADDS (100%, no leverage)
        "portfolio_risk": Slot(impl=GrossExposureCap, params=GrossExposureCap.Params(max_gross_pct=1.0)),
        "exit_hard": [Slot(impl=CloudAdherenceTrail, params=CloudAdherenceTrail.Params())],
        "entry_selection": [
            Slot(impl=PreFlightStaleness, params=PreFlightStaleness.Params()),
            Slot(impl=BctIntradayGapVolConfirm, params=BctIntradayGapVolConfirm.Params()),
        ],
        "entry_timing": Slot(impl=ConfirmedMarketEntry, params=ConfirmedMarketEntry.Params()),
        "protective_stop": Slot(impl=CloudProtectiveStop, params=CloudProtectiveStop.Params()),
        # --- #340-B ADD lever (the only behavioral addition) ---
        "adds": Slot(impl=StagedRiskPyramid, params=StagedRiskPyramid.Params(variant="Pe-rampup", max_adds=2)),
        "diagnostics": [
            Slot(impl=VersionMarker, params=VersionMarker.Params()),
            Slot(impl=ChartEmit, params=ChartEmit.Params()),
        ],
    },
)

LEAN_ENTRY = True
