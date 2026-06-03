"""learned-dvrank — the #322 learned-signal CLOUD-VALIDATION config (NOT a champion, NO merge).

champion-intraday-gapvol with EXACTLY ONE change: the daily signal slot swaps BctScoreFull →
OracleSignal(DvRankPredictor). Everything else — universe, regime, sizing, the intraday entry-confirm
(PreFlightStaleness → BctIntradayGapVolConfirm), entry-timing, the #290 protective stop, the daily
KijunG3 exit — is HELD CONSTANT vs the champion, so the Sharpe/return delta is attributable to the
LEARNED-SIGNAL BOOSTER alone (the clean-experiment discipline: essentials constant, swap the booster).

The booster = the phase-1 mine finding (PHASE1_FINDINGS.md): the BCT screen picks the POOL (score≥7,
table-stakes) but does not RANK within it; DV/liquidity-rank does (top-DV rides to winners, robust
4/4 regimes). DvRankPredictor fires iff bct_score≥7 AND rank≤rank_cap — i.e. the top-liquidity slice
of the screened pool. rank_cap=250 is the local-test sweet spot (+12pp win / +7.5pp ret on the
2021-2025 substrate); the cloud-validation 5-gate run confirms or refutes it on the FULL signal
(different entries + capital reallocation, not just the selection effect the local test isolated).

is_fixture=False — real entry-confirm + exit wired (passes the #272 gate). For VALIDATION ONLY (the
5 charter gates + §Parity vs the baseline champion); merge is Falk's call.
"""
from __future__ import annotations

from engine.config import Slot, StrategyConfig
from phases.diagnostics.chart_emit.chart_emit import ChartEmit
from phases.diagnostics.version_marker.version_marker import VersionMarker
from phases.entry_selection.bct_intraday_gap_vol_confirm.bct_intraday_gap_vol_confirm import BctIntradayGapVolConfirm
from phases.entry_selection.preflight_staleness.preflight_staleness import PreFlightStaleness
from phases.entry_timing.confirmed_market_entry.confirmed_market_entry import ConfirmedMarketEntry
from phases.exit.kijun_g3_exits.kijun_g3_exits import KijunG3Exits
from phases.protective_stop.kijun_protective_stop.kijun_protective_stop import KijunProtectiveStop
from phases.regime.spy_200ma.spy_200ma import SpySma200
from phases.regime.vix_percentile.vix_percentile import VixPercentile
from phases.signal.oracle_signal.oracle_signal import DvRankPredictor, OracleSignal
from phases.sizing.flat_pct_heatcap.flat_pct_heatcap import FlatPctHeatcap
from phases.universe.dv_rank_cap.dv_rank_cap import DvRankCap

CONFIG = StrategyConfig(
    name="learned-dvrank",
    version="1.0.0",
    is_fixture=False,
    phases={
        "universe": Slot(impl=DvRankCap, params=DvRankCap.Params()),
        # THE ONE CHANGE: learned signal = BCT pool (score≥7) + DV-rank edge (cap=250).
        "signal": Slot(
            impl=OracleSignal,
            params=OracleSignal.Params(
                predictor=DvRankPredictor(min_score=7, rank_cap=250),
                min_score=7,
                parabolic_threshold=0.25,
            ),
        ),
        "regime": [
            Slot(impl=SpySma200, params=SpySma200.Params()),
            Slot(impl=VixPercentile, params=VixPercentile.Params(vix_percentile_enabled=False)),
        ],
        "sizing": Slot(impl=FlatPctHeatcap, params=FlatPctHeatcap.Params(position_pct=0.10, resolution="intraday")),
        "exit_hard": [
            Slot(impl=KijunG3Exits, params=KijunG3Exits.Params(
                cloud_exit_enabled=False, weekly_kijun_exit_enabled=False,
                phase3_days=56, phase3_pnl=0.15,
            )),
        ],
        "entry_selection": [
            Slot(impl=PreFlightStaleness, params=PreFlightStaleness.Params()),
            Slot(impl=BctIntradayGapVolConfirm, params=BctIntradayGapVolConfirm.Params()),
        ],
        "entry_timing": Slot(impl=ConfirmedMarketEntry, params=ConfirmedMarketEntry.Params()),
        "protective_stop": Slot(impl=KijunProtectiveStop, params=KijunProtectiveStop.Params()),
        "diagnostics": [
            Slot(impl=VersionMarker, params=VersionMarker.Params()),
            Slot(impl=ChartEmit, params=ChartEmit.Params()),
        ],
    },
)

# Same live-selection gate as the champion (no stored universe; floors+rank+cap at lean_entry).
LEAN_ENTRY = True
