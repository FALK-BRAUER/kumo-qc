"""champion-asis — the carve's phase stack on the filter -> rank+cap dynamic universe.

The proven per-ticker BCT LOGIC (8-condition signal / SPY+VIX regime / flat-% sizing /
Kijun+G3 exits / version-marker) wired over the v2 universe pipeline:

    filter (tradeability_floors) -> universe (dv_rank_cap) -> signal (bct_score_full)
    -> regime (spy_200ma, vix_percentile) -> sizing (flat_pct_heatcap)
    -> exit_hard (kijun_g3_exits) -> diagnostics (version_marker)

NOT the 326 oracle, NO fixed slots, NO top-N artifact: a dynamic, point-in-time,
survivorship-clean candidate set (floors gate tradeability; DV-desc rank+coarse_max cap;
BCT score>=7 selects). Run fresh -> gate-validate (G1-G5/DSR-PBO) -> first honest baseline.
Every result pins to (git commit + this config hash + substrate fingerprint 90f2d7e3).

Direct-ref Slots, typed Params. One active strategy per build.
"""
from __future__ import annotations

from engine.config import Slot, StrategyConfig
from phases.diagnostics.version_marker.version_marker import VersionMarker
from phases.exit.kijun_g3_exits.kijun_g3_exits import KijunG3Exits
from phases.filter.tradeability_floors.tradeability_floors import TradeabilityFloors
from phases.regime.spy_200ma.spy_200ma import SpySma200
from phases.regime.vix_percentile.vix_percentile import VixPercentile
from phases.signal.bct_score_full.bct_score_full import BctScoreFull
from phases.sizing.flat_pct_heatcap.flat_pct_heatcap import FlatPctHeatcap
from phases.universe.dv_rank_cap.dv_rank_cap import DvRankCap

CONFIG = StrategyConfig(
    name="champion-asis",
    version="3.0.0",
    phases={
        # Tradeability gate (price>=10, trailing-20d ADV>=5M). Eligibility only.
        "filter": Slot(
            impl=TradeabilityFloors,
            params=TradeabilityFloors.Params(
                min_price=10.0, min_avg_dollar_volume=5_000_000.0, adv_window=20,
            ),
        ),
        # Rank eligible by DV desc, cap coarse_max (unbounded baseline). Scan breadth only.
        "universe": Slot(
            impl=DvRankCap,
            params=DvRankCap.Params(coarse_max=9999),
        ),
        # George's 8-condition BCT scorer — the actual stock selector (score>=7).
        "signal": Slot(
            impl=BctScoreFull,
            params=BctScoreFull.Params(min_score=7, parabolic_threshold=0.25),
        ),
        "regime": [
            Slot(impl=SpySma200, params=SpySma200.Params()),
            Slot(impl=VixPercentile, params=VixPercentile.Params(vix_percentile_enabled=False)),
        ],
        "sizing": Slot(
            impl=FlatPctHeatcap,
            params=FlatPctHeatcap.Params(position_pct=0.10),
        ),
        "exit_hard": [
            Slot(impl=KijunG3Exits, params=KijunG3Exits.Params(
                cloud_exit_enabled=False, weekly_kijun_exit_enabled=False,
                phase3_days=56, phase3_pnl=0.15,
            )),
        ],
        "diagnostics": [
            Slot(impl=VersionMarker, params=VersionMarker.Params()),
        ],
    },
)
