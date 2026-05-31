"""Live universe selection (#238) — the pure filter→rank→cap, run ONCE-DAILY, no file.

LOCAL SIMULATES CLOUD (charter): the universe is computed LIVE each day from QC's coarse
feed (cloud = ground truth); local runs this IDENTICAL code on conformed-coarse data to
approximate cloud. NO precomputed/shipped universe file (a stored date→ticker file is a
frozen universe — the 326 scar). This is the same filter+rank LOGIC the (now-retired)
build_filter/build_universe held, run live.

Two-stage, matching the documented QC trailing-metric pattern:
  1. PREFILTER (cheap, on coarse single-day data): keep names with single-day dollar-volume
     >= prefilter_dv. A LOOSE PERF-BOUND (default 25M, well under the 100M decision floor) to
     bound the once-daily history call — NOT a strategy threshold. Single-day DV dips below
     the 20d-mean on quiet days, so it must be loose or it false-drops valid names.
  2. PRECISE (on RAW history of survivors): latest close >= min_price AND trailing-adv_window
     mean dollar-volume >= min_avg_dollar_volume; rank by trailing DV DESC (ticker-asc
     tiebreak); cap to coarse_max. RAW decides the floor+rank (the coarse prefilter only bounds).

This module is PURE (no QC types): the caller (runtime.lean_entry coarse_selection) supplies
coarse rows + a RAW-history-derived {ticker: (close, trailing_dv)} map. Unit-tested + golden-
mastered vs an inline reference. The QC history fetch + add_universe wiring live in lean_entry.
"""
from __future__ import annotations


def select_live_universe(
    coarse_dollar_volume: dict[str, float],
    raw: dict[str, tuple[float, float]],
    *,
    prefilter_dv: float = 25_000_000.0,
    min_price: float = 10.0,
    min_avg_dollar_volume: float = 100_000_000.0,
    coarse_max: int = 9999,
) -> list[str]:
    """Return today's ranked candidate tickers (rank order), live filter→rank→cap.

    coarse_dollar_volume: {ticker -> single-day dollar volume} from the coarse feed (prefilter).
    raw: {ticker -> (latest_close, trailing_adv_window_mean_dollar_volume)} from RAW history of
         the prefilter survivors (the PRECISE decision data). Names absent from `raw` (no
         history) are dropped.
    """
    # Stage 1 — prefilter on coarse single-day DV (loose perf-bound).
    survivors = [t for t, sdv in coarse_dollar_volume.items() if sdv >= prefilter_dv]
    # Stage 2 — precise floors on RAW history, then DV-desc rank (ticker-asc tiebreak), cap.
    eligible: dict[str, float] = {}
    for t in survivors:
        rv = raw.get(t)
        if rv is None:
            continue
        close, trailing_dv = rv
        if close >= min_price and trailing_dv >= min_avg_dollar_volume:
            eligible[t] = trailing_dv
    ranked = sorted(eligible.items(), key=lambda kv: (-kv[1], kv[0]))
    return [t for t, _dv in ranked[:coarse_max]]
