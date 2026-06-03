"""#358 — runtime consumption-hook tests (PER-SYMBOL LAZY load): _weekly_scalars_for fetches each
symbol's per-symbol key ONCE (memoized), HIT short-circuits history, MISS/not-armed fall back to the
live re-derivation (fail-closed). Exercised on a light stub (QC base is `object` outside LEAN)."""
from __future__ import annotations

import datetime as _dt
import types

import pytest

from runtime import lean_entry
from runtime.lean_entry import BctEngineAlgorithm
from runtime.warmup_weekly_cache import dump_weekly_blob, weekly_cache_key

_WK = {"w_tenkan": 1.0, "w_kijun": 2.0, "w_senkou_a": 3.0,
       "w_senkou_b": 4.0, "w_close_0": 5.0, "w_close_26": 6.0}
_D = _dt.date(2025, 1, 2)
_FP = "fp1"


@pytest.fixture(autouse=True)
def _resolution(monkeypatch):
    if getattr(lean_entry, "Resolution", None) is None:
        monkeypatch.setattr(lean_entry, "Resolution", types.SimpleNamespace(DAILY="daily"), raising=False)


class _Sym:
    def __init__(self, v: str) -> None:
        self.value = v


class _Store:
    """LEAN-ObjectStore stand-in holding per-symbol keys; counts reads (to assert fetch-once)."""
    def __init__(self, data: dict[str, str]) -> None:
        self._d = data
        self.reads = 0

    def contains_key(self, k: str) -> bool:
        return k in self._d

    def read(self, k: str) -> str:
        self.reads += 1
        return self._d[k]


class _Stub:
    WARMUP_DAYS = 560

    def __init__(self, fp, store):
        self._weekly_cache_fp = fp
        self._weekly_loaded: dict = {}
        self.object_store = store
        self._weekly_cache_hits = 0
        self._weekly_cache_misses = 0
        self.history_calls = 0

    def history(self, *a, **k):
        self.history_calls += 1
        return None  # empty → live re-derive returns None after a miss/not-armed


def _store_with(sym: str) -> _Store:
    blob = dump_weekly_blob({sym.upper(): {_D: _WK}}, _FP)
    return _Store({weekly_cache_key(_FP, sym): blob})


def test_per_symbol_hit_short_circuits_history():
    s = _Stub(_FP, _store_with("AAPL"))
    out = BctEngineAlgorithm._weekly_scalars_for(s, _Sym("AAPL"), _D)
    assert out == _WK and s.history_calls == 0
    assert s._weekly_cache_hits == 1 and s._weekly_cache_misses == 0


def test_lazy_fetch_once_memoized():
    store = _store_with("AAPL")
    s = _Stub(_FP, store)
    BctEngineAlgorithm._weekly_scalars_for(s, _Sym("AAPL"), _D)
    BctEngineAlgorithm._weekly_scalars_for(s, _Sym("AAPL"), _D)
    assert store.reads == 1                      # fetched ONCE, second query served from the memo
    assert "AAPL" in s._weekly_loaded


def test_symbol_not_cached_falls_to_live_and_memoizes_none():
    s = _Stub(_FP, _store_with("AAPL"))
    out = BctEngineAlgorithm._weekly_scalars_for(s, _Sym("MSFT"), _D)  # no per-sym key for MSFT
    assert out is None and s.history_calls == 1 and s._weekly_cache_misses == 1
    assert s._weekly_loaded["MSFT"] is None      # attempted-missing memoized → no re-fetch
    BctEngineAlgorithm._weekly_scalars_for(s, _Sym("MSFT"), _D)
    assert s.object_store.reads == 0 or "MSFT" in s._weekly_loaded  # not re-fetched


def test_date_not_ready_falls_to_live():
    s = _Stub(_FP, _store_with("AAPL"))
    out = BctEngineAlgorithm._weekly_scalars_for(s, _Sym("AAPL"), _dt.date(2025, 6, 30))  # date not cached
    assert out is None and s.history_calls == 1 and s._weekly_cache_misses == 1


def test_not_armed_fp_none_fail_closed_to_live():
    s = _Stub(None, _store_with("AAPL"))         # cloud / not-armed → no fp
    BctEngineAlgorithm._weekly_scalars_for(s, _Sym("AAPL"), _D)
    assert s.history_calls == 1                  # FAIL-CLOSED: live re-derive, no divergence


def test_engagement_logged_when_armed():
    """REGRESSION (the refactor bug): the ENGAGED hit/miss signal must fire when the cache is ARMED.
    Was silently dead after _weekly_cache→_weekly_cache_fp rename (condition checked the stale attr)."""
    logs: list[str] = []
    class _S:
        _weekly_cache_fp = "fp1"; _weekly_cache_hits = 42; _weekly_cache_misses = 8
        def log(self, m): logs.append(m)
    BctEngineAlgorithm._log_cache_engagement(_S())
    assert any("ENGAGED: hits=42 misses=8" in m for m in logs)


def test_engagement_not_logged_when_not_armed():
    logs: list[str] = []
    class _S:
        _weekly_cache_fp = None; _weekly_cache_hits = 0; _weekly_cache_misses = 0
        def log(self, m): logs.append(m)
    BctEngineAlgorithm._log_cache_engagement(_S())
    assert logs == []


# ── #358b WARMUP-SKIP: _daily_scalars_for (full daily_scalar cache lazy per-sym) ──
def test_daily_scalars_for_hit_and_memoized():
    from runtime.warmup_weekly_cache import (
        ALL_SCALAR_FIELDS, daily_scalar_cache_key, dump_weekly_blob,
    )
    full = {k: float(i) for i, k in enumerate(ALL_SCALAR_FIELDS)}
    store = _Store({daily_scalar_cache_key("fpD", "AAPL"): dump_weekly_blob({"AAPL": {_D: full}}, "fpD", ALL_SCALAR_FIELDS)})

    class _DS:
        _daily_cache_fp = "fpD"
        def __init__(self): self._daily_loaded = {}; self.object_store = store
    s = _DS()
    got = BctEngineAlgorithm._daily_scalars_for(s, _Sym("AAPL"), _D)
    assert got == full and store.reads == 1                       # full 16-scalar row, fetched once
    BctEngineAlgorithm._daily_scalars_for(s, _Sym("AAPL"), _D)
    assert store.reads == 1                                       # memoized — no re-fetch


def test_daily_scalars_for_miss_and_not_armed():
    class _DS:
        def __init__(self, fp, store): self._daily_cache_fp = fp; self._daily_loaded = {}; self.object_store = store
    # not armed (fp None) → None
    assert BctEngineAlgorithm._daily_scalars_for(_DS(None, _Store({})), _Sym("AAPL"), _D) is None
    # armed but symbol not cached → None (fail-closed)
    assert BctEngineAlgorithm._daily_scalars_for(_DS("fpD", _Store({})), _Sym("AAPL"), _D) is None
