"""#358 — cache-KEY scheme tests (Falk: correctness-critical, the framework standard).

The key encodes validity (type+data_fp+params_hash[+sym]) so a stale/wrong cache is UNADDRESSABLE
(fail-closed by construction). One formula for write+read (no drift). Covers Falk's a–d."""
from __future__ import annotations

import pytest

from sweeps.warmup_cache.keys import (
    WEEKLY_PARAMS_HASH, cache_key, indicator_params_hash, weekly_cache_key,
)


# ── (a) write-key == read-key: the SAME formula on both sides → no silent miss ──
def test_write_key_equals_read_key():
    fp = "abc123"
    assert weekly_cache_key(fp) == weekly_cache_key(fp)                  # deterministic
    # weekly_cache_key IS cache_key(weekly_ichimoku, fp, WEEKLY_PARAMS_HASH) — write & read both call it
    assert weekly_cache_key(fp) == cache_key("weekly_ichimoku", fp, WEEKLY_PARAMS_HASH)


# ── (b) different data_fingerprint → different key (stale data can't load) ──
def test_different_data_fingerprint_different_key():
    assert weekly_cache_key("fp_A") != weekly_cache_key("fp_B")


# ── (c) different params_hash → different key (param change can't load stale) ──
def test_different_params_hash_different_key():
    fp = "fp1"
    assert cache_key("weekly_ichimoku", fp, "params_A") != cache_key("weekly_ichimoku", fp, "params_B")
    # the params_hash itself changes with the periods → validity scope
    assert indicator_params_hash((9, 26, 52, 26)) != indicator_params_hash((7, 22, 44, 22))


# ── (d) different cache_type → different key (no cross-instance collision) ──
def test_different_cache_type_different_key():
    fp, ph = "fp1", "ph1"
    assert cache_key("weekly_ichimoku", fp, ph) != cache_key("daily_scalar", fp, ph)
    assert cache_key("weekly_ichimoku", fp, ph) != cache_key("vix_percentile", fp, ph)


# ── validity components are mandatory (fail-loud) ──
def test_cache_key_requires_all_validity_components():
    for bad in [("", "fp", "ph"), ("t", "", "ph"), ("t", "fp", "")]:
        with pytest.raises(ValueError):
            cache_key(*bad)


def test_symbol_suffix_optional_and_uppercased():
    base = cache_key("daily_scalar", "fp1", "ph1")
    keyed = cache_key("daily_scalar", "fp1", "ph1", symbol="aapl")
    assert keyed == base + "-AAPL" and keyed != base


def test_separator_is_filesystem_safe():
    # "-" not ":" — macOS APFS reinterprets ":" as "/" (breaks the loose-file write).
    assert ":" not in weekly_cache_key("fp1") and "/" not in weekly_cache_key("fp1")
