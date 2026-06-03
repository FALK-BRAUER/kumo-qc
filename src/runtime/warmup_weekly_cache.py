"""#358 — RUNTIME-bundled weekly warmup-cache read side + the shared cache-KEY formula.

Lives in src/runtime/ (NOT sweeps/) because the cloud_package dist flattens src/ + its transitive
src imports ONLY — sweeps/ is offline runner mechanics, never bundled. lean_entry's flag-on lazy
import must resolve in the deployed dist, so the runtime READ (key formula + parse + ObjectStore
load) is here; the OFFLINE write (build script) imports the same key formula + dump from here too
(scripts add src/ to path) → ONE formula for write+read, no drift. The framework PR extracts the
generic cache_key/AsOfScalarCache from this weekly reference instance.

Delivery = QC-native ObjectStore (the live strategy reads no raw files in-container). FAIL-CLOSED,
two layers: (1) the validity-scoped LOCAL-ONLY key (type+data_fp+params) — a stale/wrong cache is a
DIFFERENT key → unaddressable; cloud never has the key → contains_key False → None; (2) the blob's
embedded fingerprint must also match. Either → caller re-derives live (canonical). A HIT is
byte-identical to the live re-derive (same WeeklyIchimokuAsOf, same daily data) → trade-neutral.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
from typing import Any

# the 6 weekly Ichimoku scalars the CONTINUOUS_WEEKLY decision re-derives (== table_builder subset).
WEEKLY_FIELDS = ("w_tenkan", "w_kijun", "w_senkou_a", "w_senkou_b", "w_close_0", "w_close_26")


# ── shared cache-KEY formula (framework standard; PR-2 generalizes to AsOfScalarCache) ──
def indicator_params_hash(params: tuple[object, ...]) -> str:
    """Short stable hash of an indicator's defining params (periods etc.) = its validity scope."""
    return hashlib.sha256(repr(tuple(params)).encode()).hexdigest()[:12]


def cache_key(cache_type: str, data_fingerprint: str, params_hash: str, symbol: str | None = None) -> str:
    """The ObjectStore key: ``<type>-<data_fp>-<params_hash>[-<SYMBOL>]``. Validity-in-key → a stale/
    wrong cache (different data OR params) is a DIFFERENT, UNADDRESSABLE key (fail-closed by
    construction). Type-namespaced → no cross-instance collision. FAIL-LOUD if a validity component is
    missing. Separator '-' not ':' (macOS APFS maps ':'→'/', breaking the loose-file write)."""
    if not cache_type or not data_fingerprint or not params_hash:
        raise ValueError("cache_key: cache_type, data_fingerprint, params_hash are all required")
    parts = [cache_type, str(data_fingerprint), str(params_hash)]
    if symbol:
        parts.append(str(symbol).upper())
    return "-".join(parts)


# LEAN Ichimoku default periods (tenkan 9 / kijun 26 / senkou-B 52 / displacement 26) — the weekly
# cache's validity params (WeeklyIchimokuAsOf wraps a default Ichimoku()).
WEEKLY_ICHIMOKU_PARAMS = (9, 26, 52, 26)
WEEKLY_CACHE_TYPE = "weekly_ichimoku"
WEEKLY_PARAMS_HASH = indicator_params_hash(WEEKLY_ICHIMOKU_PARAMS)


def weekly_cache_key(data_fingerprint: str, symbol: str | None = None) -> str:
    """The weekly-Ichimoku cache key for a data fingerprint (+ optional per-SYMBOL key). Used by BOTH
    the offline write and the runtime read → write_key == read_key by construction (single formula).
    Per-symbol keys (symbol set) let the runtime LAZY-load only the active names it queries — full
    universe coverage without a single giant blob (the 1.8GB-OOM avoidance)."""
    return cache_key(WEEKLY_CACHE_TYPE, data_fingerprint, WEEKLY_PARAMS_HASH, symbol)


