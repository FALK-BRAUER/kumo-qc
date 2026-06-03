"""#348 V1 BuyStopBreakoutConfirm — confirm only on a buy-stop breakout above signal_price×(1+buffer)."""
from datetime import datetime
from typing import Any

from engine.context import OrderIntent, PhaseContext
from phases.entry_selection.buy_stop_breakout_confirm.buy_stop_breakout_confirm import (
    BuyStopBreakoutConfirm, breakout_confirm_decision,
)


# ── pure decision ──

def test_decision_confirms_above_buystop():
    ok, r = breakout_confirm_decision(curr_price=101.0, signal_price=100.0, breakout_buffer=0.0075,
                                      bars_elapsed=1, window_bars=78)
    assert ok and r == "confirmed"  # 101 >= 100*1.0075 = 100.75


def test_decision_below_buystop_declines():
    ok, r = breakout_confirm_decision(curr_price=100.5, signal_price=100.0, breakout_buffer=0.0075,
                                      bars_elapsed=1, window_bars=78)
    assert not ok and r == "below_buystop"  # 100.5 < 100.75


def test_decision_window_closed():
    ok, r = breakout_confirm_decision(curr_price=200.0, signal_price=100.0, breakout_buffer=0.0075,
                                      bars_elapsed=79, window_bars=78)
    assert not ok and r == "window_closed"


def test_decision_warming():
    ok, r = breakout_confirm_decision(curr_price=None, signal_price=100.0, breakout_buffer=0.0075,
                                      bars_elapsed=1, window_bars=78)
    assert not ok and r == "warming"


# ── phase ──

class _Sym:
    def __init__(self, v: str) -> None: self.value = v
    def __hash__(self) -> int: return hash(self.value)
    def __eq__(self, o: object) -> bool: return isinstance(o, _Sym) and o.value == self.value


class _QC:
    def __init__(self, sym: _Sym, signal_price: float) -> None:
        self._active = {sym}
        self._snaps = {sym: {"signal_price": signal_price, "daily_kijun": 95.0, "decision_date": "T"}}
        self._intraday: dict[Any, dict[str, Any]] = {}
        self._entry_confirm: dict[str, Any] = {}

    def snapshot_for_entry(self, sym: Any) -> Any:
        return self._snaps.get(sym)


def _phase(**kw: Any) -> BuyStopBreakoutConfirm:
    return BuyStopBreakoutConfirm(BuyStopBreakoutConfirm.Params(**kw), logger=None)


def _ctx(qc: _QC, tk: str) -> PhaseContext:
    c = PhaseContext(qc=qc, time=datetime(2025, 1, 3), data=None)
    c.bar_state.sized_orders = [OrderIntent(ticker=tk, qty=0, price=0.0, stop=0.0, module="signal", risk_dollars=0.0)]
    return c


def test_phase_breakout_confirms():
    # HOOD-like: breaks above the +0.75% buy-stop (102 > 100.75) → confirm.
    sym = _Sym("HOOD")
    qc = _QC(sym, signal_price=100.0)
    qc._intraday[sym] = {"last_close": 102.0}
    c = _ctx(qc, "hood")
    _phase().evaluate(c)
    assert [i.ticker for i in c.bar_state.sized_orders] == ["hood"]
    assert qc._entry_confirm["hood"]["confirmed"] is True


def test_phase_chop_never_confirms():
    # MRVL-like: gaps but chops below the buy-stop (100.3 < 100.75) → no entry, expires at window close.
    sym = _Sym("MRVL")
    qc = _QC(sym, signal_price=100.0)
    qc._intraday[sym] = {"last_close": 100.3}
    c = _ctx(qc, "mrvl")
    p = _phase(window_bars=1)
    p.evaluate(c)                 # bar 1: below buy-stop
    assert c.bar_state.sized_orders == []
    c2 = _ctx(qc, "mrvl")
    p.evaluate(c2)                # bar 2: window_closed → expired
    assert qc._entry_confirm["mrvl"]["expired"] is True


def test_space_and_complexity():
    assert set(BuyStopBreakoutConfirm.Params.space().axes) == {"breakout_buffer", "window_bars"}
    assert BuyStopBreakoutConfirm.COMPLEXITY.free_params == 2
