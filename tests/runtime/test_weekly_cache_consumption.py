"""#358 — runtime consumption-hook tests: _weekly_scalars_for cache-HIT short-circuit, cache-MISS
and cache-None fall-back to the live re-derivation (fail-closed). The method is exercised on a light
stub (the QC base is `object` outside LEAN), so the cache-HIT path is fully testable without a runtime;
the MISS/None paths assert the live history() re-derivation is reached (the canonical fallback)."""
from __future__ import annotations

import datetime as _dt
import types

import pytest

from runtime import lean_entry
from runtime.lean_entry import BctEngineAlgorithm


@pytest.fixture(autouse=True)
def _resolution(monkeypatch):
    # Outside LEAN, lean_entry.Resolution is None; the live re-derive path references Resolution.DAILY.
    # Stub it so the cache-MISS/None fall-back paths reach self.history (the behavior under test).
    if getattr(lean_entry, "Resolution", None) is None:
        monkeypatch.setattr(lean_entry, "Resolution", types.SimpleNamespace(DAILY="daily"), raising=False)

_WK = {"w_tenkan": 1.0, "w_kijun": 2.0, "w_senkou_a": 3.0,
       "w_senkou_b": 4.0, "w_close_0": 5.0, "w_close_26": 6.0}
_D = _dt.date(2025, 1, 2)


class _Sym:
    def __init__(self, v: str) -> None:
        self.value = v


class _Stub:
    """Minimal stand-in: carries _weekly_cache + counts history() calls (the live re-derivation)."""
    WARMUP_DAYS = 560

    def __init__(self, cache):
        self._weekly_cache = cache
        self.history_calls = 0

    def history(self, *a, **k):
        self.history_calls += 1
        return None  # empty → the re-derivation returns None after a cache miss/none


def test_cache_hit_short_circuits_no_history():
    s = _Stub({"AAPL": {_D: _WK}})
    out = BctEngineAlgorithm._weekly_scalars_for(s, _Sym("AAPL"), _D)
    assert out == _WK and s.history_calls == 0          # HIT → cached weekly, NO history() re-derive


def test_cache_miss_symbol_falls_to_live_rederive():
    s = _Stub({"AAPL": {_D: _WK}})
    out = BctEngineAlgorithm._weekly_scalars_for(s, _Sym("MSFT"), _D)  # symbol not cached
    assert s.history_calls == 1 and out is None         # MISS → live re-derive (canonical fallback)


def test_cache_miss_date_falls_to_live_rederive():
    s = _Stub({"AAPL": {_D: _WK}})
    out = BctEngineAlgorithm._weekly_scalars_for(s, _Sym("AAPL"), _dt.date(2025, 6, 30))  # date not cached
    assert s.history_calls == 1 and out is None         # no future/absent-date peek → re-derive


def test_cache_none_fail_closed_to_live_rederive():
    s = _Stub(None)                                     # cloud / fingerprint-mismatch → loader returned None
    out = BctEngineAlgorithm._weekly_scalars_for(s, _Sym("AAPL"), _D)
    assert s.history_calls == 1                         # FAIL-CLOSED: no cache → live re-derive, no divergence
