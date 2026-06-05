"""#340-reserve grid — the cash-reserve × size × pyramid tournament (Falk's reopened winner-side, the
charter-compliant successor to the name-cap). The 16-cell sizing matrix proved breadth ATE the cash
before the pyramid could add (63 names × 1.65% ≈ 100% gross → adds gross-cap-dropped → pyramid starved,
same as #340-C). This grid RESERVES cash for the pyramid via ReserveHeatcap.base_entry_gross_budget:
base entries fill only to budget × gross; the (1 - budget) reserve is consumed ONLY by the adds → the
pyramid can re-concentrate into the ≥+5% provers instead of breadth diluting the monsters.

  AXIS 1 size   : position_pct ∈ {0.05 (=S1 1.0×), 0.025 (0.5×), 0.0165 (0.33×)}
  AXIS 2 budget : base_entry_gross_budget ∈ {0.50, 0.70} (reserve 50% / 30% for the pyramid)
  AXIS 3 pyramid: ON (StagedRiskPyramid Pe-rampup + GrossExposureCap 1.0) | OFF (control)

THE DECISIVE CONTROL — {size 0.05 × budget 0.70 × pyrON}: keep S1's WINNING big entries (~14 names at
0.70 gross), reserve 30% to ADD to the provers. Isolates PURE pyramid-reserve from breadth-dilution. If
THIS beats S1 → the pyramid pays WHEN GIVEN ROOM, independent of breadth. If even this doesn't → #340-C
holds for real (the pyramid doesn't pay even with reserved cash) → convergence (leverage the only lever).
The pyrOFF budget-controls confirm the reserve only helps WITH the pyramid (idle reserve = no adds = the
reserve alone is pure downside).

Same fixed proven-optimal stack as sizing_pyramid_matrix (DvRankCap / BctScoreFull s7 / SpySma200 /
CloudAdherenceTrail cloud-bottom / GapVolConfirm / CloudProtectiveStop). gross-cap stays 1.0 — the
headroom is from the RESERVE, NOT leverage (autonomous, not Rule#5).
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
from phases.sizing.reserve_heatcap.reserve_heatcap import ReserveHeatcap
from phases.universe.dv_rank_cap.dv_rank_cap import DvRankCap


def make_config(position_pct: float = 0.05, budget: float = 0.70, pyramid: bool = True) -> StrategyConfig:
    """S1 stack + ReserveHeatcap(position_pct, base_entry_gross_budget=budget) + pyramid adds ON/OFF."""
    pyr = "pyrON" if pyramid else "pyrOFF"
    phases = {
        "universe": Slot(impl=DvRankCap, params=DvRankCap.Params()),
        "signal": Slot(impl=BctScoreFull, params=BctScoreFull.Params(min_score=7, parabolic_threshold=0.25)),
        "regime": [
            Slot(impl=SpySma200, params=SpySma200.Params()),
            Slot(impl=VixPercentile, params=VixPercentile.Params(vix_percentile_enabled=False)),
        ],
        "sizing": Slot(impl=ReserveHeatcap, params=ReserveHeatcap.Params(
            position_pct=position_pct, base_entry_gross_budget=budget, resolution="intraday")),
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
        # the reserved (1 - budget) headroom is what these adds consume — re-concentrate into the provers.
        phases["portfolio_risk"] = Slot(impl=GrossExposureCap,
                                        params=GrossExposureCap.Params(max_gross_pct=1.0, resolution="intraday"))
        phases["adds"] = Slot(impl=StagedRiskPyramid, params=StagedRiskPyramid.Params(variant="Pe-rampup", max_adds=2))
    return StrategyConfig(name=f"reserve-sz{position_pct}-b{budget}-{pyr}", version="1.0.0",
                          is_fixture=False, continuous_weekly=True, phases=phases)
