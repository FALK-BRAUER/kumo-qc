"""#276b-1 EXPERIMENT — BctIntradayHoldConfirm: above-Tenkan HOLD + rising-vol (no reclaim-cross).

The gap-up-compatible variant: a candidate ALREADY ABOVE the Tenkan (where the reclaim-cross fires
NOTHING — no_reclaim_cross) DOES confirm here on a single bar (hold-above + vol expansion). FIRE +
DECLINE pinned; the rising-vol gate is the selectivity (the experiment measures whether it has edge).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from engine.context import OrderIntent, PhaseContext
from phases.entry_selection.bct_intraday_hold_confirm.bct_intraday_hold_confirm import (
    BctIntradayHoldConfirm,
    hold_confirm_decision,
)


def _d(**kw: Any) -> tuple[bool, str]:
    kw.setdefault("curr_above", True)
    kw.setdefault("curr_vol", 200.0)
    kw.setdefault("vol_mean", 100.0)
    kw.setdefault("vol_mult", 1.5)
    kw.setdefault("bars_elapsed", 1)
    kw.setdefault("window_bars", 24)
    return hold_confirm_decision(**kw)


# ── PURE ──

def test_above_tenkan_with_vol_confirms_no_cross_needed() -> None:
    # the KEY difference vs reclaim-cross: ALREADY above (no from-below edge) + vol → CONFIRM.
    assert _d(curr_above=True, curr_vol=200.0, vol_mean=100.0) == (True, "confirmed")


def test_below_tenkan_declines() -> None:
    ok, reason = _d(curr_above=False)
    assert ok is False and reason == "below_tenkan"


def test_above_but_weak_volume_declines() -> None:
    ok, reason = _d(curr_above=True, curr_vol=120.0, vol_mean=100.0, vol_mult=1.5)
    assert ok is False and reason == "weak_volume"


def test_warming_declines() -> None:
    assert _d(curr_above=None) == (False, "warming")


def test_window_closed_declines() -> None:
    assert _d(bars_elapsed=25, window_bars=24) == (False, "window_closed")


# ── PHASE ──

class _Sym:
    def __init__(self, v: str) -> None:
        self.value = v

    def __hash__(self) -> int:
        return hash(self.value)

    def __eq__(self, o: object) -> bool:
        return isinstance(o, _Sym) and o.value == self.value


class _Tenkan:
    def __init__(self, v: float) -> None:
        self.is_ready = True
        self.current = type("C", (), {"value": v})()


class _VolWindow:
    def __init__(self, vals: list[float]) -> None:
        self._v = list(vals)

    @property
    def count(self) -> int:
        return len(self._v)

    def __getitem__(self, i: int) -> float:
        return self._v[i]


class _Bar:
    def __init__(self, volume: float) -> None:
        self.volume = volume


class _QC:
    def __init__(self, sym: _Sym) -> None:
        self._active = {sym}
        self._intraday: dict[Any, dict[str, Any]] = {}
        self._entry_confirm: dict[str, Any] = {}


def _phase(**kw: Any) -> BctIntradayHoldConfirm:
    return BctIntradayHoldConfirm(BctIntradayHoldConfirm.Params(**kw), logger=None)


def _ctx(qc: _QC, tickers: list[str]) -> PhaseContext:
    c = PhaseContext(qc=qc, time=datetime(2025, 2, 4), data=None)
    c.bar_state.sized_orders = [
        OrderIntent(ticker=t, qty=0, price=0.0, stop=0.0, module="signal", risk_dollars=0.0)
        for t in tickers
    ]
    return c


def test_phase_gap_up_already_above_confirms_first_bar() -> None:
    # a gap-up that opens ABOVE Tenkan (105 close > 100 Tenkan) + vol surge → confirms bar 1.
    # (the reclaim-cross would never fire this — no from-below cross.)
    sym = _Sym("AAPL")
    qc = _QC(sym)
    qc._intraday[sym] = {"intraday_tenkan": _Tenkan(100.0), "vol_window": _VolWindow([100.0, 100.0]),
                         "last_close": 105.0, "last_bar": _Bar(500.0)}
    c = _ctx(qc, ["aapl"])
    _phase().evaluate(c)
    assert [i.ticker for i in c.bar_state.sized_orders] == ["aapl"]
    assert qc._entry_confirm["aapl"]["confirmed"] is True


def test_phase_below_tenkan_does_not_confirm() -> None:
    sym = _Sym("AAPL")
    qc = _QC(sym)
    qc._intraday[sym] = {"intraday_tenkan": _Tenkan(100.0), "vol_window": _VolWindow([100.0]),
                         "last_close": 98.0, "last_bar": _Bar(500.0)}
    c = _ctx(qc, ["aapl"])
    _phase().evaluate(c)
    assert c.bar_state.sized_orders == []


def test_phase_never_blocks() -> None:
    sym = _Sym("AAPL")
    qc = _QC(sym)
    qc._intraday[sym] = {"intraday_tenkan": _Tenkan(100.0), "vol_window": _VolWindow([100.0]),
                         "last_close": 105.0, "last_bar": _Bar(500.0)}
    assert _phase().evaluate(_ctx(qc, ["aapl"])).blocked is False


def test_space_and_complexity() -> None:
    assert set(BctIntradayHoldConfirm.Params.space().axes) == {"vol_mult", "window_bars"}
    assert BctIntradayHoldConfirm.COMPLEXITY.free_params == 2
