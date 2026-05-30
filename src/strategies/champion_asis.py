"""champion-asis — the carve's phase stack on the DYNAMIC universe (v2, reframed #212).

The 7 universe-agnostic library phases (BCT signal / SPY+VIX regime / flat-% sizing /
Kijun+G3 exits / version-marker) wired over the dynamic point-in-time universe — NO 326,
NO fixed slots. This is NOT the 326 oracle: it's the same proven per-ticker LOGIC on the
honest dynamic+raw substrate. Run fresh → gate-validate (G1-G5) → that is the first honest
baseline. Every result pins to (git commit + this config hash + substrate fingerprint).

Direct-ref Slots, typed Params. One active strategy per build.
"""
from __future__ import annotations

from engine.config import Slot, StrategyConfig
from phases.diagnostics.version_marker.version_marker import VersionMarker
from phases.exit.kijun_g3_exits.kijun_g3_exits import KijunG3Exits
from phases.regime.spy_200ma.spy_200ma import SpySma200
from phases.regime.vix_percentile.vix_percentile import VixPercentile
from phases.signal.bct_score_full.bct_score_full import BctScoreFull
from phases.sizing.flat_pct_heatcap.flat_pct_heatcap import FlatPctHeatcap
from phases.universe.dynamic_dollar_volume.dynamic_dollar_volume import DynamicDollarVolume

CONFIG = StrategyConfig(
    name="champion-asis",
    version="2.0.0",
    phases={
        "universe": Slot(
            impl=DynamicDollarVolume,
            params=DynamicDollarVolume.Params(n=1500, price_floor=10.0, dv_floor=5_000_000.0, dv_window=20),
        ),
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
