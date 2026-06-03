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


def score_from_daily_frame(daily: pd.DataFrame) -> dict[str, Any] | None:
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


def score_symbol(algorithm: Any, symbol: Any) -> dict[str, Any] | None:
    try:
        from QuantConnect import Resolution
    except ImportError:
        return None

    daily = _fetch_ohlcv(algorithm, symbol, _DAILY_BARS, Resolution.DAILY)
    return score_from_daily_frame(daily)


def score_symbol_native(algorithm: Any, symbol: Any, ind: dict[str, Any]) -> dict[str, Any] | None:
    d_ichi = ind["d_ichi"]; w_ichi = ind["w_ichi"]; w_close = ind["w_close"]
    sma200 = ind["sma200"]; adx = ind["adx"]; adx_window = ind["adx_window"]; roc13 = ind["roc13"]

    if not (d_ichi.is_ready and w_ichi.is_ready and sma200.is_ready and adx.is_ready and roc13.is_ready):
        return None
    if w_close.count < 27 or adx_window.count < 4:
        return None

    d_price = float(algorithm.securities[symbol].price)
    if d_price <= 0:
        return None

    d_tenkan = d_ichi.tenkan.current.value
    d_cloud_top = max(d_ichi.senkou_a.current.value, d_ichi.senkou_b.current.value)
    ma200 = sma200.current.value
    w_tenkan = w_ichi.tenkan.current.value
    w_kijun = w_ichi.kijun.current.value
    w_sa = w_ichi.senkou_a.current.value
    w_sb = w_ichi.senkou_b.current.value
    w_cloud_top = max(w_sa, w_sb)
    adx_now = adx.current.value
    plus_di = adx.positive_directional_index.current.value
    minus_di = adx.negative_directional_index.current.value
    adx_rising = adx_window[0] > adx_window[3]

    conditions: list[bool] = [
        bool(d_price > w_cloud_top),
        bool(w_tenkan > w_kijun),
        bool(w_close[0] > w_close[26]),
        bool(w_sa > w_sb),
        bool(d_price > d_cloud_top),
        bool(d_price > d_tenkan),
        bool(adx_rising and plus_di > minus_di and adx_now >= 20),
        bool(d_price > ma200),
    ]
    score = sum(conditions)
    if score == 8:   rating = "+++"
    elif score >= 6: rating = "++"
    elif score >= 4: rating = "+"
    elif score >= 2: rating = "="
    else:            rating = "--"
    return {"score": score, "rating": rating, "conditions": conditions}


def score_symbol_cached(scalars: dict[str, float]) -> dict[str, Any]:
    d_price = scalars["d_price"]
    w_cloud_top = max(scalars["w_senkou_a"], scalars["w_senkou_b"])
    adx_rising = scalars["adx_now"] > scalars["adx_3back"]
    conditions: list[bool] = [
        bool(d_price > w_cloud_top),
        bool(scalars["w_tenkan"] > scalars["w_kijun"]),
        bool(scalars["w_close_0"] > scalars["w_close_26"]),
        bool(scalars["w_senkou_a"] > scalars["w_senkou_b"]),
        bool(d_price > scalars["d_cloud_top"]),
        bool(d_price > scalars["d_tenkan"]),
        bool(adx_rising and scalars["plus_di"] > scalars["minus_di"]
             and scalars["adx_now"] >= 20),
        bool(d_price > scalars["ma200"]),
    ]
    score = sum(conditions)
    if score == 8:   rating = "+++"
    elif score >= 6: rating = "++"
    elif score >= 4: rating = "+"
    elif score >= 2: rating = "="
    else:            rating = "--"
    return {"score": score, "rating": rating, "conditions": conditions}
