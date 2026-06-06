"""#276b ENTRY-MECHANIC param-sweep factory — S1 champion (champion_intraday_gapvol) with the EXISTING
entry stack's params swept (NO new phase: HQ verified S1's asymmetric-gap gate already ships —
PreFlightStaleness(below_kijun_invalidates=True, gap_up_tolerance) + BctIntradayGapVolConfirm(gap_threshold,
vol_mult, window_bars) + ConfirmedMarketEntry-fires-at-open). Tests gate looseness/selectivity inside
the validated phase — the same hypothesis as a new gap-gate, zero new failure surface.

  gap_threshold        — the selective gap cohort (S1=0.03; 0.02=admit more gap-ups, 0.04/0.05=tighter)
  vol_mult             — loud-open multiple (S1=1.0; >1.5 known to kill winners)
  gap_up_tolerance_pct — bounds the chase (S1=0.10)
champion_intraday_gapvol.py UNTOUCHED.
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


def make_config(gap_threshold: float = 0.03, vol_mult: float = 1.0,
                gap_up_tolerance_pct: float = 0.10, window_bars: int = 6) -> StrategyConfig:
    """S1 champion with the entry-gate params swept (the ONLY change vs S1)."""
    tag = f"gt{gap_threshold}_vm{vol_mult}_tol{gap_up_tolerance_pct}"
    return StrategyConfig(
        name=f"entry-sweep-{tag}",
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
            "exit_hard": [Slot(impl=CloudAdherenceTrail, params=CloudAdherenceTrail.Params())],
            "entry_selection": [
                Slot(impl=PreFlightStaleness,
                     params=PreFlightStaleness.Params(gap_up_tolerance_pct=gap_up_tolerance_pct,
                                                      below_kijun_invalidates=True)),
                Slot(impl=BctIntradayGapVolConfirm,
                     params=BctIntradayGapVolConfirm.Params(gap_threshold=gap_threshold, vol_mult=vol_mult,
                                                            window_bars=window_bars)),
            ],
            "entry_timing": Slot(impl=ConfirmedMarketEntry, params=ConfirmedMarketEntry.Params()),
            "protective_stop": Slot(impl=CloudProtectiveStop, params=CloudProtectiveStop.Params()),
            "diagnostics": [
                Slot(impl=VersionMarker, params=VersionMarker.Params()),
                Slot(impl=ChartEmit, params=ChartEmit.Params()),
            ],
        },
    )
