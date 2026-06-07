from datetime import datetime

import pytest

from engine.base import DegradedDataError
from engine.context import PhaseContext
from phases.exit.scratch_flat_exit.scratch_flat_exit import ScratchFlatExit


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
    def __init__(self, sym, close=100.0, entry=100.0, entry_date=datetime(2025, 1, 1)):
        self.portfolio = {sym: FakeHolding()}
        self.securities = {sym: FakeSecurity(close)}
        self.transactions = FakeTransactions()
        self._position_meta = {sym: {"entry_price": entry, "entry_date": entry_date}}
        self._position_path = {
            sym: {
                "peak_price": max(close, entry),
                "mfe_pct": max(close, entry) / entry - 1.0,
                "days_held": 5,
            }
        }
        self.logged = []

    def log(self, msg):
        self.logged.append(msg)


def _sym(name="AAPL"):
    return type("Symbol", (), {"value": name})()


def _run(qc, now=datetime(2025, 1, 6), **params):
    ctx = PhaseContext(qc=qc, time=now, data=None)
    phase = ScratchFlatExit(ScratchFlatExit.Params(**params), logger=None)
    result = phase.evaluate(ctx)
    return result, ctx


def test_no_progress_exit_after_wait_window():
    sym = _sym()
    qc = FakeQC(sym, close=100.2)

    result, ctx = _run(qc, no_progress_days=3, min_mfe_pct=0.02)

    assert result.facts["no_progress_count"] == 1
    assert len(ctx.bar_state.exit_intents) == 1
    assert ctx.bar_state.exit_intents[0].ticker == "AAPL"
    assert qc.logged == [
        "EXIT_EVENT|2025-01-06|AAPL|event=SCRATCH_FLAT_EXIT|module=exit.scratch_flat_exit"
        "|reason=no_progress|days_held=5|qty=100.000000|entry_price=100.000000|exit_price=100.200000"
        "|pnl=20.000000|return_pct=0.002000|mfe_pct=0.002000|mae_pct=0.000000"
        "|peak_return_pct=0.002000|giveback_from_peak_pct=0.000000"
    ]


def test_requires_position_path_contract():
    assert ScratchFlatExit.REQUIRES_UPSTREAM == ["position_path"]


def test_missing_position_path_raises_loud():
    sym = _sym("MSFT")
    qc = FakeQC(sym, close=100.2)
    qc._position_path = {}

    with pytest.raises(DegradedDataError, match="PositionPathTracker"):
        _run(qc)


def test_roundtrip_to_flat_after_mfe_exits():
    sym = _sym("MSFT")
    qc = FakeQC(sym, close=100.2)
    qc._position_path = {sym: {"peak_price": 104.0, "mfe_pct": 0.04, "days_held": 5}}

    result, ctx = _run(qc, min_mfe_pct=0.02, scratch_band_pct=0.005)

    assert result.facts["roundtrip_count"] == 1
    assert len(ctx.bar_state.exit_intents) == 1
    assert ctx.bar_state.exit_intents[0].ticker == "MSFT"


def test_loss_cap_after_mfe_exits():
    sym = _sym("TSLA")
    qc = FakeQC(sym, close=97.5)
    qc._position_path = {sym: {"peak_price": 103.0, "mfe_pct": 0.03, "days_held": 5}}

    result, ctx = _run(qc, min_mfe_pct=0.02, max_loss_after_mfe_pct=0.02)

    assert result.facts["capped_loss_count"] == 1
    assert len(ctx.bar_state.exit_intents) == 1


def test_holds_young_trade_with_no_mfe():
    sym = _sym("NVDA")
    qc = FakeQC(sym, close=100.2, entry_date=datetime(2025, 1, 5))
    qc._position_path[sym]["days_held"] = 1

    result, ctx = _run(qc, now=datetime(2025, 1, 6), no_progress_days=3)

    assert result.facts["exit_count"] == 0
    assert ctx.bar_state.exit_intents == []
