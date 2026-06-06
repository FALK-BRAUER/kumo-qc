"""#340-C-REDO — the sizing × pyramid MATRIX (Falk's reopened winner-side). #340-C tested only
{full-size × pyramid-ON} → "99.8% invested, no cash" → mis-concluded headroom=leverage. The missing
cell = SMALLER entries (cheap probes that LEAVE CASH) → more winner-candidates fit under the SAME 100%
gross-cap (headroom from SIZING-DOWN, NOT leverage — gross stays 1.0, autonomous) + pyramid
re-concentrates the freed cash into the ≥+5% PROVERS.

  AXIS 1 per-entry size: position_pct ∈ {0.05(=S1 1.0×), 0.033(0.66×), 0.025(0.5×), 0.0165(0.33×)}.
  AXIS 2 pyramid: OFF (S1, no adds) | ON (StagedRiskPyramid Pe-rampup on the provers + the #378 floor +
    GrossExposureCap to bound the adds at 1.0).
FIXED (proven-optimal): exit=CloudAdherenceTrail (cloud-bottom), entry=GapVolConfirm gap0.03, gross-cap=1.0.

Two traps the screen instruments: DILUTION (smaller entries halve each monster's contribution unless the
pyramid re-concentrates → {smaller + pyramid-OFF} likely LOSES) + SLOT-FILL/SIGNAL-SCARCITY (do the extra
slots fill, or does cash idle for lack of score-7 signals? — anchor to CLOUD-realistic counts; local
over-counts signals ~6×). champion_intraday_gapvol.py + champion_pyramid.py UNTOUCHED.
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


def make_config(position_pct: float = 0.05, pyramid: bool = False) -> StrategyConfig:
    """S1 champion with per-entry size = `position_pct`, and the pyramid adds slot ON/OFF."""
    pyr = "pyrON" if pyramid else "pyrOFF"
    phases = {
        "universe": Slot(impl=DvRankCap, params=DvRankCap.Params()),
        "signal": Slot(impl=BctScoreFull, params=BctScoreFull.Params(min_score=7, parabolic_threshold=0.25)),
        "regime": [
            Slot(impl=SpySma200, params=SpySma200.Params()),
            Slot(impl=VixPercentile, params=VixPercentile.Params(vix_percentile_enabled=False)),
        ],
        "sizing": Slot(impl=FlatPctHeatcap, params=FlatPctHeatcap.Params(position_pct=position_pct, resolution="intraday")),
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
    }
    if pyramid:
        # the adds lever (re-concentrate freed cash into ≥+5% provers) + its REQUIRED gross-cap (#181)
        # + the #378 stop-resize floor. gross-cap stays 1.0 — the headroom is from sizing-down, NOT leverage.
        phases["portfolio_risk"] = Slot(impl=GrossExposureCap,
                                        params=GrossExposureCap.Params(max_gross_pct=1.0, resolution="intraday"))
        phases["adds"] = Slot(impl=StagedRiskPyramid, params=StagedRiskPyramid.Params(variant="Pe-rampup", max_adds=2))
    return StrategyConfig(name=f"matrix-sz{position_pct}-{pyr}", version="1.0.0",
                          is_fixture=False, continuous_weekly=True, phases=phases)
