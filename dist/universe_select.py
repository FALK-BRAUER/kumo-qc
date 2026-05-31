"""Pure floor + rank helpers (#238 / R1 un-fuse) — the live universe, computed ONCE-DAILY.

LOCAL SIMULATES CLOUD (charter): the universe is computed LIVE each day from QC's coarse
feed (cloud = ground truth); local runs this IDENTICAL code on conformed-coarse data to
approximate cloud. NO precomputed/shipped universe file (a stored date→ticker file is a
frozen universe — the 326 scar).

R1 UN-FUSE (Falk): the FILTER and the RANK are DISTINCT engine phases now, filter FIRST.
These two helpers are the pure cores they call:
  - `apply_floors`  → the FILTER phase (tradeability_floors) applies the PRECISE floors
                      (close ≥ min_price AND trailing_dv ≥ min_avg_dollar_volume).
  - `rank_and_cap`  → the RANK phase (dv_rank_cap) ranks the eligible names by trailing DV
                      DESC (ticker-ASC tiebreak) and caps to coarse_max.
The PREFILTER (loose single-day-DV perf-bound) + the RAW-history trailing-metric build live
upstream in runtime.lean_entry._coarse_selection, which produces the `bar_metrics` map these
helpers consume — computed ONCE, never recomputed.

Both helpers are PURE (no QC types): unit-tested + golden-mastered vs an inline reference on
identical bars. The QC history fetch + add_universe wiring live in lean_entry.
"""
from __future__ import annotations


def apply_floors(
    bar_metrics: dict[str, tuple[float, float]],
    *,
    min_price: float = 10.0,
    min_avg_dollar_volume: float = 100_000_000.0,
) -> list[str]:
    """PRECISE tradeability floors on the trailing metrics. Returns eligible tickers
    (close >= min_price AND trailing_dv >= min_avg_dollar_volume), SORTED for determinism."""
    return sorted(
        t for t, (close, dv) in bar_metrics.items()
        if close >= min_price and dv >= min_avg_dollar_volume
    )


def rank_and_cap(
    eligible: list[str],
    dv_by_ticker: dict[str, float],
    *,
    coarse_max: int = 9999,
) -> list[str]:
    """Rank the eligible tickers by trailing DV DESC (ticker-ASC tiebreak), cap to coarse_max.
    dv lookup is case-insensitive (eligible may be uppercase canonical; dv keys lowercase)."""
    ranked = sorted(eligible, key=lambda t: (-dv_by_ticker.get(t.lower(), 0.0), t))
    return ranked[:coarse_max]
