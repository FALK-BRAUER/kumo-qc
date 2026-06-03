"""champion-intraday-gapvol — the #270 daily-signal → intraday-confirmed execution champion.

The forward champion that supersedes the champion-asis blind-entry FIXTURE. Same proven per-ticker
BCT selection + regime + sizing + EXIT as champion-asis, but the entry is no longer a phantom
market-on-open: the daily 8-condition signal picks candidates (after close T, for T+1), and on T+1's
INTRADAY (5-min) clock the engine confirms before firing.

S1 promotion (#339): the EXIT stack is the cloud-adherence winner — CloudAdherenceTrail (daily EOD
exit when close < the daily cloud bottom) + CloudProtectiveStop (GTC catastrophic floor at the same
cloud bottom), sizing flat 5%, CONTINUOUS_WEEKLY corrected-weekly (#336). Rotation + profit-take OFF.

Two clocks (engine _partition_clocks routes per-KIND; #270/#274/#313):
  DAILY decision clock (scheduled after-close, #313): universe → signal → regime → sizing →
    exit_hard (CloudAdherenceTrail — EOD close < daily cloud bottom; EOD-only, intraday stop-
    monitoring destroys the W1-W4 edge, fintrack Run-8 lesson) → diagnostics. Produces the
    candidate snapshot (276b-0) for T+1.
  INTRADAY execution clock (5-min, on_data): the candidate stubs are injected, then
    entry_selection (PreFlightStaleness → BctIntradayConfirm: asymmetric gap-gate, then tenkan-
    reclaim CROSS + rising-vol) → entry_timing (ConfirmedMarketEntry: market fire on confirm) →
    protective_stop (CloudProtectiveStop: GTC catastrophic floor at the daily cloud bottom) →
    FIRE_ENTRIES.

The CloudProtectiveStop GTC floor is the touch-fire catastrophic backstop (gap/halt); the daily
CloudAdherenceTrail exit is the normal close-breach; the engine cancels one when the other fires
(no double-exit, FIRE_EXITS → _cancel_protective_stop).

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
from phases.exit.cloud_adherence_trail.cloud_adherence_trail import CloudAdherenceTrail
from phases.protective_stop.cloud_protective_stop.cloud_protective_stop import CloudProtectiveStop
from phases.regime.spy_200ma.spy_200ma import SpySma200
from phases.regime.vix_percentile.vix_percentile import VixPercentile
from phases.signal.bct_score_full.bct_score_full import BctScoreFull
from phases.sizing.flat_pct_heatcap.flat_pct_heatcap import FlatPctHeatcap
from phases.universe.dv_rank_cap.dv_rank_cap import DvRankCap

CONFIG = StrategyConfig(
    name="champion-intraday-gapvol",
    version="1.0.0",
    is_fixture=False,  # a real champion: entry-confirm + exit wired → passes the #272 gate
    continuous_weekly=True,  # #336/#339 S1: corrected-weekly Ichimoku (continuous self.history)
    phases={
        # --- DAILY decision clock (selection/regime as champion-asis; sizing+exit = S1 #339) ---
        "universe": Slot(impl=DvRankCap, params=DvRankCap.Params()),
        "signal": Slot(
            impl=BctScoreFull,
            params=BctScoreFull.Params(min_score=7, parabolic_threshold=0.25),
        ),
        "regime": [
            Slot(impl=SpySma200, params=SpySma200.Params()),
            Slot(impl=VixPercentile, params=VixPercentile.Params(vix_percentile_enabled=False)),
        ],
        # sizing on the INTRADAY clock (#276b-1): the confirmed entry is sized at confirm time on
        # the 5-min clock — the whole entry-execution chain (selection→timing→sizing→floor→FIRE)
        # shares the intraday clock (the engine's entry-chain-clock guard enforces this).
        "sizing": Slot(impl=FlatPctHeatcap, params=FlatPctHeatcap.Params(position_pct=0.05, resolution="intraday")),
        # EXIT = S1 winner (#339): CloudAdherenceTrail — daily EOD exit when close < the daily cloud
        # bottom (Ichimoku Kumo floor). Replaces KijunG3Exits; pairs with the CloudProtectiveStop
        # GTC floor below (both keyed to the daily cloud, coherent let-the-cloud-decide exit stack).
        "exit_hard": [
            Slot(impl=CloudAdherenceTrail, params=CloudAdherenceTrail.Params()),
        ],
        # --- INTRADAY execution clock (the #270 entry model) ---
        # entry_selection: pre-flight staleness gate → intraday tenkan-reclaim CROSS + rising-vol.
        "entry_selection": [
            Slot(impl=PreFlightStaleness, params=PreFlightStaleness.Params()),
            Slot(impl=BctIntradayGapVolConfirm, params=BctIntradayGapVolConfirm.Params()),
        ],
        # entry_timing: fire a MARKET order intraday on confirm (not next-open MOO).
        "entry_timing": Slot(impl=ConfirmedMarketEntry, params=ConfirmedMarketEntry.Params()),
        # protective_stop: S1 (#339) GTC catastrophic floor at the daily cloud bottom (pre-FIRE,
        # ticket-tracked). Replaces the Kijun floor; coherent with the CloudAdherenceTrail exit.
        "protective_stop": Slot(impl=CloudProtectiveStop, params=CloudProtectiveStop.Params()),
        "diagnostics": [
            Slot(impl=VersionMarker, params=VersionMarker.Params()),
            Slot(impl=ChartEmit, params=ChartEmit.Params()),
        ],
    },
)

# Same live-selection gate as champion-asis (no stored universe; floors+rank+cap at lean_entry).
LEAN_ENTRY = True
