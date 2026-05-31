"""v2-delta: constructor is SpySma200(SpySma200.Params(...), logger=None)."""
from datetime import datetime
from engine.context import PhaseContext, BarState
from phases.regime.spy_200ma.spy_200ma import SpySma200


class FakeSma:
    def __init__(self, value, ready=True):
        self.is_ready = ready
        self.current = type("C", (), {"value": value})()


class FakeSecurity:
    def __init__(self, price):
        self.price = price


class FakeQC:
    def __init__(self, spy_price, ma200):
        self.spy = "SPY_SYM"
        self.spy_sma200 = FakeSma(ma200)
        self.securities = {"SPY_SYM": FakeSecurity(spy_price)}


def make_ctx(qc):
    return PhaseContext(qc=qc, time=datetime(2025, 1, 2), data=None)


def test_spy_below_ma200_blocks():
    qc = FakeQC(spy_price=400.0, ma200=450.0)
    phase = SpySma200(SpySma200.Params(), logger=None)
    result = phase.evaluate(make_ctx(qc))
    assert result.blocked is True
    assert "SPY" in result.reason


def test_spy_above_ma200_passes():
    qc = FakeQC(spy_price=500.0, ma200=450.0)
    phase = SpySma200(SpySma200.Params(), logger=None)
    result = phase.evaluate(make_ctx(qc))
    assert result.blocked is False


def test_spy_at_ma200_passes():
    qc = FakeQC(spy_price=450.0, ma200=450.0)
    phase = SpySma200(SpySma200.Params(), logger=None)
    result = phase.evaluate(make_ctx(qc))
    assert result.blocked is False  # strictly less than, matches oracle


def test_sma200_not_ready_blocks():
    # #261-7: a not-ready regime SMA now BLOCKS (fail-closed), not the old fail-open pass.
    qc = FakeQC(spy_price=400.0, ma200=450.0)
    qc.spy_sma200 = FakeSma(450.0, ready=False)
    phase = SpySma200(SpySma200.Params(), logger=None)
    result = phase.evaluate(make_ctx(qc))
    assert result.blocked is True  # not ready → BLOCK until warm (#261-7)


def test_spy_none_blocks():
    # #261-7: a missing spy / spy_sma200 also blocks — never wave entries through on partial state.
    class NoSpyQC:
        spy = None
        spy_sma200 = None
        securities: dict[object, object] = {}
    phase = SpySma200(SpySma200.Params(), logger=None)
    result = phase.evaluate(PhaseContext(qc=NoSpyQC(), time=datetime(2025, 1, 2), data=None))
    assert result.blocked is True
