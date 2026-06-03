from __future__ import annotations

from typing import Any

import pandas as pd

# The exact contract of qc._indicators[symbol]. Lifecycle populates ALL of these; phases
# read a subset. consolidator is retained so on_securities_changed can dispose it.
#   d_ichi     daily IchimokuKinkoHyo (conditions 5,6: daily>cloud, daily>tenkan)
#   w_ichi     weekly IchimokuKinkoHyo (conditions 1,2,4: weekly>cloud, tenkan>kijun, green)
#   w_close    RollingWindow[float](28) weekly closes (condition 3: chikou vs 26 completed wks)
#   sma200     daily SMA(200) (condition 8: price>200MA)
#   adx        daily ADX(9) (condition 7: adx>=20, +DI>-DI)            [#213f maintained]
#   adx_window RollingWindow[float](5) of ADX values (condition 7: adx_rising = [0]>[3]) [#213f]
#   roc13      daily ROC(13) (parabolic entry block: 13-day run > threshold) [#213f maintained]
#   consolidator  weekly TradeBarConsolidator (disposed on unsubscribe)
# #213f added adx/adx_window/roc13 so the SIGNAL reads maintained indicators O(1)/candidate
# (zero per-bar history → no 10s isolator timeout). NOTE: maintained ADX/ROC are NEW design
# (legacy computed ADX via per-bar history, fit only because its universe was ~326); no
# legacy template — the QC wiring (adx.updated → window; roc convention) is integration-
# verified on the LEAN run, flagged for confirmation.
INDICATOR_KEYS: tuple[str, ...] = (
    "d_ichi", "w_ichi", "w_close", "sma200", "adx", "adx_window", "roc13", "consolidator",
    # #253 entry_selection (BctEntryConfirm §4 Gate 2). ADDITIVE — the SIGNAL/exit phases do
    # NOT read these, so champion-asis scoring/sizing/exit is byte-unchanged (parity intact);
    # only a strategy that wires the entry_selection phase reads them.
    #   macd            daily MACD(12/26/9) (C3 confluence)
    #   macd_hist_window RollingWindow[float](2) of MACD histogram (C3 turning up/down)
    #   vol_sma20       daily SMA(20) of VOLUME (C4 volume >= mult x 20d avg)
    #   tbounce         TBounceTracker — daily sessions-below-Tenkan + gap-up state (C2 degrade)
    #   daily_consolidator  daily TradeBarConsolidator feeding the tbounce tracker (disposed on unsub)
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
        # gap uses the PRIOR bar's close — compute BEFORE overwriting prev_close.
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
            w["close"] = float(row["close"])  # last close wins
            w["volume"] += int(row["volume"])
    # Chronological by Friday — matches legacy `for time in sorted(weeks)` unconditionally
    # (not reliant on the input index being pre-sorted).
    return [weeks[f] for f in sorted(weeks)]
