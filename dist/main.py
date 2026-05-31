from config import Slot, StrategyConfig
from engine import StrategyEngine
from phase_universe_dv_rank_cap import DvRankCap
from phase_signal_bct_score_full import BctScoreFull
from phase_regime_spy_200ma import SpySma200
from phase_regime_vix_percentile import VixPercentile
from phase_entry_selection_bct_entry_confirm import BctEntryConfirm
from phase_entry_timing_market_on_open_entry import MarketOnOpenEntry
from phase_sizing_score_tier_heatcap import ScoreTierHeatcap
from phase_exit_kijun_g3_exits import KijunG3Exits
from phase_diagnostics_version_marker import VersionMarker
from phase_diagnostics_chart_emit import ChartEmit
from lean_entry import BctEngineAlgorithm

STRATEGY_CONFIG = StrategyConfig(
    name='champion-entry-sized',
    version='1.0.0',
    phases={
    'universe': Slot(impl=DvRankCap, params=DvRankCap.Params(enabled=True)),
    'signal': Slot(impl=BctScoreFull, params=BctScoreFull.Params(min_score=7, parabolic_threshold=0.25, enabled=True)),
    'regime': [Slot(impl=SpySma200, params=SpySma200.Params(enabled=True)), Slot(impl=VixPercentile, params=VixPercentile.Params(vix_percentile_enabled=False, vix_percentile_threshold=75.0, vix_percentile_lookback=504, enabled=True))],
    'entry_selection': Slot(impl=BctEntryConfirm, params=BctEntryConfirm.Params(macd_fast=12, macd_slow=26, macd_signal=9, volume_gate_mult=1.0, tenkan_pullback_tol=0.005, flat_eps=0.002, gap_up_threshold=0.01, min_confirm=2, enabled=True)),
    'entry_timing': Slot(impl=MarketOnOpenEntry, params=MarketOnOpenEntry.Params(enabled=True)),
    'sizing': Slot(impl=ScoreTierHeatcap, params=ScoreTierHeatcap.Params(position_pct=0.1, full=1.0, three_quarter=0.75, half=0.5, min_score=2, enabled=True)),
    'exit_hard': [Slot(impl=KijunG3Exits, params=KijunG3Exits.Params(cloud_exit_enabled=False, weekly_kijun_exit_enabled=False, phase3_days=56, phase3_pnl=0.15, enabled=True))],
    'diagnostics': [Slot(impl=VersionMarker, params=VersionMarker.Params(enabled=True)), Slot(impl=ChartEmit, params=ChartEmit.Params(enabled=True, chart_name='Universe'))],
    },
)


class BCTAlgorithm(BctEngineAlgorithm):
    STRATEGY_CONFIG = STRATEGY_CONFIG
