"""champion-intraday-gapvol-regime — the #270 daily-signal → intraday-confirmed execution champion.

The forward champion that supersedes the champion-asis blind-entry FIXTURE. Same proven per-ticker
BCT selection + regime + sizing + EXIT as champion-asis, but the entry is no longer a phantom
market-on-open: the daily 8-condition signal picks candidates (after close T, for T+1), and on T+1's
INTRADAY (5-min) clock the engine confirms before firing.

Two clocks (engine _partition_clocks routes per-KIND; #270/#274/#313):
  DAILY decision clock (scheduled after-close, #313): universe → signal → regime → sizing →
    exit_hard (KijunG3Exits — REUSED UNCHANGED from champion-asis; George's rule = DAILY close <
    Kijun, EOD-only; intraday stop-monitoring destroys the W1-W4 edge, fintrack Run-8 lesson) →
    diagnostics. Produces the candidate snapshot (276b-0) for T+1.
  INTRADAY execution clock (5-min, on_data): the candidate stubs are injected, then
    entry_selection (PreFlightStaleness → BctIntradayConfirm: asymmetric gap-gate, then tenkan-
    reclaim CROSS + rising-vol) → entry_timing (ConfirmedMarketEntry: market fire on confirm) →
    protective_stop (KijunProtectiveStop: the #290 daily-Kijun GTC catastrophic floor) → FIRE_ENTRIES.

The EXIT is held CONSTANT vs champion-asis (the daily KijunG3Exits) on purpose — so the proof-of-life
Sharpe-delta is attributable to the ENTRY model alone (HQ: clean experiment). The #290 GTC floor is
the touch-fire catastrophic backstop (gap/halt); the daily exit is the normal close-breach; the
engine cancels one when the other fires (no double-exit, FIRE_EXITS → _cancel_protective_stop).

is_fixture=False — a real champion: it wires an entry-confirm (entry_selection + entry_timing) AND an
exit (exit_hard), so the #272 fail-loud gate passes. NO implicit market-on-open. Same live-selection
gate + universe knobs as champion-asis (lean_entry _coarse_selection; no stored universe, RAW).
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
from phases.signal.bct_score_full.bct_score_full import BctScoreFull
from phases.sizing.flat_pct_heatcap.flat_pct_heatcap import FlatPctHeatcap
from phases.universe.dv_rank_cap.dv_rank_cap import DvRankCap

CONFIG = StrategyConfig(
    name="champion-intraday-gapvol-regime",
    version="1.0.0",
    is_fixture=False,  # a real champion: entry-confirm + exit wired → passes the #272 gate
    phases={
        # --- DAILY decision clock (same selection/regime/sizing/exit as champion-asis) ---
        "universe": Slot(impl=DvRankCap, params=DvRankCap.Params()),
        "signal": Slot(
            impl=BctScoreFull,
            params=BctScoreFull.Params(min_score=7, parabolic_threshold=0.25),
        ),
        "regime": [
            Slot(impl=SpySma200, params=SpySma200.Params()),
            Slot(impl=VixPercentile, params=VixPercentile.Params(vix_percentile_enabled=True, vix_percentile_threshold=75.0)),
        ],
        # sizing on the INTRADAY clock (#276b-1): the confirmed entry is sized at confirm time on
        # the 5-min clock — the whole entry-execution chain (selection→timing→sizing→floor→FIRE)
        # shares the intraday clock (the engine's entry-chain-clock guard enforces this).
        "sizing": Slot(impl=FlatPctHeatcap, params=FlatPctHeatcap.Params(position_pct=0.10, resolution="intraday")),
        # EXIT held CONSTANT vs champion-asis (daily KijunG3Exits, EOD close<Kijun + G3 trail).
        "exit_hard": [
            Slot(impl=KijunG3Exits, params=KijunG3Exits.Params(
                cloud_exit_enabled=False, weekly_kijun_exit_enabled=False,
                phase3_days=56, phase3_pnl=0.15,
            )),
        ],
        # --- INTRADAY execution clock (the #270 entry model) ---
        # entry_selection: pre-flight staleness gate → intraday tenkan-reclaim CROSS + rising-vol.
        "entry_selection": [
            Slot(impl=PreFlightStaleness, params=PreFlightStaleness.Params()),
            Slot(impl=BctIntradayGapVolConfirm, params=BctIntradayGapVolConfirm.Params()),
        ],
        # entry_timing: fire a MARKET order intraday on confirm (not next-open MOO).
        "entry_timing": Slot(impl=ConfirmedMarketEntry, params=ConfirmedMarketEntry.Params()),
        # protective_stop: the #290 daily-Kijun GTC catastrophic floor (pre-FIRE, ticket-tracked).
        "protective_stop": Slot(impl=KijunProtectiveStop, params=KijunProtectiveStop.Params()),
        "diagnostics": [
            Slot(impl=VersionMarker, params=VersionMarker.Params()),
            Slot(impl=ChartEmit, params=ChartEmit.Params()),
        ],
    },
)

# Same live-selection gate as champion-asis (no stored universe; floors+rank+cap at lean_entry).
LEAN_ENTRY = True
