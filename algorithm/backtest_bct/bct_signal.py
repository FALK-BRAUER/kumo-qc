"""BCT signal scorer — George's Blue Cloud Trading 8-condition Blue Flag checklist.

No top-level QuantConnect imports — safe to import outside the LEAN runtime.
QC Resolution enum is imported lazily inside score_symbol().
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


# Bar counts fetched from QC History API
# QC has no Resolution.Weekly — weekly bars are derived by resampling daily.
# Daily bars needed: max(130 weeks * 5 days, 300 daily) + buffer → 700
_WEEKLY_BARS = 130   # target weekly bars (derived from daily resample)
_DAILY_BARS = 700    # covers 130 weekly bars (650 trading days) + 300-bar daily window


def _mid(high: pd.Series, low: pd.Series, period: int) -> pd.Series:
    """Ichimoku midpoint line: (period-high + period-low) / 2."""
    return (high.rolling(period).max() + low.rolling(period).min()) / 2


def _adx_wilder(
    df: pd.DataFrame, period: int = 9
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """ADX / +DI / -DI using Wilder's EWM (alpha = 1/period).

    Matches TC2000 output. Standard TA-lib uses a different default period (14)
    and sometimes different smoothing — this is the explicit period-9 Wilder's form
    George uses on his charts.
    """
    h, lo, c = df["high"], df["low"], df["close"]
    pc, ph, pl = c.shift(1), h.shift(1), lo.shift(1)

    tr = pd.concat([(h - lo), (h - pc).abs(), (lo - pc).abs()], axis=1).max(axis=1)

    up = h - ph
    dn = pl - lo
    plus_dm = pd.Series(
        np.where((up > dn) & (up > 0), up.values, 0.0), index=df.index, dtype=float
    )
    minus_dm = pd.Series(
        np.where((dn > up) & (dn > 0), dn.values, 0.0), index=df.index, dtype=float
    )

    a = 1.0 / period
    atr = tr.ewm(alpha=a, adjust=False).mean()
    plus_di = 100.0 * plus_dm.ewm(alpha=a, adjust=False).mean() / atr
    minus_di = 100.0 * minus_dm.ewm(alpha=a, adjust=False).mean() / atr

    denom = (plus_di + minus_di).replace(0.0, np.nan)
    dx = 100.0 * (plus_di - minus_di).abs() / denom
    adx = dx.ewm(alpha=a, adjust=False).mean()

    return adx, plus_di, minus_di


def _resample_weekly(df: pd.DataFrame) -> pd.DataFrame:
    """Resample daily OHLCV to weekly bars (week ending Friday)."""
    weekly = df.resample("W-FRI").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    })
    return weekly.dropna(subset=["close"])


def _fetch_ohlcv(algorithm: Any, symbol: Any, bars: int, resolution: Any) -> pd.DataFrame:
    """Pull OHLCV history from QC and return a flat, lowercase-column DataFrame."""
    try:
        df = algorithm.History([symbol], bars, resolution)
    except Exception:
        return pd.DataFrame()

    if df is None or df.empty:
        return pd.DataFrame()

    if isinstance(df.index, pd.MultiIndex):
        df = df.droplevel(0)

    df = df.copy()
    df.columns = [c.lower() for c in df.columns]
    required = {"open", "high", "low", "close", "volume"}
    if not required.issubset(df.columns):
        return pd.DataFrame()

    return df[["open", "high", "low", "close", "volume"]].astype(float)


def score_symbol(algorithm: Any, symbol: Any) -> dict[str, Any] | None:
    """Score a symbol against the BCT 8-condition Blue Flag checklist.

    Fetches weekly and daily OHLCV bars via algorithm.History(), then evaluates
    all 8 conditions. Returns None when data is insufficient.

    Args:
        algorithm: QCAlgorithm instance (provides the History API at runtime).
        symbol:    QuantConnect Symbol object.

    Returns:
        {
            "score":      int       — 0–8 conditions met,
            "rating":     str       — "+++" | "++" | "+" | "=" | "--",
            "conditions": list[bool] — one flag per condition (order matches CLAUDE.md),
        }
        or None if there are not enough bars to compute all indicators.
    """
    # Lazy import — QuantConnect is not available outside the LEAN runtime
    from QuantConnect import Resolution  # noqa: PLC0415

    # Fetch daily bars; weekly derived by resampling (QC has no Resolution.Weekly)
    daily = _fetch_ohlcv(algorithm, symbol, _DAILY_BARS, Resolution.DAILY)
    if len(daily) < 230:
        return None

    weekly = _resample_weekly(daily)
    # Need at least 78 weekly bars (span_b=52 + displacement=26)
    if len(weekly) < 78:
        return None

    # ── Weekly Ichimoku ────────────────────────────────────────────────────────
    w_tenkan = _mid(weekly["high"], weekly["low"], 9)
    w_kijun = _mid(weekly["high"], weekly["low"], 26)
    # Ichimoku's 26-bar forward displacement: current cloud = Span A/B from 26 bars ago.
    # series.shift(26) at iloc[-1] gives the value from iloc[-27], i.e. 26 bars ago.
    w_cloud_a = ((w_tenkan + w_kijun) / 2).shift(26)
    w_cloud_b = _mid(weekly["high"], weekly["low"], 52).shift(26)

    w_price = weekly["close"].iloc[-1]
    w_cloud_a_now = w_cloud_a.iloc[-1]
    w_cloud_b_now = w_cloud_b.iloc[-1]
    w_tenkan_now = w_tenkan.iloc[-1]
    w_kijun_now = w_kijun.iloc[-1]
    # Chikou = current close vs close 26 weekly bars ago
    w_price_26_ago = weekly["close"].iloc[-27]

    # ── Daily Ichimoku ─────────────────────────────────────────────────────────
    d_tenkan = _mid(daily["high"], daily["low"], 9)
    d_kijun = _mid(daily["high"], daily["low"], 26)
    d_cloud_a = ((d_tenkan + d_kijun) / 2).shift(26)

    d_price = daily["close"].iloc[-1]
    d_tenkan_now = d_tenkan.iloc[-1]
    d_cloud_a_now = d_cloud_a.iloc[-1]
    ma200 = daily["close"].rolling(200).mean().iloc[-1]

    # ── ADX / DMI — Wilder period-9, on daily bars ────────────────────────────
    adx, plus_di, minus_di = _adx_wilder(daily, period=9)
    adx_now = adx.iloc[-1]
    plus_di_now = plus_di.iloc[-1]
    minus_di_now = minus_di.iloc[-1]
    # "ADX rising" = current ADX above value 3 bars ago (PLAYBOOK simplified proxy)
    adx_rising = bool(adx.iloc[-1] > adx.iloc[-4])

    # Guard: any NaN means insufficient history for that indicator
    critical_values = [
        w_cloud_a_now, w_cloud_b_now, w_tenkan_now, w_kijun_now, w_price_26_ago,
        d_cloud_a_now, d_tenkan_now, ma200, adx_now, plus_di_now, minus_di_now,
    ]
    if any(pd.isna(v) for v in critical_values):
        return None

    # ── 8-condition Blue Flag checklist (CLAUDE.md order) ─────────────────────
    conditions: list[bool] = [
        bool(w_price > w_cloud_a_now),                                            # 1. weekly price above cloud
        bool(w_tenkan_now > w_kijun_now),                                         # 2. weekly tenkan > kijun
        bool(w_price > w_price_26_ago),                                           # 3. weekly chikou > price 26 bars ago
        bool(w_cloud_a_now > w_cloud_b_now),                                      # 4. weekly cloud green
        bool(d_price > d_cloud_a_now),                                            # 5. daily price above cloud
        bool(d_price > d_tenkan_now),                                             # 6. daily price above tenkan
        bool(adx_rising and plus_di_now > minus_di_now and adx_now >= 20),       # 7. ADX rising + +DI > -DI + ADX ≥ 20
        bool(d_price > ma200),                                                    # 8. price above 200-day MA
    ]

    score = sum(conditions)

    if score == 8:
        rating = "+++"
    elif score >= 6:
        rating = "++"
    elif score >= 4:
        rating = "+"
    elif score >= 2:
        rating = "="
    else:
        rating = "--"

    return {"score": score, "rating": rating, "conditions": conditions}
