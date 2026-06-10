from datetime import datetime

import pytest

from engine.base import DegradedDataError
from engine.context import PhaseContext
from phases.exit.stale_mfe_exit.stale_mfe_exit import StaleMfeExit


class FakeHolding:
    def __init__(self, quantity=100):
        self.invested = True
        self.quantity = quantity


class FakeTransactions:
    def get_open_orders(self, symbol=None):
        return []


class FakeQC:
    def __init__(self, sym):
        self.portfolio = {sym: FakeHolding()}
        self.transactions = FakeTransactions()
        self.securities = {sym: type("Security", (), {"close": 100.0})()}
        self._position_meta = {sym: {"entry_price": 100.0, "entry_date": datetime(2025, 1, 1)}}
        self._position_path = {}
        self.logged = []

    def log(self, msg):
        self.logged.append(msg)


def _sym(name="AAPL"):
    return type("Symbol", (), {"value": name})()


def _path(price: float, mfe_pct: float, *, days_held: int = 10) -> dict[str, float | int]:
    current_return_pct = price / 100.0 - 1.0
    return {
        "last_price": price,
        "peak_price": 100.0 * (1.0 + mfe_pct),
        "trough_price": min(price, 100.0),
        "current_return_pct": current_return_pct,
        "mfe_pct": mfe_pct,
        "mae_pct": min(current_return_pct, 0.0),
        "giveback_pct": max(mfe_pct - current_return_pct, 0.0),
        "days_held": days_held,
    }


def _evaluate(phase: StaleMfeExit, qc: FakeQC, sym, day: int, path: dict[str, float | int]):
    qc._position_path[sym] = path
    ctx = PhaseContext(qc=qc, time=datetime(2025, 1, day, 10, 35), data=None)
    return phase.evaluate(ctx), ctx


def test_contract_and_clock_are_intraday():
    assert StaleMfeExit.REQUIRES_UPSTREAM == ["position_path"]
    assert StaleMfeExit.PHASE_RESOLUTION == "intraday"


def test_stale_mfe_exit_waits_for_sessions_then_exits():
    sym = _sym()
    qc = FakeQC(sym)
    phase = StaleMfeExit(
        StaleMfeExit.Params(
            stale_sessions=2,
            min_hold_sessions=2,
            min_mfe_pct=0.04,
            min_giveback_pct=0.01,
        ),
        logger=None,
    )

    result, ctx = _evaluate(phase, qc, sym, 2, _path(104.0, 0.06, days_held=1))
    assert result.facts["exit_count"] == 0
    assert ctx.bar_state.exit_intents == []

    result, ctx = _evaluate(phase, qc, sym, 3, _path(104.0, 0.06, days_held=2))
    assert result.facts["exit_count"] == 0
    assert ctx.bar_state.exit_intents == []

    result, ctx = _evaluate(phase, qc, sym, 6, _path(104.0, 0.06, days_held=4))

    assert result.facts == {"exit_count": 1, "stale_count": 1, "age_count": 0}
    assert len(ctx.bar_state.exit_intents) == 1
    assert ctx.bar_state.exit_intents[0].ticker == "AAPL"
    assert ctx.bar_state.exit_intents[0].qty == -100
    assert ctx.bar_state.exit_intents[0].order_type == "market"
    assert "reason=stale_mfe" in qc.logged[-1]


def test_new_mfe_resets_stale_counter():
    sym = _sym("RESET")
    qc = FakeQC(sym)
    phase = StaleMfeExit(
        StaleMfeExit.Params(
            stale_sessions=2,
            min_hold_sessions=2,
            min_mfe_pct=0.04,
            min_giveback_pct=0.015,
        ),
        logger=None,
    )

    _evaluate(phase, qc, sym, 2, _path(103.0, 0.05))
    _evaluate(phase, qc, sym, 3, _path(104.0, 0.06))
    result, ctx = _evaluate(phase, qc, sym, 6, _path(104.0, 0.06))

    assert result.facts["exit_count"] == 0
    assert ctx.bar_state.exit_intents == []

    result, ctx = _evaluate(phase, qc, sym, 7, _path(104.0, 0.06))

    assert result.facts["stale_count"] == 1
    assert ctx.bar_state.exit_intents[0].ticker == "RESET"


def test_age_cap_can_exit_even_without_mfe_progress():
    sym = _sym("AGE")
    qc = FakeQC(sym)
    phase = StaleMfeExit(
        StaleMfeExit.Params(
            stale_sessions=0,
            max_hold_sessions=2,
            max_hold_return_pct=0.02,
        ),
        logger=None,
    )

    _evaluate(phase, qc, sym, 2, _path(101.0, 0.01, days_held=1))
    _evaluate(phase, qc, sym, 3, _path(101.0, 0.01, days_held=2))
    result, ctx = _evaluate(phase, qc, sym, 6, _path(101.0, 0.01, days_held=4))

    assert result.facts == {"exit_count": 1, "stale_count": 0, "age_count": 1}
    assert ctx.bar_state.exit_intents[0].ticker == "AGE"
    assert "reason=age_cap" in qc.logged[-1]


def test_age_cap_can_leave_valid_runner_alone():
    sym = _sym("RUN")
    qc = FakeQC(sym)
    phase = StaleMfeExit(
        StaleMfeExit.Params(
            stale_sessions=0,
            max_hold_sessions=1,
            max_hold_return_pct=0.02,
        ),
        logger=None,
    )

    _evaluate(phase, qc, sym, 2, _path(105.0, 0.06))
    result, ctx = _evaluate(phase, qc, sym, 3, _path(105.0, 0.06))

    assert result.facts["exit_count"] == 0
    assert ctx.bar_state.exit_intents == []


def test_missing_position_path_raises_loud():
    sym = _sym("MISS")
    qc = FakeQC(sym)
    phase = StaleMfeExit(StaleMfeExit.Params(), logger=None)

    with pytest.raises(DegradedDataError, match="PositionPathTracker"):
        phase.evaluate(PhaseContext(qc=qc, time=datetime(2025, 1, 2, 10, 35), data=None))
