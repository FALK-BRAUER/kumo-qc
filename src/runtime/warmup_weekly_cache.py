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


class WeeklyCacheGapError(Exception):
    """#368 fail-loud: a weekly-cache MISS on an IN-WINDOW name (the weekly IS computable from full
    history) while the warmup is TRIMMED → the cache has a coverage gap that would SILENTLY drop a
    valid candidate (the live re-derive at the trimmed window can't compute it). Halt loud — never
    ship a silent-divergence. (A miss on a pre-78wk-from-listing / post-delisting name is LEGIT and
    does NOT raise — that name is genuinely uncomputable, correctly skipped.)"""


def weekly_miss_action(*, rederive_ready: bool, armed: bool, warmup_days: int,
                       weekly_floor: int, traded_on_asof: bool = True) -> str:
    """#368/#370 — decide what an armed weekly-cache MISS does, AFTER re-deriving from the FULL
    weekly_floor window (NOT the possibly-trimmed warmup). Pure → unit-testable.
      - NOT ready  → 'skip'  : uncomputable (pre-78wk-from-listing OR fully post-delisting) → legit, None.
      - ready but the symbol did NOT TRADE on asof (last available bar < asof — delisted/halted that day,
        a delisting-LAG query) → 'value' : NOT a build gap. The cache legitimately has no asof key (no
        bar); the re-derive is the CARRY-FORWARD weekly (no new bar since the last → weekly unchanged),
        which is EXACTLY what the untrimmed full-warmup path returns → byte-identical, never throw. (#370
        HCP@2025-02-27: HashiCorp delisted 02-26, scored 02-27 on universe lag.)
      - ready + TRADED on asof + trimmed (armed AND warmup_days < weekly_floor) → 'throw' : the name IS
        computable AND it traded on asof so the build SHOULD have cached it, but didn't → a real coverage
        gap that at trimmed warmup would silently drop a valid candidate → fail loud.
      - ready + NOT trimmed → 'value' : full warmup (or unarmed) → the re-derive is canonical → value."""
    if not rederive_ready:
        return "skip"
    if armed and warmup_days < weekly_floor and traded_on_asof:
        return "throw"
    return "value"


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


# ── serialize (offline write) / parse (runtime read) — exact inverses (round-trip-identical) ──
def dump_weekly_blob(syms: dict[str, dict[_dt.date, dict[str, float]]], fingerprint: str) -> str:
    """Serialize a ``{SYM: {date: {6 weekly scalars}}}`` map → the ObjectStore JSON blob."""
    return json.dumps({
        "fingerprint": str(fingerprint),
        "syms": {
            sym: {d.isoformat(): {k: float(wk[k]) for k in WEEKLY_FIELDS} for d, wk in rows.items()}
            for sym, rows in syms.items()
        },
    }, separators=(",", ":"))


def parse_weekly_cache(
    text: str | None,
    expected_fingerprint: str | None,
) -> dict[str, dict[_dt.date, dict[str, float]]] | None:
    """Parse the ObjectStore blob → ``{SYM: {date: {6 weekly scalars}}}``. FAIL-CLOSED → ``None`` on
    falsy text/fp, bad JSON, fingerprint mismatch, or malformed/missing weekly fields. Pure."""
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
            if not isinstance(wk, dict) or not set(WEEKLY_FIELDS).issubset(wk):
                return None  # malformed row — don't half-load
            try:
                m[_dt.date.fromisoformat(date_iso)] = {k: float(wk[k]) for k in WEEKLY_FIELDS}
            except (ValueError, TypeError):
                return None
        if m:
            out[str(sym).upper()] = m
    return out or None


def load_weekly_cache_from_store(
    object_store: Any,
    key: str | None,
    expected_fingerprint: str | None,
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
    return parse_weekly_cache(text, expected_fingerprint)


def load_weekly_cache_for_symbol(
    object_store: Any,
    data_fingerprint: str | None,
    symbol: str,
) -> dict[_dt.date, dict[str, float]] | None:
    """LAZY per-SYMBOL load: fetch+parse ONLY this symbol's per-symbol key (weekly_cache_key(fp, sym)).
    Returns ``{date: {6 weekly scalars}}`` for the symbol, or ``None`` (FAIL-CLOSED → live re-derive)
    when fp/symbol falsy, the per-sym key is absent (cloud / sym not cached), or read/parse fails. The
    runtime memoizes the result per symbol so each is fetched at most once."""
    if object_store is None or not data_fingerprint or not symbol:
        return None
    key = weekly_cache_key(data_fingerprint, symbol)
    parsed = load_weekly_cache_from_store(object_store, key, data_fingerprint)
    return parsed.get(str(symbol).upper()) if parsed else None
