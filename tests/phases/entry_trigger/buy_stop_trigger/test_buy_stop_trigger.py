"""BuyStopTrigger: fires only when the current bar trades through the armed buy-stop."""
from datetime import datetime

from engine.context import PhaseContext
from phases.entry_trigger.buy_stop_trigger.buy_stop_trigger import BuyStopTrigger


class _Sym:
    def __init__(self, value: str) -> None:
        self.value = value

    def __hash__(self) -> int:
        return hash(self.value)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _Sym) and other.value == self.value


class _Hold:
    invested = False


class _Sec:
    def __init__(self, high: float, close: float) -> None:
        self.high = high
        self.close = close


class _QC:
    def __init__(self, high: float, close: float) -> None:
        self.sym = _Sym("AAA")
        self._armed = {self.sym: {"zone": 100.0}}
        self.portfolio = {self.sym: _Hold()}
        self.securities = {self.sym: _Sec(high, close)}


def _run(high: float, close: float, breakout_pct: float = 0.01) -> int:
    qc = _QC(high, close)
    ctx = PhaseContext(qc=qc, time=datetime(2025, 1, 2, 10, 0), data=None, clock="intraday")
    BuyStopTrigger(BuyStopTrigger.Params(breakout_pct=breakout_pct), logger=None).evaluate(ctx)
    return len(ctx.bar_state.sized_orders)


def test_fires_when_bar_high_crosses_buy_stop() -> None:
    assert _run(high=101.5, close=101.0, breakout_pct=0.01) == 1


def test_declines_when_bar_high_stays_below_buy_stop() -> None:
    assert _run(high=100.5, close=100.4, breakout_pct=0.01) == 0
