"""CloudAdherenceTrail (#339 candidate B) — exit only on cloud-bottom breach; HOLD recoverable
Kijun-dips that stay above the cloud (the BCT-3 thesis). Constructor: (Params(...), logger=None)."""
from datetime import datetime

import pytest

from engine.base import DegradedDataError
from engine.context import PhaseContext
from phases.exit.cloud_adherence_trail.cloud_adherence_trail import CloudAdherenceTrail


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


def make_symbol(name="AAPL"):
    return type("Symbol", (), {"value": name})()


def make_ctx(qc):
    return PhaseContext(qc=qc, time=datetime(2025, 6, 15), data=None)


def _setup(close, kijun=100.0, senkou_a=105.0, senkou_b=95.0, ready=True, w_ichi=None, qty=100):
    sym = make_symbol()
    qc = FakeQC()
    qc.portfolio[sym] = FakeHolding(invested=True, quantity=qty)
    qc.securities[sym] = FakeSecurity(close=close)
    qc._indicators[sym] = {"d_ichi": FakeIndicator(kijun, senkou_a, senkou_b, ready), "w_ichi": w_ichi}
    return sym, qc


def test_holds_recoverable_dip_below_kijun_above_cloud():
    # close=97: below Kijun (100) but ABOVE cloud_bottom (95) — KijunG3 would EXIT, CloudAdherence HOLDS.
    _sym, qc = _setup(close=97.0)  # cloud_bottom = min(105,95) = 95
    ctx = make_ctx(qc)
    result = CloudAdherenceTrail(CloudAdherenceTrail.Params(), logger=None).evaluate(ctx)
    assert result.blocked is False
    assert len(ctx.bar_state.exit_intents) == 0  # the BCT-3 hold — recoverable dip not realized


def test_exits_on_cloud_bottom_breach():
    _sym, qc = _setup(close=90.0)  # below cloud_bottom = 95
    ctx = make_ctx(qc)
    result = CloudAdherenceTrail(CloudAdherenceTrail.Params(), logger=None).evaluate(ctx)
    assert len(ctx.bar_state.exit_intents) == 1
    intent = ctx.bar_state.exit_intents[0]
    assert intent.qty == -100 and intent.stop == 95.0  # stop trails the cloud bottom


def test_no_exit_above_cloud():
    _sym, qc = _setup(close=110.0)  # above everything
    ctx = make_ctx(qc)
    result = CloudAdherenceTrail(CloudAdherenceTrail.Params(), logger=None).evaluate(ctx)
    assert len(ctx.bar_state.exit_intents) == 0


def test_weekly_kijun_composes_when_enabled():
    # above cloud_bottom (95) so no cloud exit, but below weekly Kijun (99) with the flag on → exit.
    _sym, qc = _setup(close=97.0, w_ichi=FakeIndicator(kijun=99.0))
    ctx = make_ctx(qc)
    p = CloudAdherenceTrail.Params(weekly_kijun_exit_enabled=True)
    result = CloudAdherenceTrail(p, logger=None).evaluate(ctx)
    assert len(ctx.bar_state.exit_intents) == 1
    assert ctx.bar_state.exit_intents[0].stop == 99.0


def test_weekly_kijun_off_by_default_holds():
    _sym, qc = _setup(close=97.0, w_ichi=FakeIndicator(kijun=99.0))
    ctx = make_ctx(qc)
    result = CloudAdherenceTrail(CloudAdherenceTrail.Params(), logger=None).evaluate(ctx)
    assert len(ctx.bar_state.exit_intents) == 0  # weekly off → holds the above-cloud dip


def test_fail_loud_on_cold_d_ichi():
    _sym, qc = _setup(close=90.0, ready=False)
    ctx = make_ctx(qc)
    with pytest.raises(DegradedDataError):
        CloudAdherenceTrail(CloudAdherenceTrail.Params(), logger=None).evaluate(ctx)


def test_absent_indicator_is_benign_skip():
    sym = make_symbol()
    qc = FakeQC()
    qc.portfolio[sym] = FakeHolding(invested=True, quantity=100)
    qc.securities[sym] = FakeSecurity(close=90.0)
    # no _indicators entry at all → benign skip, no raise
    ctx = make_ctx(qc)
    result = CloudAdherenceTrail(CloudAdherenceTrail.Params(), logger=None).evaluate(ctx)
    assert result.blocked is False
    assert len(ctx.bar_state.exit_intents) == 0
