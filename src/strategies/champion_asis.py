"""champion-asis — the carve's phase stack on the LIVE selection-gate dynamic universe.

The proven per-ticker BCT LOGIC (8-condition signal / SPY+VIX regime / flat-% sizing /
Kijun+G3 exits / version-marker) wired over the v2 universe pipeline:

    universe (dv_rank_cap) -> signal (bct_score_full)
    -> regime (spy_200ma, vix_percentile) -> sizing (flat_pct_heatcap)
    -> exit_hard (kijun_g3_exits) -> diagnostics (version_marker)

NOT the 326 oracle, NO fixed slots, NO top-N artifact, NO stored universe file: a dynamic,
point-in-time, survivorship-clean candidate set computed LIVE once-daily from QC's coarse
feed (#238 / Y, Falk — the floors live at the SELECTION GATE: lean_entry._coarse_selection
builds the trailing metrics, applies apply_floors (tradeability) → rank_and_cap (DV-desc,
coarse_max cap) → subscribes ONLY the ranked qualifying set. There is NO per-bar filter phase
— the floors moved to selection where they bound subscription (only qualifying names get
Ichimoku'd). The universe phase EXPOSES that live-selected ranked order; BCT score>=7 selects).
Run fresh -> gate-validate (G1-G5/DSR-PBO) -> first honest baseline. Every result pins to
(git commit + this config hash + substrate fingerprint 90f2d7e3).

Direct-ref Slots, typed Params. One active strategy per build. NO UNIVERSE_SPEC: #238
retired the stored-universe-file ObjectStore artifact + its fingerprint-verify (the 326
scar) — the universe is computed live, so there is no file to pin/verify. The lean_entry
universe knobs (PREFILTER_DV / MIN_PRICE / MIN_AVG_DOLLAR_VOLUME / COARSE_MAX / ADV_WINDOW)
are the SINGLE source of the floors+rank+cap (applied at the selection gate).
"""
from __future__ import annotations

from engine.config import Slot, StrategyConfig
from phases.diagnostics.chart_emit.chart_emit import ChartEmit
from phases.diagnostics.version_marker.version_marker import VersionMarker
from phases.exit.kijun_g3_exits.kijun_g3_exits import KijunG3Exits
from phases.regime.spy_200ma.spy_200ma import SpySma200
from phases.regime.vix_percentile.vix_percentile import VixPercentile
from phases.signal.bct_score_full.bct_score_full import BctScoreFull
from phases.sizing.flat_pct_heatcap.flat_pct_heatcap import FlatPctHeatcap
from phases.universe.dv_rank_cap.dv_rank_cap import DvRankCap

CONFIG = StrategyConfig(
    name="champion-asis",
    # 3.2.0: Y (Falk) — floors moved to the SELECTION GATE (lean_entry._coarse_selection);
    # the redundant per-bar filter phase is DROPPED. The universe phase exposes the live
    # floored+ranked+capped selection. (3.1.0 = the R1 un-fuse this supersedes.)
    version="3.2.0",
    phases={
        # EXPOSE the live-selected ranked order. The floors (price>=10, trailing-20d ADV>=100M
        # — LIQUIDITY threshold, ~943 names/day FY2025; fintrack ruling) + the DV-desc rank +
        # the COARSE_MAX cap ALL happen at the selection gate (lean_entry, single source); this
        # phase reads qc._ranked_today ∩ active in rank order (#182 fix).
        "universe": Slot(
            impl=DvRankCap,
            params=DvRankCap.Params(),
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
        # diagnostics is a list-kind (engine keys by (kind, module)); two sub-phases coexist.
        # chart_emit (#243) makes the universe counts cloud-observable via self.plot — the
        # only channel left since QC dropped Log() API + ObjectStore export (non-Institutional).
        "diagnostics": [
            Slot(impl=VersionMarker, params=VersionMarker.Params()),
            Slot(impl=ChartEmit, params=ChartEmit.Params()),
        ],
    },
)

# NO UNIVERSE_SPEC (#238): the stored-universe-file mechanism (ObjectStore eligible/universe
# JSON + the load-time fingerprint-verify) is RETIRED. The universe is computed LIVE
# once-daily from QC's coarse feed (Y: the selection gate runtime.lean_entry._coarse_selection
# builds the trailing metrics, applies runtime.universe_select.apply_floors then rank_and_cap,
# and subscribes only the qualifying set) — there is no file to pin or verify. The universe
# knobs are class attributes on the lean_entry subclass (PREFILTER_DV / MIN_PRICE /
# MIN_AVG_DOLLAR_VOLUME / COARSE_MAX / ADV_WINDOW) — the single source of the floors+rank+cap.

# LEAN_ENTRY: this strategy is LEAN-DEPLOYABLE — the build (build/cloud_package.py) seeds
# runtime.lean_entry + emits the BctEngineAlgorithm subclass in dist/main.py. Config-only
# fixtures (sample/example) omit this flag.
LEAN_ENTRY = True
