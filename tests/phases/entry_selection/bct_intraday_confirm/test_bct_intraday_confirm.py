"""#276b-1 — BctIntradayConfirm: the intraday tenkan-reclaim CROSS + rising-vol entry trigger.

The #244 methodology pillar (FIRE + DECLINE on dummy inputs). The HQ/Gemini-mandated case is the
CROSS-vs-LEVEL distinction: a bar ALREADY above Tenkan (no edge) must NOT fire; only the upward
CROSS (prior bar ≤ Tenkan → this bar > Tenkan) fires. Plus: weak-volume declines, window-close
drops (SG5), warming/no-prior-bar defer. Pure-core golden-master + a phase test over a bar sequence.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from engine.context import OrderIntent, PhaseContext
from phases.entry_selection.bct_intraday_confirm.bct_intraday_confirm import (
    BctIntradayConfirm,
    confirm_decision,
)


def _d(**kw: Any) -> tuple[bool, str]:
    kw.setdefault("prev_above", False)
    kw.setdefault("curr_above", True)
    kw.setdefault("curr_vol", 200.0)
    kw.setdefault("vol_mean", 100.0)
    kw.setdefault("vol_mult", 1.5)
    kw.setdefault("bars_elapsed", 1)
    kw.setdefault("window_bars", 24)
    return confirm_decision(**kw)


# ── PURE decision (golden-master) ──

def test_cross_up_with_volume_confirms() -> None:
    # prior bar NOT above → this bar above (the upward CROSS) + volume expansion → CONFIRM.
    assert _d(prev_above=False, curr_above=True, curr_vol=200.0, vol_mean=100.0) == (True, "confirmed")


def test_already_above_is_NOT_a_cross() -> None:
    # HQ/Gemini-MANDATED: a bar already above Tenkan (prev above, curr above) has NO edge → DECLINE.
    ok, reason = _d(prev_above=True, curr_above=True)
    assert ok is False and reason == "no_reclaim_cross"


def test_below_tenkan_no_cross() -> None:
    ok, reason = _d(prev_above=False, curr_above=False)
    assert ok is False and reason == "no_reclaim_cross"


def test_cross_down_is_not_a_reclaim() -> None:
    # above → below (a cross DOWN) is not a reclaim.
    ok, reason = _d(prev_above=True, curr_above=False)
    assert ok is False and reason == "no_reclaim_cross"


def test_cross_up_but_weak_volume_declines() -> None:
    ok, reason = _d(prev_above=False, curr_above=True, curr_vol=120.0, vol_mean=100.0, vol_mult=1.5)
    assert ok is False and reason == "weak_volume"  # 120 <= 100*1.5


def test_cross_up_exact_threshold_volume_declines() -> None:
    # strict '>' — exactly at mean×mult is NOT an expansion.
    ok, reason = _d(curr_vol=150.0, vol_mean=100.0, vol_mult=1.5)
    assert ok is False and reason == "weak_volume"


def test_window_closed_declines() -> None:
    ok, reason = _d(bars_elapsed=25, window_bars=24)
    assert ok is False and reason == "window_closed"


def test_warming_when_curr_above_none() -> None:
    ok, reason = _d(curr_above=None)
    assert ok is False and reason == "warming"


def test_no_prior_bar_defers() -> None:
    ok, reason = _d(prev_above=None, curr_above=True)
    assert ok is False and reason == "no_prior_bar"


def test_no_vol_baseline_declines() -> None:
    ok, reason = _d(vol_mean=None)
    assert ok is False and reason == "no_vol_baseline"


# ── PHASE (gates sized_orders over a bar SEQUENCE) ──

class _Sym:
    def __init__(self, v: str) -> None:
        self.value = v

    def __hash__(self) -> int:
        return hash(self.value)

    def __eq__(self, o: object) -> bool:
        return isinstance(o, _Sym) and o.value == self.value


class _Tenkan:
    def __init__(self, value: float, ready: bool = True) -> None:
        self.is_ready = ready
        self.current = type("C", (), {"value": value})()


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


def _phase(**kw: Any) -> BctIntradayConfirm:
    return BctIntradayConfirm(BctIntradayConfirm.Params(**kw), logger=None)


def _set_bar(qc: _QC, sym: _Sym, *, tenkan: float, close: float, vol: float,
             vol_window: list[float]) -> None:
    qc._intraday[sym] = {
        "intraday_tenkan": _Tenkan(tenkan),
        "vol_window": _VolWindow(vol_window),
        "last_close": close,
        "last_bar": _Bar(vol),
    }


def _ctx(qc: _QC, tickers: list[str]) -> PhaseContext:
    c = PhaseContext(qc=qc, time=datetime(2025, 2, 4), data=None)
    c.bar_state.sized_orders = [
        OrderIntent(ticker=t, qty=0, price=0.0, stop=0.0, module="signal", risk_dollars=0.0)
        for t in tickers
    ]
    return c


def test_phase_confirms_on_cross_up_sequence() -> None:
    # tick1: below Tenkan (prev_above set False, no fire). tick2: crosses above + volume → CONFIRM.
    sym = _Sym("AAPL")
    qc = _QC(sym)
    ph = _phase(vol_mult=1.5, window_bars=24)

    _set_bar(qc, sym, tenkan=100.0, close=99.0, vol=200.0, vol_window=[100.0, 100.0])
    c1 = _ctx(qc, ["aapl"])
    ph.evaluate(c1)
    assert [i.ticker for i in c1.bar_state.sized_orders] == []  # below → deferred (dropped)
    assert qc._entry_confirm["aapl"]["confirmed"] is False

    _set_bar(qc, sym, tenkan=100.0, close=101.0, vol=200.0, vol_window=[100.0, 100.0])  # cross up
    c2 = _ctx(qc, ["aapl"])  # re-injected
    ph.evaluate(c2)
    assert [i.ticker for i in c2.bar_state.sized_orders] == ["aapl"]  # CONFIRMED → kept
    assert qc._entry_confirm["aapl"]["confirmed"] is True


def test_phase_already_above_never_confirms() -> None:
    # both bars above Tenkan (no cross) → never confirms, dropped each tick (the level-vs-cross bug).
    sym = _Sym("AAPL")
    qc = _QC(sym)
    ph = _phase()
    for _ in range(3):
        _set_bar(qc, sym, tenkan=100.0, close=105.0, vol=500.0, vol_window=[100.0])
        c = _ctx(qc, ["aapl"])
        ph.evaluate(c)
        assert c.bar_state.sized_orders == []
    assert qc._entry_confirm["aapl"]["confirmed"] is False


def test_phase_confirmed_persists_across_ticks() -> None:
    sym = _Sym("AAPL")
    qc = _QC(sym)
    ph = _phase()
    _set_bar(qc, sym, tenkan=100.0, close=99.0, vol=200.0, vol_window=[100.0])  # below (prime prev)
    ph.evaluate(_ctx(qc, ["aapl"]))
    _set_bar(qc, sym, tenkan=100.0, close=101.0, vol=200.0, vol_window=[100.0])  # cross → confirm
    ph.evaluate(_ctx(qc, ["aapl"]))
    assert qc._entry_confirm["aapl"]["confirmed"] is True
    # a later tick (even back below Tenkan) keeps the confirmed candidate (re-fire-safe).
    _set_bar(qc, sym, tenkan=100.0, close=98.0, vol=10.0, vol_window=[100.0])
    c = _ctx(qc, ["aapl"])
    ph.evaluate(c)
    assert [i.ticker for i in c.bar_state.sized_orders] == ["aapl"]


def test_phase_window_expiry_drops_candidate() -> None:
    sym = _Sym("AAPL")
    qc = _QC(sym)
    ph = _phase(window_bars=3)
    # never crosses (stays below); after window_bars ticks → expired, dropped permanently.
    for _ in range(4):
        _set_bar(qc, sym, tenkan=100.0, close=99.0, vol=200.0, vol_window=[100.0])
        ph.evaluate(_ctx(qc, ["aapl"]))
    assert qc._entry_confirm["aapl"]["expired"] is True
    # even a textbook cross now is ignored (window closed).
    _set_bar(qc, sym, tenkan=100.0, close=101.0, vol=500.0, vol_window=[100.0])
    c = _ctx(qc, ["aapl"])
    ph.evaluate(c)
    assert c.bar_state.sized_orders == []


def test_phase_weak_volume_does_not_confirm() -> None:
    sym = _Sym("AAPL")
    qc = _QC(sym)
    ph = _phase(vol_mult=1.5)
    _set_bar(qc, sym, tenkan=100.0, close=99.0, vol=100.0, vol_window=[100.0])  # below
    ph.evaluate(_ctx(qc, ["aapl"]))
    _set_bar(qc, sym, tenkan=100.0, close=101.0, vol=120.0, vol_window=[100.0])  # cross, weak vol
    c = _ctx(qc, ["aapl"])
    ph.evaluate(c)
    assert c.bar_state.sized_orders == []  # 120 <= 100*1.5 → no confirm
    assert qc._entry_confirm["aapl"]["confirmed"] is False


def test_phase_never_blocks_the_bar() -> None:
    sym = _Sym("AAPL")
    qc = _QC(sym)
    _set_bar(qc, sym, tenkan=100.0, close=101.0, vol=200.0, vol_window=[100.0])
    res = _phase().evaluate(_ctx(qc, ["aapl"]))
    assert res.blocked is False


def test_space_and_complexity_declared() -> None:
    axes = BctIntradayConfirm.Params.space().axes
    assert "vol_mult" in axes and "window_bars" in axes
    assert BctIntradayConfirm.COMPLEXITY.free_params == 2
