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
    WEEKLY_FLOOR_DAYS = 560  # #368: mirrors BCTAlgorithm; the miss-fallback re-derives at this floor

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


# ── #370 volume-aware traded_on_asof: real bar (vol>0) cache-miss → throw; fill-forward (vol==0) → value ──
def _hist_df(n_weekdays: int, asof: _dt.date, last_volume: float):
    """A daily history DataFrame of n weekday bars ending AT asof; the asof bar gets `last_volume`
    (0.0 = a LEAN fill-forward synthetic bar, >0 = a real trade). ~430 weekdays → weekly is_ready."""
    import pandas as pd
    dates: list[_dt.date] = []
    d = asof
    while len(dates) < n_weekdays:
        if d.weekday() < 5:
            dates.append(d)
        d -= _dt.timedelta(days=1)
    dates.sort()
    rows = []
    for i, dd in enumerate(dates):
        c = 100.0 + i * 0.1
        vol = last_volume if dd == asof else 1_000_000.0
        rows.append((c, c + 1.0, c - 1.0, c, vol))
    return pd.DataFrame(rows, index=pd.to_datetime(dates),
                        columns=["open", "high", "low", "close", "volume"])


class _TrimStub:
    """Trimmed-warmup (320<560), cache-ARMED but EMPTY → every lookup misses → live re-derive over
    the injected history. Exercises the #370 traded_on_asof COMPUTATION + the throw/value decision."""
    WARMUP_DAYS = 320
    WEEKLY_FLOOR_DAYS = 560

    def __init__(self, hist_df) -> None:
        self._weekly_cache_fp = "fp1"
        self._weekly_loaded: dict = {}
        self.object_store = _Store({})          # empty → cache miss → re-derive
        self._weekly_cache_hits = 0
        self._weekly_cache_misses = 0
        self._hist = hist_df

    def history(self, *a, **k):
        return self._hist


def test_real_bar_on_asof_cache_miss_throws() -> None:
    """NVD-class: the symbol REALLY traded on asof (vol>0) → build SHOULD have cached it → a trimmed
    cache miss is a REAL gap → THROW (the guard, preserved)."""
    from runtime.warmup_weekly_cache import WeeklyCacheGapError
    asof = _dt.date(2025, 2, 18)
    s = _TrimStub(_hist_df(440, asof, last_volume=1_000_000.0))
    with pytest.raises(WeeklyCacheGapError):
        BctEngineAlgorithm._weekly_scalars_for(s, _Sym("NVD"), asof)


def test_fillforward_bar_on_asof_returns_value_not_throw() -> None:
    """HCP-class: LEAN fill-forwards a synthetic asof bar (vol==0) for a delisted name → NOT a real
    trade → build couldn't cache it → carry-forward 'value', NOT a throw (== full-warmup)."""
    asof = _dt.date(2025, 2, 27)
    s = _TrimStub(_hist_df(440, asof, last_volume=0.0))
    out = BctEngineAlgorithm._weekly_scalars_for(s, _Sym("HCP"), asof)
    assert out is not None and "w_tenkan" in out      # carry-forward weekly value, no WeeklyCacheGapError


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
