"""#345/#363 ROTATION SCREEN factory — S1 champion (champion_intraday_gapvol) + a GainFlooredRotation
exit phase, parametrized by `variant` (R1/R2). Tests whether gain-floored rotation (evict gain-positive
laggards to free cash-locked capital) beats S1's realized FLOOR-PROXY (+21.13k) WITHOUT clipping a
runner — the lever that creates headroom by freeing LOSER... no: by freeing GAIN-POSITIVE LAGGARD
capital (never a consolidating-from-loss carrier — the gain-floor, the #341 fix).

R1/R2 are FULL-exit only (FIRE_EXITS cancels the protective stop cleanly — no gross-cap, no #378
needed). champion_intraday_gapvol.py is UNTOUCHED. R3 (full-exit-redeploy) is deferred — its inline
redeploy add has timing/gross-cap/#378 hazards (code-review #345), built only if R1/R2 show promise.
"""
from __future__ import annotations

from engine.config import Slot, StrategyConfig
from phases.diagnostics.chart_emit.chart_emit import ChartEmit
from phases.diagnostics.version_marker.version_marker import VersionMarker
from phases.entry_selection.bct_intraday_gap_vol_confirm.bct_intraday_gap_vol_confirm import BctIntradayGapVolConfirm
from phases.entry_selection.preflight_staleness.preflight_staleness import PreFlightStaleness
from phases.entry_timing.confirmed_market_entry.confirmed_market_entry import ConfirmedMarketEntry
from phases.exit.cloud_adherence_trail.cloud_adherence_trail import CloudAdherenceTrail
from phases.exit.rotation.gain_floored_rotation import GainFlooredRotation
from phases.protective_stop.cloud_protective_stop.cloud_protective_stop import CloudProtectiveStop
from phases.regime.spy_200ma.spy_200ma import SpySma200
from phases.regime.vix_percentile.vix_percentile import VixPercentile
from phases.signal.bct_score_full.bct_score_full import BctScoreFull
from phases.sizing.flat_pct_heatcap.flat_pct_heatcap import FlatPctHeatcap
from phases.universe.dv_rank_cap.dv_rank_cap import DvRankCap


def make_config(variant: str) -> StrategyConfig:
    """S1 champion + a GainFlooredRotation(`variant`) exit phase (the ONLY change vs S1)."""
    return StrategyConfig(
        name=f"rotation-screen-{variant}",
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
            # the ONLY addition vs S1 — the gain-floored rotation exit (daily, full-exit):
            "exit_rotation": Slot(impl=GainFlooredRotation, params=GainFlooredRotation.Params(variant=variant)),
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
