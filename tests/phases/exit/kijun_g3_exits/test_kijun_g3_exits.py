"""v2-delta: constructor is KijunG3Exits(KijunG3Exits.Params(...), logger=None)."""
from datetime import datetime, timedelta
import pytest
from engine.context import PhaseContext, BarState
from engine.base import PhaseResult
from phases.exit.kijun_g3_exits.kijun_g3_exits import KijunG3Exits


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
        self._position_meta = {}
        self.transactions = FakeTransactions()


def make_symbol(name="AAPL"):
    s = type("Symbol", (), {"value": name})()
    return s


def make_ctx(qc):
    return PhaseContext(qc=qc, time=datetime(2025, 6, 15), data=None)


def test_kijun_exit_fires_when_close_below_kijun():
    sym = make_symbol("AAPL")
    qc = FakeQC()
    qc.portfolio[sym] = FakeHolding(invested=True, quantity=100)
    qc.securities[sym] = FakeSecurity(close=90.0)  # below kijun=100
    qc.securities[sym].close = 90.0
    qc._indicators[sym] = {
        "d_ichi": FakeIndicator(kijun=100.0, senkou_a=105.0, senkou_b=95.0),
        "w_ichi": None,
    }

    phase = KijunG3Exits(KijunG3Exits.Params(), logger=None)
    ctx = make_ctx(qc)
    result = phase.evaluate(ctx)

    assert result.blocked is False
    assert len(ctx.bar_state.exit_intents) == 1
    assert ctx.bar_state.exit_intents[0].ticker == "AAPL"
    assert ctx.bar_state.exit_intents[0].qty == -100


def test_no_exit_when_close_above_kijun():
    sym = make_symbol("MSFT")
    qc = FakeQC()
    qc.portfolio[sym] = FakeHolding(invested=True, quantity=50)
    qc.securities[sym] = FakeSecurity(close=110.0)  # above kijun=100
    qc._indicators[sym] = {
        "d_ichi": FakeIndicator(kijun=100.0, senkou_a=105.0, senkou_b=95.0),
        "w_ichi": None,
    }

    phase = KijunG3Exits(KijunG3Exits.Params(), logger=None)
    ctx = make_ctx(qc)
    result = phase.evaluate(ctx)

    assert result.blocked is False
    assert len(ctx.bar_state.exit_intents) == 0


def test_g3_exit_fires_when_below_cloud_bottom_after_56d_15pct():
    sym = make_symbol("GOOG")
    entry_date = datetime(2025, 6, 15) - timedelta(days=60)  # 60d > 56d threshold
    qc = FakeQC()
    qc.portfolio[sym] = FakeHolding(invested=True, quantity=200)
    qc.securities[sym] = FakeSecurity(close=80.0)  # below cloud_bottom=90
    qc._indicators[sym] = {
        "d_ichi": FakeIndicator(kijun=100.0, senkou_a=95.0, senkou_b=90.0),  # cloud_bottom=90
        "w_ichi": None,
    }
    qc._position_meta[sym] = {"entry_date": entry_date, "entry_price": 60.0}  # pnl=+33% > 15%

    phase = KijunG3Exits(KijunG3Exits.Params(), logger=None)
    ctx = make_ctx(qc)
    result = phase.evaluate(ctx)

    assert result.blocked is False
    assert len(ctx.bar_state.exit_intents) == 1
    assert ctx.bar_state.exit_intents[0].ticker == "GOOG"


def test_g3_not_triggered_before_56_days():
    sym = make_symbol("TSLA")
    entry_date = datetime(2025, 6, 15) - timedelta(days=30)  # only 30d < 56d
    qc = FakeQC()
    qc.portfolio[sym] = FakeHolding(invested=True, quantity=100)
    qc.securities[sym] = FakeSecurity(close=80.0)  # below cloud_bottom but <56d
    qc._indicators[sym] = {
        "d_ichi": FakeIndicator(kijun=100.0, senkou_a=95.0, senkou_b=90.0),
        "w_ichi": None,
    }
    qc._position_meta[sym] = {"entry_date": entry_date, "entry_price": 60.0}

    phase = KijunG3Exits(KijunG3Exits.Params(), logger=None)
    ctx = make_ctx(qc)
    result = phase.evaluate(ctx)

    # Not in phase3, falls back to Kijun stop: close=80 < kijun=100 → exit fires
    assert len(ctx.bar_state.exit_intents) == 1
    assert ctx.bar_state.exit_intents[0].stop == 100.0  # kijun stop, not cloud_bottom


def test_skip_uninvested_positions():
    sym = make_symbol("AMZN")
    qc = FakeQC()
    qc.portfolio[sym] = FakeHolding(invested=False, quantity=0)
    qc._indicators[sym] = {"d_ichi": FakeIndicator(kijun=100.0), "w_ichi": None}
    qc.securities[sym] = FakeSecurity(close=90.0)

    phase = KijunG3Exits(KijunG3Exits.Params(), logger=None)
    ctx = make_ctx(qc)
    result = phase.evaluate(ctx)

    assert len(ctx.bar_state.exit_intents) == 0


def test_exit_phase_never_blocks():
    qc = FakeQC()
    phase = KijunG3Exits(KijunG3Exits.Params(), logger=None)
    ctx = make_ctx(qc)
    result = phase.evaluate(ctx)
    assert result.blocked is False


def test_cloud_exit_only_when_enabled():
    sym = make_symbol("META")
    qc = FakeQC()
    qc.portfolio[sym] = FakeHolding(invested=True, quantity=100)
    qc.securities[sym] = FakeSecurity(close=103.0)  # above kijun=100, below cloud_top=105
    qc._indicators[sym] = {
        "d_ichi": FakeIndicator(kijun=100.0, senkou_a=105.0, senkou_b=95.0),
        "w_ichi": None,
    }

    # Default: cloud_exit_enabled=False → no exit
    phase = KijunG3Exits(KijunG3Exits.Params(), logger=None)
    ctx = make_ctx(qc)
    result = phase.evaluate(ctx)
    assert len(ctx.bar_state.exit_intents) == 0

    # Enabled: cloud_exit_enabled=True → exit fires
    phase2 = KijunG3Exits(KijunG3Exits.Params(cloud_exit_enabled=True), logger=None)
    ctx2 = make_ctx(qc)
    result2 = phase2.evaluate(ctx2)
    assert len(ctx2.bar_state.exit_intents) == 1
