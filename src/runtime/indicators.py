"""Indicator lifecycle helpers (#213c) — the pure, golden-masterable pieces.

The per-symbol indicator PLUMBING (QC native ichimoku/sma + a weekly consolidator) lives
in runtime.lean_entry (QC runtime). The one piece that is pure Python — and parity-critical
— is the manual daily->weekly aggregation. It is carved EXACTLY from the legacy champion's
_seed_weekly (algorithm/performance_bct/main.py): the proven workaround for the QC-cloud
DataFrame.resample() 5-minute timeout (commit 8048c29). Reproduce faithfully; do NOT
re-optimize (honest baseline first).

INDICATOR_KEYS is the documented contract of qc._indicators[symbol] — the lifecycle
populates exactly these; the phases (bct_score_full pre-filter, kijun_g3_exits) read them.
"""
from __future__ import annotations

from collections import deque
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
    """Maintained §2-Component-2 (T-Bounce) state — pure, history-free, DAILY-OHLC-fed.

    HQ ruling (#253-P1): C2 must read the latest DAILY OHLC BAR (open/high/low/close), NOT the
    live close-snapshot — the pullback (C2b) is a daily-LOW touch and the bounce (C2c) is a
    daily-candle bullish-close / lower-wick rejection. This tracker stores the LATEST completed
    daily bar so the entry phase reads it O(1) (no per-bar history). It also maintains the two
    recent-context degrade inputs:
      - `sessions_below_tenkan` (consecutive daily closes below daily Tenkan; degrade C2 when >3).
      - `gap_up_frac` = today's open vs the PRIOR daily close (degrade C2 when > gap_up_threshold,
        the Rule #10 first-test-after-gap-up guard; HQ default 1%).

    update(open_, high, low, close, tenkan) is called once per completed daily bar (the daily
    consolidator in lean_entry feeds it). Pure float state — golden-masterable, no QC types.
    `last_*` are None until the first bar (the phase declines a candidate with no daily bar yet).
    The George-style ranking experiment also reads prior-high and relative-volume state from the
    same completed daily bars; these values are optional and fail conservative until populated.
    """

    __slots__ = (
        "sessions_below_tenkan", "gap_up_frac", "prev_close",
        "last_open", "last_high", "last_low", "last_close", "last_volume",
        "prior_high20", "prior_high50", "prior_high252", "rel_volume20",
        "_high20", "_high50", "_high252", "_vol20",
    )

    def __init__(self) -> None:
        self.sessions_below_tenkan: int = 0
        self.gap_up_frac: float = 0.0
        self.prev_close: float | None = None
        self.last_open: float | None = None
        self.last_high: float | None = None
        self.last_low: float | None = None
        self.last_close: float | None = None
        self.last_volume: float | None = None
        self.prior_high20: float | None = None
        self.prior_high50: float | None = None
        self.prior_high252: float | None = None
        self.rel_volume20: float | None = None
        self._high20: deque[float] = deque(maxlen=20)
        self._high50: deque[float] = deque(maxlen=50)
        self._high252: deque[float] = deque(maxlen=252)
        self._vol20: deque[float] = deque(maxlen=20)

    def update(
        self,
        open_: float,
        high: float,
        low: float,
        close: float,
        tenkan: float,
        volume: float | None = None,
    ) -> None:
        """Fold one completed daily bar into the maintained T-Bounce state.

        Stores the bar as `last_open/high/low/close` (C2 reads these), then updates:
        sessions_below_tenkan: increment while close < Tenkan, reset to 0 the day close >= Tenkan.
        gap_up_frac: (open - prev_close)/prev_close, clamped at >= 0 (only UP gaps matter; a
          gap-down is 0.0). First bar (no prior close) -> 0.0. Uses the PRIOR close (set last bar).
        prior_high20/50/252: max high in each completed-bar window BEFORE the current bar.
        rel_volume20: current completed-bar volume versus the PRIOR 20-bar average.
        """
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

        self.prior_high20 = max(self._high20) if self._high20 else None
        self.prior_high50 = max(self._high50) if self._high50 else None
        self.prior_high252 = max(self._high252) if self._high252 else None
        if volume is not None and self._vol20:
            avg_volume = sum(self._vol20) / len(self._vol20)
            self.rel_volume20 = volume / avg_volume if avg_volume > 0.0 else None
        else:
            self.rel_volume20 = None

        self.last_open = open_
        self.last_high = high
        self.last_low = low
        self.last_close = close
        self.last_volume = volume
        self.prev_close = close
        self._high20.append(high)
        self._high50.append(high)
        self._high252.append(high)
        if volume is not None:
            self._vol20.append(volume)


def weekly_friday(ts: pd.Timestamp) -> pd.Timestamp:
    """The Friday of ts's week, normalized — the weekly bucket key. Exact legacy rule:
    ts + (4 - weekday) % 7 days, normalized to midnight (Mon..Sun -> that week's Friday)."""
    return (ts + pd.Timedelta(days=(4 - ts.weekday()) % 7)).normalize()


def weekly_aggregate(daily: pd.DataFrame) -> list[dict[str, Any]]:
    """Aggregate a daily OHLCV frame into weekly (W-FRI) bars — the manual aggregation the
    legacy champion uses INSTEAD of df.resample (the QC-cloud timeout fix). Returns weekly
    bars in chronological order, each {friday, open, high, low, close, volume}.

    Rules (exact carve): first daily bar of a Friday-week sets OHLCV; subsequent bars in the
    same week extend high/low, overwrite close (last), accumulate volume. open is the FIRST
    day's open. Same result as resample('W-FRI').agg(first/max/min/last/sum), without the
    pandas-resample overhead that trips the cloud 5-min limit.

    Expects lowercased columns {open, high, low, close, volume} and a datetime index. Returns
    [] if columns are missing or the frame is empty.
    """
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
