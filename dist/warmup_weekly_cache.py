from __future__ import annotations

import datetime as _dt
import hashlib
import json
from typing import Any

WEEKLY_FIELDS = ("w_tenkan", "w_kijun", "w_senkou_a", "w_senkou_b", "w_close_0", "w_close_26")


def indicator_params_hash(params: tuple[object, ...]) -> str:
    return hashlib.sha256(repr(tuple(params)).encode()).hexdigest()[:12]


def cache_key(cache_type: str, data_fingerprint: str, params_hash: str, symbol: str | None = None) -> str:
    if not cache_type or not data_fingerprint or not params_hash:
        raise ValueError("cache_key: cache_type, data_fingerprint, params_hash are all required")
    parts = [cache_type, str(data_fingerprint), str(params_hash)]
    if symbol:
        parts.append(str(symbol).upper())
    return "-".join(parts)


WEEKLY_ICHIMOKU_PARAMS = (9, 26, 52, 26)
WEEKLY_CACHE_TYPE = "weekly_ichimoku"
WEEKLY_PARAMS_HASH = indicator_params_hash(WEEKLY_ICHIMOKU_PARAMS)


def weekly_cache_key(data_fingerprint: str, symbol: str | None = None) -> str:
    return cache_key(WEEKLY_CACHE_TYPE, data_fingerprint, WEEKLY_PARAMS_HASH, symbol)


ALL_SCALAR_FIELDS = (
    "d_price", "d_tenkan", "d_cloud_top", "ma200",
    "w_tenkan", "w_kijun", "w_senkou_a", "w_senkou_b", "w_close_0", "w_close_26",
    "adx_now", "plus_di", "minus_di", "adx_3back",
    "roc13", "d_cloud_bottom", "d_kijun",
)
DAILY_SCALAR_CACHE_TYPE = "daily_scalar"
DAILY_SCALAR_PARAMS = (9, 26, 52, 26, 200, 9, 13)
DAILY_SCALAR_PARAMS_HASH = indicator_params_hash(DAILY_SCALAR_PARAMS)


def daily_scalar_cache_key(data_fingerprint: str, symbol: str | None = None) -> str:
    return cache_key(DAILY_SCALAR_CACHE_TYPE, data_fingerprint, DAILY_SCALAR_PARAMS_HASH, symbol)


def dump_weekly_blob(
    syms: dict[str, dict[_dt.date, dict[str, float]]], fingerprint: str,
    fields: tuple[str, ...] = WEEKLY_FIELDS,
) -> str:
    return json.dumps({
        "fingerprint": str(fingerprint),
        "syms": {
            sym: {d.isoformat(): {k: float(wk[k]) for k in fields} for d, wk in rows.items()}
            for sym, rows in syms.items()
        },
    }, separators=(",", ":"))


def parse_weekly_cache(
    text: str | None,
    expected_fingerprint: str | None,
    fields: tuple[str, ...] = WEEKLY_FIELDS,
) -> dict[str, dict[_dt.date, dict[str, float]]] | None:
    if not text or not expected_fingerprint:
        return None
    try:
        blob = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(blob, dict) or str(blob.get("fingerprint")) != str(expected_fingerprint):
        return None
    syms = blob.get("syms")
    if not isinstance(syms, dict):
        return None
    out: dict[str, dict[_dt.date, dict[str, float]]] = {}
    for sym, rows in syms.items():
        if not isinstance(rows, dict):
            return None
        m: dict[_dt.date, dict[str, float]] = {}
        for date_iso, wk in rows.items():
            if not isinstance(wk, dict) or not set(fields).issubset(wk):
                return None
            try:
                m[_dt.date.fromisoformat(date_iso)] = {k: float(wk[k]) for k in fields}
            except (ValueError, TypeError):
                return None
        if m:
            out[str(sym).upper()] = m
    return out or None


def load_weekly_cache_from_store(
    object_store: Any,
    key: str | None,
    expected_fingerprint: str | None,
    fields: tuple[str, ...] = WEEKLY_FIELDS,
) -> dict[str, dict[_dt.date, dict[str, float]]] | None:
    if object_store is None or not key or not expected_fingerprint:
        return None
    try:
        if not object_store.contains_key(key):
            return None
        text = object_store.read(key)
    except Exception:
        return None
    return parse_weekly_cache(text, expected_fingerprint, fields)


def load_weekly_cache_for_symbol(
    object_store: Any,
    data_fingerprint: str | None,
    symbol: str,
) -> dict[_dt.date, dict[str, float]] | None:
    if object_store is None or not data_fingerprint or not symbol:
        return None
    key = weekly_cache_key(data_fingerprint, symbol)
    parsed = load_weekly_cache_from_store(object_store, key, data_fingerprint, WEEKLY_FIELDS)
    return parsed.get(str(symbol).upper()) if parsed else None


def load_scalars_for_symbol(
    object_store: Any,
    data_fingerprint: str | None,
    symbol: str,
) -> dict[_dt.date, dict[str, float]] | None:
    if object_store is None or not data_fingerprint or not symbol:
        return None
    key = daily_scalar_cache_key(data_fingerprint, symbol)
    parsed = load_weekly_cache_from_store(object_store, key, data_fingerprint, ALL_SCALAR_FIELDS)
    return parsed.get(str(symbol).upper()) if parsed else None
