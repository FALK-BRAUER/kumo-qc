"""CloudBreachExit (#339 candidate C) — exit on cloud-TOP breach (price enters cloud). Tighter than
B (cloud-bottom). Constructor: (Params(...), logger=None)."""
from datetime import datetime

import pytest

from engine.base import DegradedDataError
from engine.context import PhaseContext
from phases.exit.cloud_breach_exit.cloud_breach_exit import CloudBreachExit


class FakeIndicator:
    def __init__(self, kijun=100.0, senkou_a=105.0, senkou_b=95.0, ready=True):
        self.is_ready = ready
        self.kijun = type("V", (), {"current": type("C", (), {"value": kijun})()})()
        self.senkou_a = type("V", (), {"current": type("C", (), {"value": senkou_a})()})()
        self.senkou_b = type("V", (), {"current": type("C", (), {"value": senkou_b})()})()


class FakeHolding:
    def __init__(self, invested=True, quantity=100):
        self.invested = invested
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


def _setup(close, w_ichi=None):
    s = _sym()
    qc = FakeQC()
    qc.portfolio[s] = FakeHolding(invested=True, quantity=100)
    qc.securities[s] = FakeSecurity(close=close)
    qc._indicators[s] = {"d_ichi": FakeIndicator(100.0, 105.0, 95.0), "w_ichi": w_ichi}  # cloud 95..105
    return qc


def test_exits_when_price_enters_cloud():
    # close=100: below cloud_top (105) — C exits (price no longer clearly above cloud).
    qc = _setup(close=100.0)
    ctx = _ctx(qc)
    CloudBreachExit(CloudBreachExit.Params(), logger=None).evaluate(ctx)
    assert len(ctx.bar_state.exit_intents) == 1
    assert ctx.bar_state.exit_intents[0].stop == 105.0  # trails the cloud top


def test_holds_when_clearly_above_cloud():
    qc = _setup(close=110.0)  # above cloud_top
    ctx = _ctx(qc)
    CloudBreachExit(CloudBreachExit.Params(), logger=None).evaluate(ctx)
    assert len(ctx.bar_state.exit_intents) == 0


def test_tighter_than_cloud_adherence():
    # close=100 is INSIDE the cloud (95..105): C exits (cloud-top breach), where B (cloud-bottom) holds.
    qc = _setup(close=100.0)
    ctx = _ctx(qc)
    CloudBreachExit(CloudBreachExit.Params(), logger=None).evaluate(ctx)
    assert len(ctx.bar_state.exit_intents) == 1  # C is tighter — exits inside the cloud


def test_weekly_kijun_composes():
    qc = _setup(close=110.0, w_ichi=FakeIndicator(kijun=112.0))  # above cloud_top(105), below weekly kijun(112)
    ctx = _ctx(qc)
    CloudBreachExit(CloudBreachExit.Params(weekly_kijun_exit_enabled=True), logger=None).evaluate(ctx)
    assert len(ctx.bar_state.exit_intents) == 1
    assert ctx.bar_state.exit_intents[0].stop == 112.0


def test_fail_loud_on_cold_d_ichi():
    s = _sym()
    qc = FakeQC()
    qc.portfolio[s] = FakeHolding(invested=True, quantity=100)
    qc.securities[s] = FakeSecurity(close=100.0)
    qc._indicators[s] = {"d_ichi": FakeIndicator(ready=False), "w_ichi": None}
    with pytest.raises(DegradedDataError):
        CloudBreachExit(CloudBreachExit.Params(), logger=None).evaluate(_ctx(qc))
