"""Pure watchlist carry helper for the LEAN selection gate.

Watchlist carry is subscription behavior: if a George-style ranker kept a name warm in
`qc._george_watchlist`, the selection gate may append a bounded number of those names to the
normally floored/ranked universe so they stay subscribed and indicator-warmed. This module is pure
and string-keyed; `lean_entry._coarse_selection` owns QC Symbol construction and logging.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class WatchlistCarryCandidate:
    ticker: str
    score: float
    age_days: int
    price: float
    trailing_dv: float
    reason: str


def _row_score(row: Any) -> float:
    if isinstance(row, dict):
        return float(row.get("score", 1.0))
    return 1.0


def _row_age(row: Any) -> int:
    if isinstance(row, dict):
        return int(row.get("age_days", 0))
    return 0


def _row_reason(row: Any) -> str:
    if isinstance(row, dict):
        raw = row.get("reason") or row.get("source") or row.get("industry") or "watchlist"
        return str(raw)
    return "watchlist"


def select_watchlist_carry(
    watchlist: dict[Any, Any],
    bar_metrics: dict[str, tuple[float, float]],
    ranked: list[str],
    *,
    max_names: int,
    min_price: float,
    min_avg_dollar_volume: float,
) -> tuple[list[WatchlistCarryCandidate], dict[str, str]]:
    """Return bounded watchlist names eligible for subscription carry.

    Eligibility is intentionally stricter than "exists in the watchlist": the ticker must appear in
    today's coarse-derived `bar_metrics`, pass raw price/liquidity carry floors, and not already be
    in the normal ranked selection. Ordering is deterministic: score desc, age asc, ticker asc.
    """
    if max_names <= 0 or not watchlist:
        return [], {}

    ranked_set = {str(t).lower() for t in ranked}
    candidates: list[WatchlistCarryCandidate] = []
    rejected: dict[str, str] = {}
    for raw_ticker, row in watchlist.items():
        ticker = str(raw_ticker).lower()
        if ticker in ranked_set:
            rejected[ticker] = "already_ranked"
            continue
        metrics = bar_metrics.get(ticker)
        if metrics is None:
            rejected[ticker] = "missing_bar_metrics"
            continue
        price, trailing_dv = metrics
        if price < min_price:
            rejected[ticker] = "below_price_floor"
            continue
        if trailing_dv < min_avg_dollar_volume:
            rejected[ticker] = "below_dv_floor"
            continue
        candidates.append(
            WatchlistCarryCandidate(
                ticker=ticker,
                score=_row_score(row),
                age_days=_row_age(row),
                price=float(price),
                trailing_dv=float(trailing_dv),
                reason=_row_reason(row),
            )
        )

    candidates.sort(key=lambda c: (-c.score, c.age_days, c.ticker))
    return candidates[:max_names], rejected
