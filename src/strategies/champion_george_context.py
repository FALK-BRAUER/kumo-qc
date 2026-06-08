"""champion-george-context - intraday champion plus George-style context ranking.

Controlled experiment config:
    champion-intraday-gapvol stack
    + rebalance(industry_warmup)
    + ranking(george_industry_attention)

The point is to test top-down industry heat, ETF/proxy attention, transcript/scanner priors, and
watchlist memory without drifting away from the executable intraday architecture. The entry
execution stack remains the current two-clock model from champion-intraday-gapvol: daily signal,
intraday gap/volume confirmation, confirmed-market entry, intraday sizing, cloud protective stop,
and cloud-adherence exit.
"""
from __future__ import annotations

from engine.config import Slot, StrategyConfig
from phases.ranking.george_industry_attention.george_industry_attention import GeorgeIndustryAttention
from phases.rebalance.industry_warmup.industry_warmup import IndustryWarmup
from strategies.champion_intraday_gapvol import CONFIG as INTRADAY_GAPVOL

CONFIG = StrategyConfig(
    name="champion-george-context",
    version="0.3.0",
    is_fixture=False,
    continuous_weekly=INTRADAY_GAPVOL.continuous_weekly,
    phases={
        "rebalance": Slot(
            impl=IndustryWarmup,
            params=IndustryWarmup.Params(top_n=5),
        ),
        **dict(INTRADAY_GAPVOL.phases),
        "ranking": Slot(
            impl=GeorgeIndustryAttention,
            params=GeorgeIndustryAttention.Params(),
        ),
    },
)

LEAN_ENTRY = True
