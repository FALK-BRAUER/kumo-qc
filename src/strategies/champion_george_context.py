"""champion-george-context — champion-entry-sized plus George-style industry context ranking.

Controlled experiment config:
    champion-entry-sized stack
    + rebalance(industry_warmup)
    + ranking(george_industry_attention)

The delta tests whether top-down industry heat, ETF/proxy attention, transcript/scanner priors,
and persistent watchlist memory improve candidate ordering before entry confirmation and sizing.
"""
from __future__ import annotations

from engine.config import Slot, StrategyConfig
from phases.diagnostics.chart_emit.chart_emit import ChartEmit
from phases.diagnostics.version_marker.version_marker import VersionMarker
from phases.entry_selection.bct_entry_confirm.bct_entry_confirm import BctEntryConfirm
from phases.entry_timing.market_on_open_entry.market_on_open_entry import MarketOnOpenEntry
from phases.exit.kijun_g3_exits.kijun_g3_exits import KijunG3Exits
from phases.ranking.george_industry_attention.george_industry_attention import GeorgeIndustryAttention
from phases.rebalance.industry_warmup.industry_warmup import IndustryWarmup
from phases.regime.spy_200ma.spy_200ma import SpySma200
from phases.regime.vix_percentile.vix_percentile import VixPercentile
from phases.signal.bct_score_full.bct_score_full import BctScoreFull
from phases.sizing.score_tier_heatcap.score_tier_heatcap import ScoreTierHeatcap
from phases.universe.dv_rank_cap.dv_rank_cap import DvRankCap

CONFIG = StrategyConfig(
    name="champion-george-context",
    version="0.1.0",
    phases={
        "rebalance": Slot(
            impl=IndustryWarmup,
            params=IndustryWarmup.Params(top_n=5),
        ),
        "universe": Slot(impl=DvRankCap, params=DvRankCap.Params()),
        "signal": Slot(
            impl=BctScoreFull,
            params=BctScoreFull.Params(min_score=7, parabolic_threshold=0.25),
        ),
        "regime": [
            Slot(impl=SpySma200, params=SpySma200.Params()),
            Slot(impl=VixPercentile, params=VixPercentile.Params(vix_percentile_enabled=False)),
        ],
        "ranking": Slot(
            impl=GeorgeIndustryAttention,
            params=GeorgeIndustryAttention.Params(),
        ),
        "entry_selection": Slot(
            impl=BctEntryConfirm,
            params=BctEntryConfirm.Params(),
        ),
        "entry_timing": Slot(
            impl=MarketOnOpenEntry,
            params=MarketOnOpenEntry.Params(),
        ),
        "sizing": Slot(
            impl=ScoreTierHeatcap,
            params=ScoreTierHeatcap.Params(
                position_pct=0.10, full=1.00, three_quarter=0.75, half=0.50, min_score=2,
            ),
        ),
        "exit_hard": [
            Slot(impl=KijunG3Exits, params=KijunG3Exits.Params(
                cloud_exit_enabled=False, weekly_kijun_exit_enabled=False,
                phase3_days=56, phase3_pnl=0.15,
            )),
        ],
        "diagnostics": [
            Slot(impl=VersionMarker, params=VersionMarker.Params()),
            Slot(impl=ChartEmit, params=ChartEmit.Params()),
        ],
    },
)

LEAN_ENTRY = True
