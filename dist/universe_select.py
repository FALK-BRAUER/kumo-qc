from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

from base import DegradedDataError

ADV_WINDOW: int = 20


@dataclass(slots=True)
class DvWindow:

    dv: deque[float] = field(default_factory=lambda: deque(maxlen=ADV_WINDOW))
    last_seen: int = -1


def rolling_dv_mean(window: deque[float]) -> float:
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
    for ticker, sdv in coarse_dv.items():
        w = windows.get(ticker)
        if w is None:
            w = DvWindow(dv=deque(maxlen=maxlen))
            windows[ticker] = w
        w.dv.append(float(sdv))
        w.last_seen = day_index
    stale = [t for t, w in windows.items() if day_index - w.last_seen >= maxlen]
    for t in stale:
        del windows[t]


def apply_floors(
    bar_metrics: dict[str, tuple[float, float]],
    *,
    min_price: float = 10.0,
    min_avg_dollar_volume: float = 100_000_000.0,
) -> list[str]:
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
    ranked = sorted(eligible, key=lambda t: (-dv_by_ticker.get(t.lower(), 0.0), t))
    return ranked[:coarse_max]
