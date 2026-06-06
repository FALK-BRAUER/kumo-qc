"""AtrStop: stamps price - ATR*mult for invested positions."""
from datetime import datetime

from engine.context import PhaseContext
from phases.stops_initial.atr_stop.atr_stop import AtrStop


class _Sym:
    def __init__(self, value: str) -> None:
        self.value = value

    def __hash__(self) -> int:
        return hash(self.value)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _Sym) and other.value == self.value


class _Hold:
    def __init__(self, invested: bool) -> None:
        self.invested = invested


class _Sec:
    def __init__(self, price: float) -> None:
        self.price = price


class _QC:
    def __init__(self) -> None:
        self.sym = _Sym("AAA")
        self._active = {self.sym}
        self.portfolio = {self.sym: _Hold(True)}
        self.securities = {self.sym: _Sec(100.0)}
        self._atr = {"AAA": 4.0}


def test_stamps_atr_stop_for_invested_position() -> None:
    qc = _QC()
    AtrStop(AtrStop.Params(atr_mult=2.5), logger=None).evaluate(PhaseContext(qc=qc, time=datetime(2025, 1, 2), data=None))
    assert qc._initial_stops[qc.sym] == 90.0


def test_skips_uninvested_position() -> None:
    qc = _QC()
    qc.portfolio[qc.sym] = _Hold(False)
    AtrStop(AtrStop.Params(), logger=None).evaluate(PhaseContext(qc=qc, time=datetime(2025, 1, 2), data=None))
    assert qc._initial_stops == {}
