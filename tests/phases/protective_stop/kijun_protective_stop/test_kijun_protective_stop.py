"""#276b-1/#290 — KijunProtectiveStop: the daily-Kijun catastrophic floor (pre-FIRE).

#244 FIRE + DECLINE. FIRE: a confirmed+sized entry gets protective_stop = the snapshot's daily
Kijun (BELOW entry, sane). DECLINE: the degenerate kijun ≥ entry (immediate stop-out) → drop the
entry LOUD (the silent-bad-trade case); H1 no-snapshot → drop; H2 stale snapshot → DegradedDataError
propagates. Pure floor golden-master + the phase stamping/declining sized_orders.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from engine.base import DegradedDataError
from engine.context import OrderIntent, PhaseContext
from phases.protective_stop.kijun_protective_stop.kijun_protective_stop import (
    KijunProtectiveStop,
    protective_floor,
)


# ── PURE floor (golden-master) ──

def test_floor_below_entry_ok() -> None:
    assert protective_floor(entry_price=100.0, daily_kijun=95.0) == (True, "ok")


def test_floor_at_entry_declines() -> None:
    ok, reason = protective_floor(entry_price=100.0, daily_kijun=100.0)
    assert ok is False and reason == "floor_at_or_above_entry"


def test_floor_above_entry_declines() -> None:
    ok, reason = protective_floor(entry_price=100.0, daily_kijun=105.0)
    assert ok is False and reason == "floor_at_or_above_entry"


def test_degraded_kijun_declines() -> None:
    ok, reason = protective_floor(entry_price=100.0, daily_kijun=0.0)
    assert ok is False and reason == "degraded_kijun"


def test_degraded_entry_declines() -> None:
    ok, reason = protective_floor(entry_price=0.0, daily_kijun=95.0)
    assert ok is False and reason == "degraded_entry"


# ── PHASE ──

class _Sym:
    def __init__(self, v: str) -> None:
        self.value = v

    def __hash__(self) -> int:
        return hash(self.value)

    def __eq__(self, o: object) -> bool:
        return isinstance(o, _Sym) and o.value == self.value


class _FakeQC:
    def __init__(self, snaps: dict[_Sym, Any]) -> None:
        self._snaps = snaps
        self._active = set(snaps)
        self.logged: list[str] = []

    def log(self, m: str) -> None:
        self.logged.append(m)

    def snapshot_for_entry(self, sym: Any) -> Any:
        return self._snaps.get(sym)


def _phase() -> KijunProtectiveStop:
    return KijunProtectiveStop(KijunProtectiveStop.Params(), logger=None)


def _ctx(qc: _FakeQC, intents: list[tuple[str, float]]) -> PhaseContext:
    c = PhaseContext(qc=qc, time=datetime(2025, 2, 4), data=None)
    c.bar_state.sized_orders = [
        OrderIntent(ticker=t, qty=10, price=px, stop=0.0, module="sizing", risk_dollars=1000.0)
        for t, px in intents
    ]
    return c


def test_phase_stamps_kijun_floor_below_entry() -> None:
    aapl = _Sym("AAPL")
    qc = _FakeQC({aapl: {"signal_price": 100.0, "daily_kijun": 95.0, "decision_date": "T"}})
    ctx = _ctx(qc, [("aapl", 100.0)])
    _phase().evaluate(ctx)
    kept = ctx.bar_state.sized_orders
    assert len(kept) == 1
    assert kept[0].protective_stop == 95.0 and kept[0].protective_stop < kept[0].price


def test_phase_declines_degenerate_floor_at_or_above_entry_loud() -> None:
    aapl = _Sym("AAPL")
    qc = _FakeQC({aapl: {"signal_price": 100.0, "daily_kijun": 101.0, "decision_date": "T"}})
    ctx = _ctx(qc, [("aapl", 100.0)])  # kijun 101 >= entry 100 → immediate stop-out → DECLINE
    _phase().evaluate(ctx)
    assert ctx.bar_state.sized_orders == []  # dropped, no immediate-stop-out floor placed
    assert any("PROTECTIVE_FLOOR_DECLINE" in m and "floor_at_or_above_entry" in m for m in qc.logged)


def test_phase_keeps_good_drops_degenerate_in_mixed_batch() -> None:
    good, bad = _Sym("AAPL"), _Sym("TSLA")
    qc = _FakeQC({
        good: {"signal_price": 100.0, "daily_kijun": 95.0, "decision_date": "T"},
        bad:  {"signal_price": 100.0, "daily_kijun": 100.0, "decision_date": "T"},
    })
    ctx = _ctx(qc, [("aapl", 100.0), ("tsla", 100.0)])
    _phase().evaluate(ctx)
    assert [i.ticker for i in ctx.bar_state.sized_orders] == ["aapl"]


def test_phase_h1_no_snapshot_drops() -> None:
    ghost = _Sym("GHOST")
    qc = _FakeQC({ghost: None})
    ctx = _ctx(qc, [("ghost", 100.0)])
    _phase().evaluate(ctx)
    assert ctx.bar_state.sized_orders == []


def test_phase_h2_stale_snapshot_propagates() -> None:
    good = _Sym("AAPL")

    class _StaleQC(_FakeQC):
        def snapshot_for_entry(self, sym: Any) -> Any:
            raise DegradedDataError("stale candidate snapshot (#276b-0 H2)")

    qc = _StaleQC({good: {"daily_kijun": 95.0}})
    with pytest.raises(DegradedDataError, match="stale"):
        _phase().evaluate(_ctx(qc, [("aapl", 100.0)]))


def test_phase_empty_tick_noop() -> None:
    qc = _FakeQC({})
    ctx = _ctx(qc, [])
    res = _phase().evaluate(ctx)
    assert ctx.bar_state.sized_orders == [] and res.facts["stamped"] == 0


def test_phase_never_blocks_the_bar() -> None:
    aapl = _Sym("AAPL")
    qc = _FakeQC({aapl: {"daily_kijun": 95.0}})
    assert _phase().evaluate(_ctx(qc, [("aapl", 100.0)])).blocked is False


def test_intraday_clock_no_axes_and_requires_sizing() -> None:
    assert KijunProtectiveStop.PHASE_RESOLUTION == "intraday"
    assert KijunProtectiveStop.PHASE_KIND == "protective_stop"
    assert "sizing" in KijunProtectiveStop.REQUIRES_UPSTREAM
    assert KijunProtectiveStop.Params.space().axes == {}
    assert KijunProtectiveStop.COMPLEXITY.free_params == 0
