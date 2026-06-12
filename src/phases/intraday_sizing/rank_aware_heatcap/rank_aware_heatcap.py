"""Intraday-sizing phase: scanner-rank-aware heat-cap adapter.

Kind: intraday_sizing
Marker: intraday_rank_aware_heatcap_v1

This adapter reuses the canonical rank-aware sizing behavior, but declares the intraday sizing kind
so two-clock strategies can replace `StubIntradaySizer` without adding a second sizing axis.
"""
from __future__ import annotations

from phases.sizing.rank_aware_heatcap.rank_aware_heatcap import (
    RankAwareHeatcap as DailyRankAwareHeatcap,
    rank_multiplier,
)


class RankAwareHeatcap(DailyRankAwareHeatcap):
    PHASE_KIND = "intraday_sizing"
    PHASE_RESOLUTION = "intraday"
    REQUIRES_UPSTREAM = ["entry_trigger", "scanner_ranker_features"]

    @property
    def version_marker(self) -> str:
        return "intraday_rank_aware_heatcap_v1"


__all__ = ["RankAwareHeatcap", "rank_multiplier"]
