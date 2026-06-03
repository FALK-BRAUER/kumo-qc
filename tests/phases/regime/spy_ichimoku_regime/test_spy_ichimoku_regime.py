"""#342 SpyIchimokuRegime — gate entries on SPY daily Ichimoku bullishness (T>K + price>=cloud).

Blocks the Jan-3-14 regime (SPY T<K); passes the bullish regime; fail-CLOSED when enabled and
unable to assess (no SPY / short history / compute error). disabled → skip.
"""
import sys
import types
from datetime import datetime

import pandas as pd

# Shim QuantConnect.Resolution — unit tests run outside the LEAN container (the phase imports it
# lazily inside evaluate()). At runtime LEAN provides the real module; the code path is identical.
_qc_mod = types.ModuleType("QuantConnect")
_qc_mod.Resolution = types.SimpleNamespace(DAILY="Daily")
sys.modules.setdefault("QuantConnect", _qc_mod)

from engine.context import PhaseContext  # noqa: E402
from phases.regime.spy_ichimoku_regime.spy_ichimoku_regime import SpyIchimokuRegime  # noqa: E402


class _Sym:
    def __init__(self, v):
        self.value = v

    def __hash__(self):
        return hash(self.value)

    def __eq__(self, o):
        return isinstance(o, _Sym) and o.value == self.value


class _Sec:
    def __init__(self, price):
        self.price = price


class _Secs(dict):
    def contains_key(self, k):
        return k in self


class _QC:
    def __init__(self, spy, price, hist):
        self.spy = spy
        self.securities = _Secs({spy: _Sec(price)}) if spy is not None else _Secs()
        self._hist = hist

    def history(self, sym, lookback, res):
        return self._hist


def _df(prices):
    """high=low=close=price (simplest deterministic Ichimoku); single-level index."""
    return pd.DataFrame({"high": prices, "low": prices, "close": prices})


def _run(qc, **params):
    ctx = PhaseContext(qc=qc, time=datetime(2025, 1, 10), data=None)
    return SpyIchimokuRegime(SpyIchimokuRegime.Params(enabled=True, **params), logger=None).evaluate(ctx)


_RISING = [100.0 + i for i in range(120)]   # newest highest → T>K, price above cloud → bullish
_FALLING = [220.0 - i for i in range(120)]  # newest lowest  → T<K, price below cloud → bearish


def test_disabled_skips():
    spy = _Sym("SPY")
    res = SpyIchimokuRegime(SpyIchimokuRegime.Params(enabled=False), logger=None).evaluate(
        PhaseContext(qc=_QC(spy, 219.0, _df(_RISING)), time=datetime(2025, 1, 10), data=None))
    assert res.decision == "skip" and res.blocked is False


def test_bullish_regime_passes():
    spy = _Sym("SPY")
    res = _run(_QC(spy, _RISING[-1], _df(_RISING)))
    assert res.blocked is False and res.decision == "pass"
    assert res.facts["tenkan"] > res.facts["kijun"]
    assert res.facts["spy"] >= res.facts["cloud_bottom"]


def test_bearish_tk_blocks():
    # the Jan 3-14 signal: SPY Tenkan < Kijun → BLOCK entries.
    spy = _Sym("SPY")
    res = _run(_QC(spy, _FALLING[-1], _df(_FALLING)))
    assert res.blocked is True and res.decision == "block"
    assert res.facts["tenkan"] <= res.facts["kijun"]


def test_below_cloud_blocks_independent_of_tk():
    # isolate the cloud condition: T>K not required, price below cloud → BLOCK.
    spy = _Sym("SPY")
    res = _run(_QC(spy, _FALLING[-1], _df(_FALLING)), require_tenkan_over_kijun=False)
    assert res.blocked is True and res.facts["cloud_ok"] is False


def test_above_cloud_passes_with_tk_off():
    spy = _Sym("SPY")
    res = _run(_QC(spy, _RISING[-1], _df(_RISING)), require_tenkan_over_kijun=False)
    assert res.blocked is False and res.facts["cloud_ok"] is True


def test_fail_closed_no_spy():
    res = _run(_QC(None, 0.0, _df(_RISING)))
    assert res.blocked is True and res.decision == "block"


def test_fail_closed_insufficient_history():
    spy = _Sym("SPY")
    res = _run(_QC(spy, 100.0, _df([100.0 + i for i in range(40)])))  # < 79 bars
    assert res.blocked is True and res.decision == "block"


def test_fail_closed_compute_error():
    # history() returns None → enabled gate can't assess → fail-closed block.
    spy = _Sym("SPY")
    res = _run(_QC(spy, 100.0, None))
    assert res.blocked is True and res.decision == "block"
