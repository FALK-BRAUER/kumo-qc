"""#339-RUN1 EXIT-MODEL SCREEN factory — S1 champion + a ProverGatedLoserExit (E1/E2/E3) added to the
exit_hard stack. Fix the realized -15.2% loser tail WITHOUT touching the winners: the prover-gate
exempts any position that ever went >= +5% (a potential monster → full cloud-bottom let-run) and cuts
only never-proved losers earlier. champion_intraday_gapvol.py UNTOUCHED.
"""
from __future__ import annotations

from engine.config import Slot, StrategyConfig
from phases.diagnostics.chart_emit.chart_emit import ChartEmit
from phases.diagnostics.version_marker.version_marker import VersionMarker
from phases.entry_selection.bct_intraday_gap_vol_confirm.bct_intraday_gap_vol_confirm import BctIntradayGapVolConfirm
from phases.entry_selection.preflight_staleness.preflight_staleness import PreFlightStaleness
from phases.entry_timing.confirmed_market_entry.confirmed_market_entry import ConfirmedMarketEntry
from phases.exit.cloud_adherence_trail.cloud_adherence_trail import CloudAdherenceTrail
from phases.exit.prover_gated_loser_exit.prover_gated_loser_exit import ProverGatedLoserExit
from phases.protective_stop.cloud_protective_stop.cloud_protective_stop import CloudProtectiveStop
from phases.regime.spy_200ma.spy_200ma import SpySma200
from phases.regime.vix_percentile.vix_percentile import VixPercentile
from phases.signal.bct_score_full.bct_score_full import BctScoreFull
from phases.sizing.flat_pct_heatcap.flat_pct_heatcap import FlatPctHeatcap
from phases.universe.dv_rank_cap.dv_rank_cap import DvRankCap


def make_config(variant: str) -> StrategyConfig:
    """S1 champion + ProverGatedLoserExit(`variant`) in the exit_hard stack (the ONLY change vs S1)."""
    return StrategyConfig(
        name=f"exit-model-{variant}",
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
            # exit_hard = champion's cloud-bottom trail (handles the proved monsters) + the prover-gated
            # never-proved-loser cut (the ONLY addition vs S1):
            "exit_hard": [
                Slot(impl=CloudAdherenceTrail, params=CloudAdherenceTrail.Params()),
                Slot(impl=ProverGatedLoserExit, params=ProverGatedLoserExit.Params(variant=variant)),
            ],
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
