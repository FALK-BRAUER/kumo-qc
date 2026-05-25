"""BCT signal scorer — indicator-only (no History() calls)."""
from __future__ import annotations

from typing import Any


def _indicator_value(indicator: Any) -> float | None:
    if indicator is None:
        return None
    current = getattr(indicator, "current", None)
    if current is None:
        return None
    value = getattr(current, "value", None)
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def score_symbol(algorithm: Any, symbol: Any, ind: dict[str, Any]) -> dict[str, Any] | None:
    """Indicator-based BCT scorer. Uses only pre-registered indicators."""
    if ind is None:
        return None

    d_ichi = ind.get("d_ichi")
    w_ichi = ind.get("w_ichi")
    w_close = ind.get("w_close")
    sma200 = ind.get("sma200")
    adx = ind.get("adx")
    plus_di = ind.get("plus_di")
    minus_di = ind.get("minus_di")

    if d_ichi is None or w_ichi is None or w_close is None or sma200 is None:
        return None
    if adx is None or plus_di is None or minus_di is None:
        return None
    if not (d_ichi.is_ready and w_ichi.is_ready and sma200.is_ready and adx.is_ready):
        return None
    if w_close.count < 27:
        return None

    d_price = float(algorithm.securities[symbol].price)
    w_price = float(w_close[0])
    w_price_26_ago = float(w_close[26])

    w_tenkan_now = _indicator_value(w_ichi.tenkan)
    w_kijun_now = _indicator_value(w_ichi.kijun)
    w_cloud_a_now = _indicator_value(getattr(w_ichi, "senkou_a", None))
    w_cloud_b_now = _indicator_value(getattr(w_ichi, "senkou_b", None))

    d_tenkan_now = _indicator_value(d_ichi.tenkan)
    d_cloud_a_now = _indicator_value(getattr(d_ichi, "senkou_a", None))
    d_cloud_b_now = _indicator_value(getattr(d_ichi, "senkou_b", None))

    ma200 = _indicator_value(sma200)
    adx_now = _indicator_value(adx)
    plus_di_now = _indicator_value(plus_di)
    minus_di_now = _indicator_value(minus_di)

    critical = [
        w_cloud_a_now,
        w_cloud_b_now,
        w_tenkan_now,
        w_kijun_now,
        w_price_26_ago,
        d_cloud_a_now,
        d_cloud_b_now,
        d_tenkan_now,
        ma200,
        adx_now,
        plus_di_now,
        minus_di_now,
    ]
    if any(v is None for v in critical):
        return None

    conditions: list[bool] = [
        bool(w_price > max(w_cloud_a_now, w_cloud_b_now)),
        bool(w_tenkan_now > w_kijun_now),
        bool(w_price > w_price_26_ago),
        bool(w_cloud_a_now > w_cloud_b_now),
        bool(d_price > max(d_cloud_a_now, d_cloud_b_now)),
        bool(d_price > d_tenkan_now),
        bool(plus_di_now > minus_di_now and adx_now >= 20),
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
    """Native wrapper for indicator-only scoring path."""
    return score_symbol(algorithm, symbol, ind)
