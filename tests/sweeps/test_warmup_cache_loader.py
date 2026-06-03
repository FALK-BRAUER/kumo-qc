"""#358 — ObjectStore-native loader tests: round-trip parity, FAIL-CLOSED parse guard, as-of keying,
and the store-fetch (contains_key gating). The loader is the cloud-safety surface (the 8b50c1a guard):
it parses ONLY on a fingerprint match and a fetch falls back to None (→ live re-derivation) when the
key is absent (cloud) / fingerprint mismatches / read fails."""
from __future__ import annotations

import datetime as _dt

from runtime.warmup_weekly_cache import (
    WEEKLY_FIELDS, dump_weekly_blob, load_weekly_cache_from_store, parse_weekly_cache,
)

_WK = {"w_tenkan": 1.5, "w_kijun": 2.5, "w_senkou_a": 3.5,
       "w_senkou_b": 4.5, "w_close_0": 5.5, "w_close_26": 6.5}
_D = _dt.date(2025, 1, 2)


class _Store:
    """Minimal LEAN-ObjectStore stand-in: {key: text} with contains_key/read."""
    def __init__(self, data: dict[str, str], raise_on_read: bool = False) -> None:
        self._d = data
        self._raise = raise_on_read

    def contains_key(self, k: str) -> bool:
        return k in self._d

    def read(self, k: str) -> str:
        if self._raise:
            raise RuntimeError("simulated read failure")
        return self._d[k]


# ── 1. PARITY round-trip: dump → parse is identity (the cached scalars are byte-identical) ──
def test_round_trip_identity():
    syms = {"AAPL": {_D: _WK}, "MSFT": {_dt.date(2025, 3, 3): {**_WK, "w_tenkan": 9.9}}}
    parsed = parse_weekly_cache(dump_weekly_blob(syms, "fp1"), "fp1")
    assert parsed == syms                               # exact round-trip, no drift
    assert set(parsed["AAPL"][_D]) == set(WEEKLY_FIELDS)


def test_symbol_keyed_uppercase():
    parsed = parse_weekly_cache(dump_weekly_blob({"msft": {_D: _WK}}, "fp1"), "fp1")
    assert "MSFT" in parsed and "msft" not in parsed    # caller keys by symbol.value (upper)


# ── 2. FAIL-CLOSED parse guard ──
def test_fail_closed_no_text_or_fp():
    assert parse_weekly_cache(None, "fp1") is None
    assert parse_weekly_cache("", "fp1") is None
    assert parse_weekly_cache(dump_weekly_blob({"AAPL": {_D: _WK}}, "fp1"), None) is None


def test_fail_closed_bad_json():
    assert parse_weekly_cache("{not json", "fp1") is None


def test_fail_closed_fingerprint_mismatch():
    assert parse_weekly_cache(dump_weekly_blob({"AAPL": {_D: _WK}}, "fp1"), "fp2") is None  # cloud data → mismatch


def test_fail_closed_missing_weekly_fields():
    import json
    blob = json.dumps({"fingerprint": "fp1", "syms": {"AAPL": {"2025-01-02": {"w_tenkan": 1.0}}}})
    assert parse_weekly_cache(blob, "fp1") is None      # malformed row → don't half-load


def test_fail_closed_non_dict_syms():
    import json
    assert parse_weekly_cache(json.dumps({"fingerprint": "fp1", "syms": []}), "fp1") is None


# ── 3. AS-OF keying: a date not in the cache → caller gets None (no future peek) ──
def test_asof_keying():
    parsed = parse_weekly_cache(dump_weekly_blob({"AAPL": {_D: _WK}}, "fp1"), "fp1")
    assert parsed["AAPL"][_D]["w_tenkan"] == 1.5
    assert parsed["AAPL"].get(_dt.date(2025, 6, 30)) is None


# ── 4. store-fetch: contains_key gating + read fail-closed ──
def test_store_fetch_hit():
    blob = dump_weekly_blob({"AAPL": {_D: _WK}}, "fp1")
    store = _Store({"k": blob})
    assert load_weekly_cache_from_store(store, "k", "fp1") == {"AAPL": {_D: _WK}}


def test_store_fetch_key_absent_fail_closed():
    store = _Store({})                                  # cloud: key never uploaded
    assert load_weekly_cache_from_store(store, "k", "fp1") is None


def test_store_fetch_fingerprint_mismatch():
    store = _Store({"k": dump_weekly_blob({"AAPL": {_D: _WK}}, "fp1")})
    assert load_weekly_cache_from_store(store, "k", "WRONG") is None


def test_store_fetch_read_error_fail_closed():
    store = _Store({"k": "x"}, raise_on_read=True)
    assert load_weekly_cache_from_store(store, "k", "fp1") is None  # read raises → live re-derive


def test_store_fetch_none_store_or_key():
    assert load_weekly_cache_from_store(None, "k", "fp1") is None
    assert load_weekly_cache_from_store(_Store({"k": "x"}), None, "fp1") is None
