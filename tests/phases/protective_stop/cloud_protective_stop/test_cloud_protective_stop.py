"""#339 — CloudProtectiveStop: the cloud-bottom catastrophic floor (pre-FIRE). Mirrors the
KijunProtectiveStop contract; floor = snapshot daily_cloud_bottom (WIDER than the Kijun → holds
recoverable Kijun-dips above the cloud). Pure cloud_floor golden + phase stamp/decline."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from engine.context import OrderIntent, PhaseContext
from phases.protective_stop.cloud_protective_stop.cloud_protective_stop import (
    CloudProtectiveStop,
    cloud_floor,
)


# ── PURE floor (golden-master) ──

def test_floor_below_entry_ok() -> None:
    assert cloud_floor(entry_price=100.0, cloud_bottom=90.0) == (True, "ok")


def test_floor_at_or_above_entry_declines() -> None:
    assert cloud_floor(entry_price=100.0, cloud_bottom=100.0)[1] == "floor_at_or_above_entry"
    assert cloud_floor(entry_price=100.0, cloud_bottom=105.0)[1] == "floor_at_or_above_entry"


def test_degraded_declines() -> None:
    assert cloud_floor(entry_price=100.0, cloud_bottom=0.0)[1] == "degraded_cloud"
    assert cloud_floor(entry_price=0.0, cloud_bottom=90.0)[1] == "degraded_entry"


# ── PHASE ──

class _Sym:
    def __init__(self, v: str) -> None:
        self.value = v

    def __hash__(self) -> int:
        return hash(self.value)

    def __eq__(self, o: object) -> bool:
        return isinstance(o, _Sym) and o.value == self.value


class _FakeQC:
    def __init__(self, snaps: dict) -> None:
        self._snaps = snaps
        self._active = set(snaps)
        self.logged: list[str] = []

    def log(self, m: str) -> None:
        self.logged.append(m)

    def snapshot_for_entry(self, sym: Any) -> Any:
        return self._snaps.get(sym)


def _phase() -> CloudProtectiveStop:
    return CloudProtectiveStop(CloudProtectiveStop.Params(), logger=None)


def _ctx(qc: _FakeQC, intents: list[tuple[str, float]]) -> PhaseContext:
    c = PhaseContext(qc=qc, time=datetime(2025, 2, 4), data=None)
    c.bar_state.sized_orders = [
        OrderIntent(ticker=t, qty=10, price=px, stop=0.0, module="sizing", risk_dollars=1000.0)
        for t, px in intents
    ]
    return c


def test_phase_stamps_cloud_bottom_floor_below_entry() -> None:
    aapl = _Sym("AAPL")
    # cloud_bottom (90) sits BELOW the Kijun (95) — the floor is WIDER, holds the recoverable dip.
    qc = _FakeQC({aapl: {"daily_kijun": 95.0, "daily_cloud_bottom": 90.0, "decision_date": "T"}})
    ctx = _ctx(qc, [("aapl", 100.0)])
    _phase().evaluate(ctx)
    kept = ctx.bar_state.sized_orders
    assert len(kept) == 1
    assert kept[0].protective_stop == 90.0 and kept[0].protective_stop < kept[0].price


def test_phase_declines_degenerate_floor_at_or_above_entry_loud() -> None:
    aapl = _Sym("AAPL")
    qc = _FakeQC({aapl: {"daily_cloud_bottom": 101.0, "decision_date": "T"}})
    ctx = _ctx(qc, [("aapl", 100.0)])
    _phase().evaluate(ctx)
    assert ctx.bar_state.sized_orders == []
    assert any("PROTECTIVE_FLOOR_DECLINE" in m and "floor_at_or_above_entry" in m for m in qc.logged)


def test_phase_h1_no_snapshot_drops() -> None:
    ghost = _Sym("GHOST")
    qc = _FakeQC({ghost: None})
    ctx = _ctx(qc, [("ghost", 100.0)])
    _phase().evaluate(ctx)
    assert ctx.bar_state.sized_orders == []


def test_phase_keeps_good_drops_degenerate_in_mixed_batch() -> None:
    good, bad = _Sym("AAPL"), _Sym("TSLA")
    qc = _FakeQC({
        good: {"daily_cloud_bottom": 90.0, "decision_date": "T"},
        bad:  {"daily_cloud_bottom": 100.0, "decision_date": "T"},
    })
    ctx = _ctx(qc, [("aapl", 100.0), ("tsla", 100.0)])
    _phase().evaluate(ctx)
    assert [i.ticker for i in ctx.bar_state.sized_orders] == ["aapl"]


# ── #364 round-3: hard_stop_pct (asymmetric left-tail cut) ──

def _phase_hs(pct: float) -> CloudProtectiveStop:
    return CloudProtectiveStop(CloudProtectiveStop.Params(hard_stop_pct=pct), logger=None)


def test_hard_stop_tightens_when_cloud_bottom_is_deep() -> None:
    # cloud_bottom 60 (deep, -40%), entry 100, hard 8% → floor = max(60, 92) = 92 (hard stop cuts at -8%).
    aapl = _Sym("AAPL")
    qc = _FakeQC({aapl: {"daily_cloud_bottom": 60.0, "decision_date": "T"}})
    ctx = _ctx(qc, [("aapl", 100.0)])
    _phase_hs(0.08).evaluate(ctx)
    kept = ctx.bar_state.sized_orders
    assert len(kept) == 1 and abs(kept[0].protective_stop - 92.0) < 1e-9


def test_hard_stop_inert_when_cloud_bottom_is_tighter() -> None:
    # cloud_bottom 95 (shallow, -5%), entry 100, hard 8% (=92) → floor = max(95, 92) = 95 (cloud wins).
    aapl = _Sym("AAPL")
    qc = _FakeQC({aapl: {"daily_cloud_bottom": 95.0, "decision_date": "T"}})
    ctx = _ctx(qc, [("aapl", 100.0)])
    _phase_hs(0.08).evaluate(ctx)
    kept = ctx.bar_state.sized_orders
    assert len(kept) == 1 and abs(kept[0].protective_stop - 95.0) < 1e-9


def test_hard_stop_zero_is_byte_unchanged_cloud_bottom() -> None:
    # 0.0 MUST leave the floor at cloud_bottom (the >0 guard — else entry×(1-0)=entry = immediate stop).
    aapl = _Sym("AAPL")
    qc = _FakeQC({aapl: {"daily_cloud_bottom": 90.0, "decision_date": "T"}})
    ctx = _ctx(qc, [("aapl", 100.0)])
    _phase_hs(0.0).evaluate(ctx)
    assert ctx.bar_state.sized_orders[0].protective_stop == 90.0
