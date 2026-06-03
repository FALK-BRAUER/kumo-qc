from __future__ import annotations

from typing import Any

import pandas as pd

INDICATOR_KEYS: tuple[str, ...] = (
    "d_ichi", "w_ichi", "w_close", "sma200", "adx", "adx_window", "roc13", "consolidator",
    "macd", "macd_hist_window", "vol_sma20", "tbounce", "daily_consolidator",
)


class TBounceTracker:

    __slots__ = (
        "sessions_below_tenkan", "gap_up_frac", "prev_close",
        "last_open", "last_high", "last_low", "last_close",
    )

    def __init__(self) -> None:
        self.sessions_below_tenkan: int = 0
        self.gap_up_frac: float = 0.0
        self.prev_close: float | None = None
        self.last_open: float | None = None
        self.last_high: float | None = None
        self.last_low: float | None = None
        self.last_close: float | None = None

    def update(self, open_: float, high: float, low: float, close: float, tenkan: float) -> None:
        if self.prev_close is not None and self.prev_close > 0.0:
            frac = (open_ - self.prev_close) / self.prev_close
            self.gap_up_frac = frac if frac > 0.0 else 0.0
        else:
            self.gap_up_frac = 0.0

        if tenkan > 0.0 and close < tenkan:
            self.sessions_below_tenkan += 1
        else:
            self.sessions_below_tenkan = 0

        self.last_open = open_
        self.last_high = high
        self.last_low = low
        self.last_close = close
        self.prev_close = close


def weekly_friday(ts: pd.Timestamp) -> pd.Timestamp:
    return (ts + pd.Timedelta(days=(4 - ts.weekday()) % 7)).normalize()


def weekly_aggregate(daily: pd.DataFrame) -> list[dict[str, Any]]:
    if daily is None or daily.empty:
        return []
    cols = {"open", "high", "low", "close", "volume"}
    if not cols.issubset(daily.columns):
        return []

    weeks: dict[pd.Timestamp, dict[str, Any]] = {}
    for ts, row in daily.iterrows():
        friday = weekly_friday(ts)
        if friday not in weeks:
            weeks[friday] = {
                "friday": friday,
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": int(row["volume"]),
            }
        else:
            w = weeks[friday]
            w["high"] = max(w["high"], float(row["high"]))
            w["low"] = min(w["low"], float(row["low"]))
            w["close"] = float(row["close"])
            w["volume"] += int(row["volume"])
    return [weeks[f] for f in sorted(weeks)]
