"""bct-lambdamart-scanner — experimental opt-in learned scanner gate.

This config clones the current `champion_intraday_gapvol` stack and inserts the deployable
`LambdamartScannerRanker` ranking phase. It is not the production champion. The model is loaded
from a QC ObjectStore key by default; local sweeps can override the same runtime field with a path.
"""
from __future__ import annotations

from engine.config import RuntimeConfig, Slot, StrategyConfig
from phases.diagnostics.chart_emit.chart_emit import ChartEmit
from phases.diagnostics.version_marker.version_marker import VersionMarker
from phases.entry_selection.bct_intraday_gap_vol_confirm.bct_intraday_gap_vol_confirm import BctIntradayGapVolConfirm
from phases.entry_selection.preflight_staleness.preflight_staleness import PreFlightStaleness
from phases.entry_timing.confirmed_market_entry.confirmed_market_entry import ConfirmedMarketEntry
from phases.exit.cloud_adherence_trail.cloud_adherence_trail import CloudAdherenceTrail
from phases.protective_stop.cloud_protective_stop.cloud_protective_stop import CloudProtectiveStop
from phases.ranking.lambdamart_scanner_ranker.lambdamart_scanner_ranker import LambdamartScannerRanker
from phases.regime.spy_200ma.spy_200ma import SpySma200
from phases.regime.vix_percentile.vix_percentile import VixPercentile
from phases.signal.bct_score_full.bct_score_full import BctScoreFull
from phases.sizing.flat_pct_heatcap.flat_pct_heatcap import FlatPctHeatcap
from phases.universe.dv_rank_cap.dv_rank_cap import DvRankCap

DEFAULT_SCANNER_RANKER_OBJECTSTORE_KEY = "objectstore://bct_lambdamart_qc_safe_v1.json"

CONFIG = StrategyConfig(
    name="bct-lambdamart-scanner",
    version="0.1.0",
    is_fixture=False,
    continuous_weekly=True,
    runtime=RuntimeConfig(
        scanner_ranker_enabled=True,
        scanner_ranker_model_path=DEFAULT_SCANNER_RANKER_OBJECTSTORE_KEY,
        scanner_ranker_top_x=20,
        scanner_ranker_fallback="raise",
    ),
    phases={
        "universe": Slot(impl=DvRankCap, params=DvRankCap.Params()),
        "signal": Slot(
            impl=BctScoreFull,
            params=BctScoreFull.Params(min_score=7, parabolic_threshold=0.25),
        ),
        "regime": [
            Slot(impl=SpySma200, params=SpySma200.Params()),
            Slot(impl=VixPercentile, params=VixPercentile.Params(vix_percentile_enabled=False)),
        ],
        "ranking": Slot(impl=LambdamartScannerRanker, params=LambdamartScannerRanker.Params()),
        "sizing": Slot(impl=FlatPctHeatcap, params=FlatPctHeatcap.Params(position_pct=0.05, resolution="intraday")),
        "exit_hard": [
            Slot(impl=CloudAdherenceTrail, params=CloudAdherenceTrail.Params()),
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

LEAN_ENTRY = True
