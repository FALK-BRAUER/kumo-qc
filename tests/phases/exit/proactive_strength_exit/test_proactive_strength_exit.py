from datetime import datetime

import pytest

from engine.base import DegradedDataError
from engine.context import PhaseContext
from phases.exit.proactive_strength_exit.proactive_strength_exit import ProactiveStrengthExit


class FakeIchi:
    def __init__(self, tenkan=105.0, kijun=100.0, senkou_a=98.0, senkou_b=95.0, ready=True):
        self.is_ready = ready
        self.tenkan = type("V", (), {"current": type("C", (), {"value": tenkan})()})()
        self.kijun = type("V", (), {"current": type("C", (), {"value": kijun})()})()
        self.senkou_a = type("V", (), {"current": type("C", (), {"value": senkou_a})()})()
        self.senkou_b = type("V", (), {"current": type("C", (), {"value": senkou_b})()})()


class FakeHolding:
    def __init__(self, quantity=100):
        self.invested = True
        self.quantity = quantity


class FakeSecurity:
    def __init__(self, close):
        self.close = close
        self.price = close


class FakeTransactions:
    def get_open_orders(self, symbol=None):
        return []


class FakeQC:
    def __init__(self, sym, close=106.0, entry=100.0):
        self.portfolio = {sym: FakeHolding()}
        self.securities = {sym: FakeSecurity(close)}
        self.transactions = FakeTransactions()
        self._position_meta = {sym: {"entry_price": entry, "entry_date": datetime(2025, 1, 1)}}
        self._position_path = {sym: {"peak_price": close, "mfe_pct": close / entry - 1.0, "days_held": 9}}
        self._indicators = {sym: {"d_ichi": FakeIchi()}}
        self.logged = []

    def log(self, msg):
        self.logged.append(msg)


def _sym(name="AAPL"):
    return type("Symbol", (), {"value": name})()


def _run(qc, **params):
    ctx = PhaseContext(qc=qc, time=datetime(2025, 1, 10), data=None)
    phase = ProactiveStrengthExit(ProactiveStrengthExit.Params(**params), logger=None)
    result = phase.evaluate(ctx)
    return result, ctx


def test_target_exit_fires_while_still_bullish():
    sym = _sym()
    qc = FakeQC(sym, close=106.0)
    result, ctx = _run(qc, target_pct=0.06)

    assert result.facts["target_count"] == 1
    assert len(ctx.bar_state.exit_intents) == 1
    intent = ctx.bar_state.exit_intents[0]
    assert intent.ticker == "AAPL"
    assert intent.qty == -100
    assert intent.order_type == "market"
    assert qc.logged == [
        "EXIT_EVENT|2025-01-10|AAPL|event=PROACTIVE_STRENGTH_EXIT|module=exit.proactive_strength_exit"
        "|reason=target|days_held=9|qty=100.000000|entry_price=100.000000|exit_price=106.000000"
        "|pnl=600.000000|return_pct=0.060000|mfe_pct=0.060000|mae_pct=0.000000"
        "|peak_return_pct=0.060000|giveback_from_peak_pct=0.000000"
    ]


def test_requires_position_path_contract():
    assert ProactiveStrengthExit.REQUIRES_UPSTREAM == ["position_path"]
    assert ProactiveStrengthExit.PHASE_RESOLUTION == "intraday"


def test_missing_position_path_raises_loud():
    sym = _sym("MSFT")
    qc = FakeQC(sym, close=106.0)
    qc._position_path = {}

    with pytest.raises(DegradedDataError, match="PositionPathTracker"):
        _run(qc, target_pct=0.06)


def test_giveback_exit_fires_after_profitable_peak():
    sym = _sym("MSFT")
    qc = FakeQC(sym, close=104.0)
    qc._position_path = {sym: {"peak_price": 108.0, "mfe_pct": 0.08, "days_held": 9}}

    result, ctx = _run(qc, target_pct=0.10, min_peak_pct=0.05, giveback_from_peak_pct=0.025)

    assert result.facts["giveback_count"] == 1
    assert len(ctx.bar_state.exit_intents) == 1
    assert ctx.bar_state.exit_intents[0].ticker == "MSFT"


def test_uses_position_path_last_price_for_intraday_exit():
    sym = _sym("META")
    qc = FakeQC(sym, close=101.0)
    qc._position_path = {
        sym: {
            "last_price": 106.5,
            "peak_price": 106.5,
            "current_return_pct": 0.065,
            "mfe_pct": 0.065,
            "days_held": 2,
        }
    }

    result, ctx = _run(qc, target_pct=0.06)

    assert result.facts["target_count"] == 1
    assert ctx.bar_state.exit_intents[0].price == 106.5


def test_no_exit_when_not_still_bullish():
    sym = _sym("TSLA")
    qc = FakeQC(sym, close=106.0)
    qc._indicators[sym] = {"d_ichi": FakeIchi(tenkan=95.0, kijun=100.0)}

    result, ctx = _run(qc, target_pct=0.06, require_still_bullish=True)

    assert result.facts["exit_count"] == 0
    assert ctx.bar_state.exit_intents == []


def test_min_hold_days_defers_proactive_exit():
    sym = _sym("AMD")
    qc = FakeQC(sym, close=110.0)
    qc._position_path[sym]["days_held"] = 3

    result, ctx = _run(qc, target_pct=0.06, min_hold_days=7)

    assert result.facts["exit_count"] == 0
    assert ctx.bar_state.exit_intents == []
    assert qc.logged == []


def test_skips_when_exit_already_present():
    sym = _sym("NVDA")
    qc = FakeQC(sym, close=110.0)
    ctx = PhaseContext(qc=qc, time=datetime(2025, 1, 10), data=None)
    ctx.bar_state.exit_intents.append(
        type("Intent", (), {"ticker": "NVDA"})()
    )

    ProactiveStrengthExit(ProactiveStrengthExit.Params(), logger=None).evaluate(ctx)

    assert len(ctx.bar_state.exit_intents) == 1
