"""#277 Rank-1 — BctIntradayGapVolConfirm: gap-magnitude + loud-open (no Tenkan). FIRE + DECLINE."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from engine.context import OrderIntent, PhaseContext
from phases.entry_selection.bct_intraday_gap_vol_confirm.bct_intraday_gap_vol_confirm import (
    BctIntradayGapVolConfirm,
    gap_vol_confirm_decision,
)


def _d(**kw: Any) -> tuple[bool, str]:
    kw.setdefault("gap_pct", 0.05); kw.setdefault("gap_threshold", 0.03)
    kw.setdefault("curr_vol", 120.0); kw.setdefault("vol_mean", 100.0)
    kw.setdefault("vol_mult", 1.0); kw.setdefault("bars_elapsed", 1); kw.setdefault("window_bars", 6)
    return gap_vol_confirm_decision(**kw)


def test_big_gap_loud_open_confirms() -> None:
    assert _d(gap_pct=0.05, curr_vol=120.0, vol_mean=100.0) == (True, "confirmed")  # +5% gap, loud


def test_gap_too_small_declines() -> None:
    ok, r = _d(gap_pct=0.02, gap_threshold=0.03)
    assert ok is False and r == "gap_too_small"


def test_quiet_open_declines() -> None:
    # winners HOLD (don't surge) → vol_mult=1.0 (loud=avg); a BELOW-avg open is quiet → decline.
    ok, r = _d(gap_pct=0.05, curr_vol=80.0, vol_mean=100.0, vol_mult=1.0)
    assert ok is False and r == "quiet_open"


def test_loud_open_at_baseline_confirms_not_a_surge() -> None:
    # vol EXACTLY at baseline (1×) is loud-enough — NOT a surge requirement (the Rank-2 trap).
    assert _d(gap_pct=0.04, curr_vol=100.0, vol_mean=100.0, vol_mult=1.0) == (True, "confirmed")


def test_warming_and_window() -> None:
    assert _d(gap_pct=None) == (False, "warming")
    assert _d(bars_elapsed=7, window_bars=6) == (False, "window_closed")


# ── PHASE ──

class _Sym:
    def __init__(self, v: str) -> None: self.value = v
    def __hash__(self) -> int: return hash(self.value)
    def __eq__(self, o: object) -> bool: return isinstance(o, _Sym) and o.value == self.value


class _VolWindow:
    def __init__(self, vals: list[float]) -> None: self._v = list(vals)
    @property
    def count(self) -> int: return len(self._v)
    def __getitem__(self, i: int) -> float: return self._v[i]


class _Bar:
    def __init__(self, volume: float) -> None: self.volume = volume


class _QC:
    def __init__(self, sym: _Sym, signal_price: float) -> None:
        self._active = {sym}
        self._snaps = {sym: {"signal_price": signal_price, "daily_kijun": 95.0, "decision_date": "T"}}
        self._intraday: dict[Any, dict[str, Any]] = {}
        self._entry_confirm: dict[str, Any] = {}

    def snapshot_for_entry(self, sym: Any) -> Any:
        return self._snaps.get(sym)


def _phase(**kw: Any) -> BctIntradayGapVolConfirm:
    return BctIntradayGapVolConfirm(BctIntradayGapVolConfirm.Params(**kw), logger=None)


def _ctx(qc: _QC, tk: str) -> PhaseContext:
    c = PhaseContext(qc=qc, time=datetime(2025, 2, 4), data=None)
    c.bar_state.sized_orders = [OrderIntent(ticker=tk, qty=0, price=0.0, stop=0.0, module="signal", risk_dollars=0.0)]
    return c


def test_phase_gap_up_loud_confirms() -> None:
    sym = _Sym("AAPL")
    qc = _QC(sym, signal_price=100.0)
    # +5% gap (last_close 105 vs signal 100), loud open (120 > mean 100) → confirm bar 1.
    qc._intraday[sym] = {"vol_window": _VolWindow([100.0, 100.0]), "last_close": 105.0, "last_bar": _Bar(120.0)}
    c = _ctx(qc, "aapl")
    _phase().evaluate(c)
    assert [i.ticker for i in c.bar_state.sized_orders] == ["aapl"]
    assert qc._entry_confirm["aapl"]["confirmed"] is True


def test_phase_small_gap_no_confirm() -> None:
    sym = _Sym("AAPL")
    qc = _QC(sym, signal_price=100.0)
    qc._intraday[sym] = {"vol_window": _VolWindow([100.0]), "last_close": 101.5, "last_bar": _Bar(500.0)}  # +1.5% < 3%
    c = _ctx(qc, "aapl")
    _phase().evaluate(c)
    assert c.bar_state.sized_orders == []


def test_space_and_complexity() -> None:
    assert set(BctIntradayGapVolConfirm.Params.space().axes) == {"gap_threshold", "vol_mult", "window_bars"}
    assert BctIntradayGapVolConfirm.COMPLEXITY.free_params == 3
