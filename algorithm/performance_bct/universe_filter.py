"""
Phase 3: BCT Universe Filter
Coarse: 6,000 US equities → ~200 liquid names
Fine:   pass-through — BCT scoring (Ichimoku + ADX) requires History() calls
        and runs in the main algorithm's scheduled rebalance, not here.
"""
from typing import List
from AlgorithmImports import *  # noqa: F401,F403  — QC LEAN runtime namespace


class BCTUniverseFilter:
    """
    Plug into the main algorithm:

        self._universe_filter = BCTUniverseFilter()
        self.add_universe(
            self._universe_filter.coarse_selection,
            self._universe_filter.fine_selection,
        )

    BCT signal scoring happens in the scheduled rebalance function after
    the universe settles, not inside fine_selection.
    """

    # Coarse thresholds — tune in Phase 4 backtest validation
    MIN_PRICE: float = 10.0
    MIN_DOLLAR_VOLUME: float = 5_000_000  # $5M/day liquidity floor
    COARSE_MAX: int = 9999

    def coarse_selection(self, coarse: List[CoarseFundamental]) -> List[Symbol]:
        """
        - has_fundamental_data: excludes ETFs, ADRs, OTC/pink-sheet names
          (QC's Morningstar dataset covers ~8,100 US equities only)
        - price > MIN_PRICE: removes sub-$10 names
        - dollar_volume > MIN_DOLLAR_VOLUME: liquidity floor
        Sorted by dollar_volume desc, capped at COARSE_MAX.
        """
        candidates = [
            c for c in coarse
            if c.has_fundamental_data
            and c.price >= self.MIN_PRICE
            and c.dollar_volume >= self.MIN_DOLLAR_VOLUME
        ]
        candidates.sort(key=lambda c: c.dollar_volume, reverse=True)
        return [c.symbol for c in candidates[: self.COARSE_MAX]]

    def fine_selection(self, fine: List[FineFundamental]) -> List[Symbol]:
        return [f.symbol for f in fine]
