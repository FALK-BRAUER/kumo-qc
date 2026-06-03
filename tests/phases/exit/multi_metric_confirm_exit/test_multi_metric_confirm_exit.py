"""MultiMetricConfirmExit (#339 candidate D) — exit only when >=confirm_n bearish signals agree
(close<kijun, ADX falling, -DI>+DI). Holds single-signal noise. Constructor: (Params(...), logger=None)."""
from datetime import datetime

import pytest

from engine.base import DegradedDataError
from engine.context import PhaseContext
from phases.exit.multi_metric_confirm_exit.multi_metric_confirm_exit import MultiMetricConfirmExit


class FakeIchi:
    def __init__(self, kijun=100.0, ready=True):
        self.is_ready = ready
        self.kijun = type("V", (), {"current": type("C", (), {"value": kijun})()})()


class FakeADX:
    def __init__(self, plus_di=20.0, minus_di=10.0, ready=True):
        self.is_ready = ready
        self.positive_directional_index = type("V", (), {"current": type("C", (), {"value": plus_di})()})()
        self.negative_directional_index = type("V", (), {"current": type("C", (), {"value": minus_di})()})()


class FakeWindow:
    """Newest-first rolling window: [0]=newest. values listed newest→oldest."""
    def __init__(self, values):
        self._v = list(values)
    @property
    def count(self):
        return len(self._v)
    def __getitem__(self, i):
        return self._v[i]


class FakeHolding:
    def __init__(self, quantity=100):
        self.invested = True
        self.quantity = quantity


class FakeSecurity:
    def __init__(self, close=90.0):
        self.close = close


class FakeTransactions:
    def get_open_orders(self, symbol=None):
        return []


class FakeQC:
    def __init__(self):
        self.portfolio = {}
        self.securities = {}
        self._indicators = {}
        self.transactions = FakeTransactions()


def _sym(name="AAPL"):
    return type("Symbol", (), {"value": name})()


def _ctx(qc):
    return PhaseContext(qc=qc, time=datetime(2025, 6, 15), data=None)


def _setup(close, kijun=100.0, plus_di=20.0, minus_di=10.0, adx_vals=(13, 12, 11, 10),
           d_ready=True, adx_ready=True):
    s = _sym()
    qc = FakeQC()
    qc.portfolio[s] = FakeHolding(quantity=100)
    qc.securities[s] = FakeSecurity(close=close)
    qc._indicators[s] = {
        "d_ichi": FakeIchi(kijun, d_ready),
        "adx": FakeADX(plus_di, minus_di, adx_ready),
        "adx_window": FakeWindow(adx_vals),
    }
    return qc


def _run(qc, confirm_n=2):
    ctx = _ctx(qc)
    MultiMetricConfirmExit(MultiMetricConfirmExit.Params(confirm_n=confirm_n), logger=None).evaluate(ctx)
    return ctx.bar_state.exit_intents


def test_two_signals_confirm_exit():
    # close<kijun (sig1) + -DI>+DI (sig2); adx rising (not falling). 2 sigs >= confirm_n=2 → EXIT.
    intents = _run(_setup(close=90.0, kijun=100.0, plus_di=10.0, minus_di=20.0, adx_vals=(13, 12, 11, 10)))
    assert len(intents) == 1 and intents[0].stop == 100.0


def test_one_signal_holds():
    # ONLY close<kijun (sig1); +DI>-DI (no di-bear); adx rising (not falling). 1 sig < 2 → HOLD.
    intents = _run(_setup(close=90.0, kijun=100.0, plus_di=20.0, minus_di=10.0, adx_vals=(13, 12, 11, 10)))
    assert len(intents) == 0  # single-signal noise held (the anti-whipsaw)


def test_all_three_confirm_exit():
    # close<kijun + adx FALLING (10<13) + -DI>+DI → 3 sigs → exit.
    intents = _run(_setup(close=90.0, kijun=100.0, plus_di=10.0, minus_di=20.0, adx_vals=(10, 11, 12, 13)))
    assert len(intents) == 1


def test_adx_falling_plus_kijun_confirms():
    # close<kijun (sig1) + adx falling (sig2: 10<13); +DI>-DI (no di-bear). 2 sigs → exit.
    intents = _run(_setup(close=90.0, kijun=100.0, plus_di=20.0, minus_di=10.0, adx_vals=(10, 11, 12, 13)))
    assert len(intents) == 1


def test_short_adx_window_treats_falling_as_false():
    # only 3 adx samples → adx_falling can't compute → False. close<kijun only = 1 sig < 2 → HOLD.
    intents = _run(_setup(close=90.0, kijun=100.0, plus_di=20.0, minus_di=10.0, adx_vals=(10, 11, 12)))
    assert len(intents) == 0


def test_fail_loud_cold_d_ichi():
    with pytest.raises(DegradedDataError):
        _run(_setup(close=90.0, d_ready=False))


def test_fail_loud_cold_adx():
    with pytest.raises(DegradedDataError):
        _run(_setup(close=90.0, adx_ready=False))
