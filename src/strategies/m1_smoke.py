"""#386 M1 SMOKE — proves the two-clock engine: the legacy day-SELECTION (DvRankCap/BctScoreFull/
SpySma200 — SAME as champion_intraday_gapvol → armed-set byte-identical vs baseline) ARMS candidates on
the daily tick (StubArm → qc._armed); the INTRADAY chain (StubEntryTrigger → StubIntradaySizer →
FIRE_ENTRIES) fires them per-5-min-bar. NO gap_vol_confirm (open-30m window), NO entry_timing
(market-on-open), NO 2nd-slot (the MOO default is DELETED). is_fixture=True: arm/entry_trigger isn't yet
in ENTRY_PHASE_KINDS (Step-2 guard refinement) — a STUB proof, not a champion. Validates: entries fire
ACROSS the day (per-bar), ZERO at 15:51 (MOO gone, by construction), armed-set == legacy baseline.
"""
from __future__ import annotations
from engine.config import Slot, StrategyConfig
from phases.diagnostics.chart_emit.chart_emit import ChartEmit
from phases.diagnostics.version_marker.version_marker import VersionMarker
from phases.exit.cloud_adherence_trail.cloud_adherence_trail import CloudAdherenceTrail
from phases.regime.spy_200ma.spy_200ma import SpySma200
from phases.regime.vix_percentile.vix_percentile import VixPercentile
from phases.signal.bct_score_full.bct_score_full import BctScoreFull
from phases.universe.dv_rank_cap.dv_rank_cap import DvRankCap
from phases.arm.stub_arm.stub_arm import StubArm
from phases.entry_trigger.stub_trigger.stub_trigger import StubEntryTrigger
from phases.intraday_sizing.stub_intraday_sizer.stub_intraday_sizer import StubIntradaySizer

CONFIG = StrategyConfig(
    name="m1-smoke", version="1.0.0", is_fixture=True, continuous_weekly=True,
    phases={
        # DAY clock — selection (SAME as champion_intraday_gapvol → armed-set comparable) → ARM
        "universe": Slot(impl=DvRankCap, params=DvRankCap.Params()),
        "signal": Slot(impl=BctScoreFull, params=BctScoreFull.Params(min_score=7, parabolic_threshold=0.25)),
        "regime": [Slot(impl=SpySma200, params=SpySma200.Params()),
                   Slot(impl=VixPercentile, params=VixPercentile.Params(vix_percentile_enabled=False))],
        "arm": Slot(impl=StubArm, params=StubArm.Params()),
        # INTRADAY clock — per-bar trigger → size-at-fire → FIRE_ENTRIES
        "entry_trigger": Slot(impl=StubEntryTrigger, params=StubEntryTrigger.Params()),
        "intraday_sizing": Slot(impl=StubIntradaySizer, params=StubIntradaySizer.Params()),
        # exits (day) so positions can close in the smoke window
        "exit_hard": [Slot(impl=CloudAdherenceTrail, params=CloudAdherenceTrail.Params())],
        "diagnostics": [Slot(impl=VersionMarker, params=VersionMarker.Params()),
                        Slot(impl=ChartEmit, params=ChartEmit.Params())],
    })
LEAN_ENTRY = True
