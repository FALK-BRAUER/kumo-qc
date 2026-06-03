"""#358 — the SHARED cache-key formula (framework standard, ALL instances: weekly/daily/monthly/vix).

Falk's correctness requirement: the key ENCODES a cache's VALIDITY, so a stale/wrong cache is
literally UNADDRESSABLE (fail-closed BY CONSTRUCTION, stronger than the in-blob fingerprint check —
which is kept as belt-and-suspenders). The key =

    <cache_type>-<data_fingerprint>-<indicator_params_hash>[-<SYMBOL>]

- TYPE-NAMESPACED: weekly/daily/monthly/vix each a distinct prefix → no cross-instance ObjectStore
  collision.
- VALIDITY-IN-KEY: change the data (fingerprint) OR the indicator params (params_hash) → DIFFERENT key
  → the old cache can't be read → recompute. Wrong/stale data can never silently load.
- ONE formula used by BOTH the offline WRITE and the runtime READ (cache_key here) — never two that
  could drift. The runtime DERIVES the key from the injected data-fingerprint via the same helper, so
  write_key(inputs) == read_key(inputs) by construction.

Separator "-" not Falk's literal ":" — macOS APFS reinterprets ":" in a filename as "/" (would break
the on-disk LocalObjectStore loose-file write); "-" is filesystem- and LEAN-key-safe. Same semantics.
"""
from __future__ import annotations

import hashlib


def indicator_params_hash(params: tuple[object, ...]) -> str:
    """Short stable hash of an indicator's defining params (periods etc.) = its validity scope."""
    return hashlib.sha256(repr(tuple(params)).encode()).hexdigest()[:12]


def cache_key(cache_type: str, data_fingerprint: str, params_hash: str, symbol: str | None = None) -> str:
    """The ObjectStore key. FAIL-LOUD if any validity component is missing (a key without full
    validity scope could collide / load stale)."""
    if not cache_type or not data_fingerprint or not params_hash:
        raise ValueError("cache_key: cache_type, data_fingerprint, params_hash are all required")
    parts = [cache_type, str(data_fingerprint), str(params_hash)]
    if symbol:
        parts.append(str(symbol).upper())
    return "-".join(parts)


# ── the WEEKLY Ichimoku instance (instance 1; sets the framework standard) ──
# LEAN Ichimoku default periods: tenkan 9 / kijun 26 / senkou-B 52 / displacement 26 — the params that
# define the weekly cache's validity (WeeklyIchimokuAsOf wraps a default Ichimoku()).
WEEKLY_ICHIMOKU_PARAMS = (9, 26, 52, 26)
WEEKLY_CACHE_TYPE = "weekly_ichimoku"
WEEKLY_PARAMS_HASH = indicator_params_hash(WEEKLY_ICHIMOKU_PARAMS)


def weekly_cache_key(data_fingerprint: str) -> str:
    """The weekly-Ichimoku cache key for a data fingerprint. Used by BOTH the offline write and the
    runtime read → write_key == read_key by construction (single formula)."""
    return cache_key(WEEKLY_CACHE_TYPE, data_fingerprint, WEEKLY_PARAMS_HASH)