# #358b warmup-skip: the FULL daily+weekly scalar set the daily-clock consumers need (signal legs,
# exit cloud_bottom). MUST equal sweeps.warmup_cache.table_builder.SCALAR_FIELDS — but the runtime is
# BUNDLED (can't import sweeps/ at runtime), so the list is duplicated here and a unit test asserts
# equality (the drift guard). The daily-suite validity params (Ichimoku 9/26/52/26 + SMA200 + ADX9 +
# ROC13) key the daily_scalar cache distinctly from the weekly_ichimoku cache.
ALL_SCALAR_FIELDS = (
    "d_price", "d_tenkan", "d_cloud_top", "ma200",
    "w_tenkan", "w_kijun", "w_senkou_a", "w_senkou_b", "w_close_0", "w_close_26",
    "adx_now", "plus_di", "minus_di", "adx_3back",
    "roc13", "d_cloud_bottom", "d_kijun",
)
DAILY_SCALAR_CACHE_TYPE = "daily_scalar"
DAILY_SCALAR_PARAMS = (9, 26, 52, 26, 200, 9, 13)  # ichimoku + sma200 + adx9 + roc13
DAILY_SCALAR_PARAMS_HASH = indicator_params_hash(DAILY_SCALAR_PARAMS)


def daily_scalar_cache_key(data_fingerprint: str, symbol: str | None = None) -> str:
    """The full-scalar (daily+weekly) cache key — distinct cache_type from weekly_ichimoku (no
    collision). Used by BOTH the offline write and the runtime read → write_key == read_key."""
    return cache_key(DAILY_SCALAR_CACHE_TYPE, data_fingerprint, DAILY_SCALAR_PARAMS_HASH, symbol)


# ── serialize (offline write) / parse (runtime read) — exact inverses (round-trip-identical) ──
def dump_weekly_blob(
    syms: dict[str, dict[_dt.date, dict[str, float]]], fingerprint: str,
    fields: tuple[str, ...] = WEEKLY_FIELDS,
) -> str:
    """Serialize a ``{SYM: {date: {scalars}}}`` map → the ObjectStore JSON blob (fields default to the
    6 weekly; pass ALL_SCALAR_FIELDS for the full daily+weekly blob)."""
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
    """Parse the ObjectStore blob → ``{SYM: {date: {scalars}}}``. FAIL-CLOSED → ``None`` on falsy
    text/fp, bad JSON, fingerprint mismatch, or a row missing any of `fields`. Pure."""
    if not text or not expected_fingerprint:
        return None
    try:
        blob = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(blob, dict) or str(blob.get("fingerprint")) != str(expected_fingerprint):
        return None  # FAIL-CLOSED: fingerprint mismatch — the cloud-divergence guard
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
                return None  # malformed row — don't half-load
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
    """Fetch the cache blob from the LEAN ObjectStore + parse. FAIL-CLOSED → ``None`` when
    object_store/key/fingerprint is falsy, the key is ABSENT (cloud: never uploaded → contains_key
    False → live re-derive), or read/parse fails. Never raises — a read error falls back to the live
    canonical path (surfaced by the caller's init LOADED/NOT-loaded log)."""
    if object_store is None or not key or not expected_fingerprint:
        return None
    try:
        if not object_store.contains_key(key):
            return None  # key absent → cloud / not-populated → fail-closed
        text = object_store.read(key)
    except Exception:  # noqa: BLE001 — fail-closed-to-live is intended; init logs LOADED/NOT-loaded
        return None
    return parse_weekly_cache(text, expected_fingerprint, fields)


def load_weekly_cache_for_symbol(
    object_store: Any,
    data_fingerprint: str | None,
    symbol: str,
) -> dict[_dt.date, dict[str, float]] | None:
    """LAZY per-SYMBOL load (weekly): fetch+parse ONLY this symbol's per-symbol weekly key. Returns
    ``{date: {6 weekly scalars}}`` or ``None`` (FAIL-CLOSED → live re-derive). Memoized by the runtime."""
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
    """LAZY per-SYMBOL load (FULL daily+weekly scalars): fetch+parse this symbol's daily_scalar key.
    Returns ``{date: {16 scalars incl d_cloud_bottom}}`` or ``None`` (FAIL-CLOSED → live re-derive).
    The warmup-skip feeds the daily-clock consumers (signal legs, exit cloud_bottom) from this."""
    if object_store is None or not data_fingerprint or not symbol:
        return None
    key = daily_scalar_cache_key(data_fingerprint, symbol)
    parsed = load_weekly_cache_from_store(object_store, key, data_fingerprint, ALL_SCALAR_FIELDS)
    return parsed.get(str(symbol).upper()) if parsed else None
