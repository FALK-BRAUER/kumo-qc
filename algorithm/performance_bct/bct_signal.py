"""BCT signal scorer — George's Blue Cloud Trading 8-condition Blue Flag checklist.

No top-level QuantConnect imports — safe to import outside the LEAN runtime.
QC Resolution enum is imported lazily inside score_symbol() / score_symbol_native().
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


_WEEKLY_BARS = 130
_DAILY_BARS = 700


def _mid(high: pd.Series, low: pd.Series, period: int) -> pd.Series:
    return (high.rolling(period).max() + low.rolling(period).min()) / 2


def _adx_wilder(
    df: pd.DataFrame, period: int = 9
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """ADX / +DI / -DI using Wilder's EWM (alpha = 1/period). Matches TC2000 / George's charts."""
    h, lo, c = df["high"], df["low"], df["close"]
    pc, ph, pl = c.shift(1), h.shift(1), lo.shift(1)
    tr = pd.concat([(h - lo), (h - pc).abs(), (lo - pc).abs()], axis=1).max(axis=1)
    up = h - ph
    dn = pl - lo
    plus_dm = pd.Series(np.where((up > dn) & (up > 0), up.values, 0.0), index=df.index, dtype=float)
    minus_dm = pd.Series(np.where((dn > up) & (dn > 0), dn.values, 0.0), index=df.index, dtype=float)
    a = 1.0 / period
    atr = tr.ewm(alpha=a, adjust=False).mean()
    plus_di = 100.0 * plus_dm.ewm(alpha=a, adjust=False).mean() / atr
    minus_di = 100.0 * minus_dm.ewm(alpha=a, adjust=False).mean() / atr
    denom = (plus_di + minus_di).replace(0.0, np.nan)
    dx = 100.0 * (plus_di - minus_di).abs() / denom
    adx = dx.ewm(alpha=a, adjust=False).mean()
    return adx, plus_di, minus_di


def _resample_weekly(df: pd.DataFrame) -> pd.DataFrame:
    weekly = df.resample("W-FRI").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
    return weekly.dropna(subset=["close"])


def _fetch_ohlcv(algorithm: Any, symbol: Any, bars: int, resolution: Any) -> pd.DataFrame:
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
    """History-based BCT scorer. Fetches 700 daily bars, resamples to weekly."""
    from QuantConnect import Resolution  # noqa: PLC0415

    daily = _fetch_ohlcv(algorithm, symbol, _DAILY_BARS, Resolution.DAILY)
    if len(daily) < 230:
        return None
    weekly = _resample_weekly(daily)
    if len(weekly) < 78:
        return None

    w_tenkan = _mid(weekly["high"], weekly["low"], 9)
    w_kijun  = _mid(weekly["high"], weekly["low"], 26)
    w_cloud_a = ((w_tenkan + w_kijun) / 2).shift(26)
    w_cloud_b = _mid(weekly["high"], weekly["low"], 52).shift(26)

    w_price        = weekly["close"].iloc[-1]
    w_cloud_a_now  = w_cloud_a.iloc[-1]
    w_cloud_b_now  = w_cloud_b.iloc[-1]
    w_tenkan_now   = w_tenkan.iloc[-1]
    w_kijun_now    = w_kijun.iloc[-1]
    w_price_26_ago = weekly["close"].iloc[-27]

    d_tenkan  = _mid(daily["high"], daily["low"], 9)
    d_kijun   = _mid(daily["high"], daily["low"], 26)
    d_cloud_a = ((d_tenkan + d_kijun) / 2).shift(26)
    d_cloud_b = _mid(daily["high"], daily["low"], 52).shift(26)

    d_price       = daily["close"].iloc[-1]
    d_tenkan_now  = d_tenkan.iloc[-1]
    d_cloud_a_now = d_cloud_a.iloc[-1]
    d_cloud_b_now = d_cloud_b.iloc[-1]
    ma200         = daily["close"].rolling(200).mean().iloc[-1]

    adx, plus_di, minus_di = _adx_wilder(daily, period=9)
    adx_now      = adx.iloc[-1]
    plus_di_now  = plus_di.iloc[-1]
    minus_di_now = minus_di.iloc[-1]
    adx_rising   = bool(adx.iloc[-1] > adx.iloc[-4])

    critical = [w_cloud_a_now, w_cloud_b_now, w_tenkan_now, w_kijun_now, w_price_26_ago,
                d_cloud_a_now, d_cloud_b_now, d_tenkan_now, ma200, adx_now, plus_di_now, minus_di_now]
    if any(pd.isna(v) for v in critical):
        return None

    conditions: list[bool] = [
        bool(w_price > max(w_cloud_a_now, w_cloud_b_now)),
        bool(w_tenkan_now > w_kijun_now),
        bool(w_price > w_price_26_ago),
        bool(w_cloud_a_now > w_cloud_b_now),
        bool(d_price > max(d_cloud_a_now, d_cloud_b_now)),
        bool(d_price > d_tenkan_now),
        bool(adx_rising and plus_di_now > minus_di_now and adx_now >= 20),
        bool(d_price > ma200),
    ]
    score = sum(conditions)
    if score == 8:   rating = "+++"
    elif score >= 6: rating = "++"
    elif score >= 4: rating = "+"
    elif score >= 2: rating = "="
    else:            rating = "--"
    return {"score": score, "rating": rating, "conditions": conditions}


def score_symbol_native(algorithm: Any, symbol: Any, ind: Any) -> dict[str, Any] | None:
    """Native-indicator BCT scorer for performance_bct.

    Uses pre-registered QC IchimokuKinkoHyo + SMA200 from the ind dict.
    ADX still fetches 100 daily bars — QC native ADX uses period 14, George uses period 9.
    """
    from QuantConnect import Resolution  # noqa: PLC0415

    d_ichi  = ind["d_ichi"]
    w_ichi  = ind["w_ichi"]
    w_close = ind["w_close"]
    sma200  = ind["sma200"]

    if not (d_ichi.is_ready and w_ichi.is_ready and sma200.is_ready):
        return None
    if not w_close.is_ready or w_close.count < 27:
        return None

    w_price        = float(w_close[0])
    w_tenkan_now   = float(w_ichi.tenkan.current.value)
    w_kijun_now    = float(w_ichi.kijun.current.value)
    w_cloud_a_now  = float(w_ichi.senkou_span_a.current.value)
    w_cloud_b_now  = float(w_ichi.senkou_span_b.current.value)
    w_price_26_ago = float(w_close[26])

    d_price       = float(algorithm.securities[symbol].price)
    d_tenkan_now  = float(d_ichi.tenkan.current.value)
    d_cloud_a_now = float(d_ichi.senkou_span_a.current.value)
    d_cloud_b_now = float(d_ichi.senkou_span_b.current.value)
    ma200         = float(sma200.current.value)

    # Custom Wilder period-9 ADX (QC native uses period 14)
    daily = _fetch_ohlcv(algorithm, symbol, 100, Resolution.DAILY)
    if len(daily) < 30:
        return None
    adx, plus_di, minus_di = _adx_wilder(daily, period=9)
    adx_now      = adx.iloc[-1]
    plus_di_now  = plus_di.iloc[-1]
    minus_di_now = minus_di.iloc[-1]
    adx_rising   = bool(adx.iloc[-1] > adx.iloc[-4])

    critical = [w_cloud_a_now, w_cloud_b_now, w_tenkan_now, w_kijun_now, w_price_26_ago,
                d_cloud_a_now, d_cloud_b_now, d_tenkan_now, ma200, adx_now, plus_di_now, minus_di_now]
    if any(pd.isna(v) for v in critical):
        return None

    conditions: list[bool] = [
        bool(w_price > max(w_cloud_a_now, w_cloud_b_now)),
        bool(w_tenkan_now > w_kijun_now),
        bool(w_price > w_price_26_ago),
        bool(w_cloud_a_now > w_cloud_b_now),
        bool(d_price > max(d_cloud_a_now, d_cloud_b_now)),
        bool(d_price > d_tenkan_now),
        bool(adx_rising and plus_di_now > minus_di_now and adx_now >= 20),
        bool(d_price > ma200),
    ]
    score = sum(conditions)
    if score == 8:   rating = "+++"
    elif score >= 6: rating = "++"
    elif score >= 4: rating = "+"
    elif score >= 2: rating = "="
    else:            rating = "--"
    return {"score": score, "rating": rating, "conditions": conditions}
