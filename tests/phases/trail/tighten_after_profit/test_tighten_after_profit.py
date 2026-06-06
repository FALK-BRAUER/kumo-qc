"""TightenAfterProfit: raises stored stops after unrealized profit exceeds the threshold."""
from datetime import datetime

from engine.context import PhaseContext
from phases.trail.tighten_after_profit.tighten_after_profit import TightenAfterProfit


class _Sym:
    def __init__(self, value: str) -> None:
        self.value = value

    def __hash__(self) -> int:
        return hash(self.value)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _Sym) and other.value == self.value


class _Hold:
    invested = True


class _Sec:
    def __init__(self, close: float) -> None:
        self.close = close


class _QC:
    def __init__(self, close: float) -> None:
        self.sym = _Sym("AAA")
        self.portfolio = {self.sym: _Hold()}
        self.securities = {self.sym: _Sec(close)}
        self._position_meta = {self.sym: {"entry_price": 100.0}}
        self._initial_stops = {self.sym: 90.0}


def _run(close: float) -> float:
    qc = _QC(close)
    TightenAfterProfit(TightenAfterProfit.Params(profit_trigger_pct=0.10, lock_profit_pct=0.02), logger=None).evaluate(
        PhaseContext(qc=qc, time=datetime(2025, 1, 2), data=None)
    )
    return qc._initial_stops[qc.sym]


def test_raises_stop_after_profit_threshold() -> None:
    assert _run(112.0) == 102.0


def test_keeps_stop_before_profit_threshold() -> None:
    assert _run(108.0) == 90.0
