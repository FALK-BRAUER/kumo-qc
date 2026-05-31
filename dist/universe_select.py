"""Pure floor + rank helpers (#238 / Y) — the live universe, computed ONCE-DAILY at selection.

LOCAL SIMULATES CLOUD (charter): the universe is computed LIVE each day from QC's coarse
feed (cloud = ground truth); local runs this IDENTICAL code on conformed-coarse data to
approximate cloud. NO precomputed/shipped universe file (a stored date→ticker file is a
frozen universe — the 326 scar).

Y (Falk): the floors + rank are applied AT THE SELECTION GATE (runtime.lean_entry.
_coarse_selection), NOT in a per-bar phase. These two pure helpers are the cores it calls,
in sequence, once-daily:
  - `apply_floors`  → the PRECISE tradeability floors (close ≥ min_price AND
                      trailing_dv ≥ min_avg_dollar_volume) — the SELECTION GATE that bounds
                      subscription (only qualifying names get tracked + Ichimoku'd).
  - `rank_and_cap`  → ranks the eligible names by trailing DV DESC (ticker-ASC tiebreak) and
                      caps to coarse_max → qc._ranked_today.
The PREFILTER (loose single-day-DV perf-bound) + the RAW-history trailing-metric build live
in runtime.lean_entry._coarse_selection, which produces the `bar_metrics` map these helpers
consume — computed ONCE, never recomputed. The universe phase (dv_rank_cap) only EXPOSES the
resulting qc._ranked_today; it neither floors nor ranks.

Both helpers are PURE (no QC types): unit-tested + golden-mastered vs an inline reference on
identical bars. The QC history fetch + add_universe wiring live in lean_entry.

SCALING FIX (incremental-DV): the trailing-DV that feeds apply_floors is no longer rebuilt
by a per-day history() fan-out (~20x slower on cloud). It is MAINTAINED as a rolling 20-day
window per coarse name, pushed ONCE per day from the COARSE feed's single-day DV. (Local:
coarse single-day DV is bit-identical to RAW close*volume by the #238 conform — see GATE 1,
a local tautology, not cloud proof. Cloud robustness rests on DV being split-invariant, which
is sound for a LIQUIDITY floor but does not cover dividend-adjust; validated at the cloud
Step-A active-set parity, not asserted here.) `rolling_dv_mean` / `update_dv_windows` below
are the pure cores; lean_entry maintains qc._dv_windows with them.

ASSUMPTION (the one residual vs the old history() path): the maintained rolling-20d mean
equals the old history(20) trailing mean ONLY IF the coarse feed delivers every tradeable
name on every day it actually trades (so a feed gap == a genuine non-trading day, injecting
nothing). A 1-19 day coarse-feed gap on a name that DID trade would, on reappearance, blend
stale DV (the pre-gap days still in the window) — whereas history(20) would fetch the last 20
ACTUAL bars. Benign under the normal QC coarse contract (liquid names appear every trading
day); stated here as the assumption rather than a claim of bit-identical semantics. The pure
arithmetic itself is golden-mastered: mean(window) == mean(inputs[-20:]) on identical inputs.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

from base import DegradedDataError

ADV_WINDOW: int = 20  # trailing trading-day window for the maintained mean-DV decision


@dataclass(slots=True)
class DvWindow:
    """Per-ticker maintained rolling DV state. `dv` is the bounded (maxlen=ADV_WINDOW) deque of
    daily dollar-volumes (index 0 = oldest, [-1] = today); `last_seen` is the day_index of the
    most recent coarse-feed appearance, used to evict long-absent names (memory bound)."""

    dv: deque[float] = field(default_factory=lambda: deque(maxlen=ADV_WINDOW))
    last_seen: int = -1


def rolling_dv_mean(window: deque[float]) -> float:
    """Mean of a maintained rolling DV deque == the OLD path's mean(close*volume over the
    trailing window). Empty window -> 0.0 (a name with no observed DV is never tradeable)."""
    n = len(window)
    if n == 0:
        return 0.0
    return sum(window) / n


def update_dv_windows(
    windows: dict[str, DvWindow],
    coarse_dv: dict[str, float],
    *,
    day_index: int,
    maxlen: int = ADV_WINDOW,
) -> None:
    """Maintain qc._dv_windows for ONE day (in place). For every ticker in today's coarse feed,
    push its single-day DV (the deque auto-drops the 21-days-ago value at maxlen) and stamp
    last_seen=day_index. A name ABSENT today simply does not update (a 1-day gap injects no
    zero — the trailing mean is over OBSERVED days, matching the history() path which also only
    saw real bars). Names absent for >= maxlen consecutive days are STALE (their window would
    have fully aged out) and are evicted to bound memory. Pure: no QC types, deterministic."""
    for ticker, sdv in coarse_dv.items():
        w = windows.get(ticker)
        if w is None:
            w = DvWindow(dv=deque(maxlen=maxlen))
            windows[ticker] = w
        w.dv.append(float(sdv))
        w.last_seen = day_index
    # Evict names not seen for >= maxlen days (memory bound). A still-present name has
    # last_seen == day_index, so it never trips this.
    stale = [t for t, w in windows.items() if day_index - w.last_seen >= maxlen]
    for t in stale:
        del windows[t]


def apply_floors(
    bar_metrics: dict[str, tuple[float, float]],
    *,
    min_price: float = 10.0,
    min_avg_dollar_volume: float = 100_000_000.0,
) -> list[str]:
    """PRECISE tradeability floors on the trailing metrics. Returns eligible tickers
    (close >= min_price AND trailing_dv >= min_avg_dollar_volume), SORTED for determinism.

    FAIL-LOUD GUARD (#261-1): a non-finite (NaN/Inf) dollar-volume, or a non-finite/negative
    close, is DEGRADED data — it must RAISE, never silently rank/admit. An Inf DV would pass
    `dv >= floor` AND dominate the DV-desc rank (Inf > any real DV → garbage selected #1); a
    NaN would silently vanish (comparison False) — both are the silent-mirage class. The floor
    arithmetic runs only on FINITE, sign-sane metrics; anything else crashes with the offending
    ticker + value so the degraded feed is diagnosable, not absorbed into the universe."""
    for t, (close, dv) in bar_metrics.items():
        if not math.isfinite(dv):
            raise DegradedDataError(
                f"non-finite trailing dollar_volume at selection gate: ticker={t!r} dv={dv!r} "
                f"(close={close!r}); degraded data must fail loud, never rank/admit (#261-1)"
            )
        if not math.isfinite(close) or close < 0.0:
            raise DegradedDataError(
                f"non-finite/negative close at selection gate: ticker={t!r} close={close!r} "
                f"(dv={dv!r}); degraded data must fail loud, never rank/admit (#261-1)"
            )
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
