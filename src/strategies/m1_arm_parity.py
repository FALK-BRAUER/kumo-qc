"""#386 M1 STAGE-1 — arm-in-parallel parity config. The champion-intraday-gapvol daily decision +
intraday fire, UNCHANGED, plus the modular `arm` phase running IN-CHAIN (after regime). The legacy
_capture_candidate_snapshot STILL runs and STILL owns the fire; arm writes qc._armed alongside it.
lean_entry's STAGE-1 live assertion (_assert_arm_parity) then crashes if qc._armed != the legacy
qc._candidate_snapshot on the winner set / zone(==signal_price) / daily_kijun.

Purpose: prove the modular arm reproduces the legacy daily decision EXACTLY — additive, reversible,
ZERO behavior change, NO delete — before Stage 2 cuts the legacy snapshot path and moves the fire
onto entry_trigger. Run local minute; green = arm parity proven across the run.

is_fixture=False — still a real champion (entry_selection + entry_timing + exit_hard wired); the only
delta vs champion-intraday-gapvol is the additive `arm` slot. Guard (a): sizing present (1 clock).
"""
from __future__ import annotations

from engine.config import Slot, StrategyConfig
from phases.arm.stub_arm.stub_arm import StubArm
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

CONFIG = StrategyConfig(
    name="m1-arm-parity",
    version="1.0.0",
    is_fixture=False,
    continuous_weekly=True,
    phases={
        # --- DAILY decision clock (champion-intraday-gapvol, UNCHANGED) ---
        "universe": Slot(impl=DvRankCap, params=DvRankCap.Params()),
        "signal": Slot(impl=BctScoreFull, params=BctScoreFull.Params(min_score=7, parabolic_threshold=0.25)),
        "regime": [
            Slot(impl=SpySma200, params=SpySma200.Params()),
            Slot(impl=VixPercentile, params=VixPercentile.Params(vix_percentile_enabled=False)),
        ],
        # #386 STAGE-1 ADDITIVE: arm runs after regime, writes qc._armed (parallel to the legacy
        # snapshot). NO fire here, NO delete — the parity assertion proves arm == snapshot.
        "arm": Slot(impl=StubArm, params=StubArm.Params()),
        "sizing": Slot(impl=FlatPctHeatcap, params=FlatPctHeatcap.Params(position_pct=0.05, resolution="intraday")),
        "exit_hard": [Slot(impl=CloudAdherenceTrail, params=CloudAdherenceTrail.Params())],
        # --- INTRADAY execution clock (champion legacy fire, UNCHANGED) ---
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
LEAN_ENTRY = True
