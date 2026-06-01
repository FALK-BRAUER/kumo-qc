"""#276a — the fire-seam order_type dispatch + #290 GTC protective stop + cancel-on-exit.

SAFETY-CRITICAL (real-money path). The load-bearing tests:
- order_type dispatches to the right broker call (market_on_open default = behaviour-unchanged).
- the GTC protective stop is placed on entry (when protective_stop>0), NOT when 0.
- CANCEL-ON-EXIT: the resting GTC stop is cancelled on EVERY runtime-exit fill path → no orphan
  double-sell (HQ's hardest-hunted bug).
Each raise/behaviour paired with a control (mutation-bite).
"""
from __future__ import annotations

from datetime import datetime

import pytest

from engine.base import ConfigError
from engine.config import Slot, StrategyConfig
from engine.context import OrderIntent, PhaseContext
from engine.engine import FIRE_ENTRIES, FIRE_EXITS, StrategyEngine
from tests.harness.stub_phases import slot


class FakeTicket:
    def __init__(self) -> None:
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


class FakeSec:
    def __init__(self, price: float) -> None:
        self.price = price


class FakeSecurities:
    def __init__(self, price: float = 100.0) -> None:
        self._price = price

    def __getitem__(self, sym: object) -> FakeSec:
        return FakeSec(self._price)


class FakeSym:
    def __init__(self, v: str) -> None:
        self.value = v

    def __hash__(self) -> int:
        return hash(self.value)

    def __eq__(self, o: object) -> bool:
        return isinstance(o, FakeSym) and o.value == self.value


class FakeQC:
    """Records every broker call so the fire-seam dispatch + GTC + cancel are assertable."""
    def __init__(self) -> None:
        self.securities = FakeSecurities()
        self.calls: list[tuple] = []
        self._tickets: list[FakeTicket] = []
        self._position_meta: dict = {}
        self._active: set = set()

    def Log(self, m: str) -> None: ...
    def log(self, m: str) -> None: ...

    def market_on_open_order(self, sym, qty):
        self.calls.append(("moo", sym.value, qty)); return FakeTicket()

    def market_order(self, sym, qty):
        self.calls.append(("market", sym.value, qty)); return FakeTicket()

    def limit_order(self, sym, qty, price):
        self.calls.append(("limit", sym.value, qty, price)); return FakeTicket()

    def stop_market_order(self, sym, qty, stop):
        self.calls.append(("stop_market", sym.value, qty, stop))
        t = FakeTicket(); self._tickets.append(t); return t


def _engine(qc: FakeQC) -> StrategyEngine:
    # a fixture stack (is_fixture passes the #272 gate); we drive _fire directly.
    cfg = StrategyConfig(name="t", version="1.0.0", is_fixture=True, phases={
        "universe": slot("universe"), "signal": slot("signal"), "sizing": slot("sizing"),
    })
    return StrategyEngine(config=cfg, qc=qc)


def _ctx(qc: FakeQC) -> PhaseContext:
    return PhaseContext(qc=qc, time=datetime(2025, 1, 2), data=None)


def _intent(ticker: str, qty: int = 10, order_type: str = "market_on_open",
            protective_stop: float = 0.0, stop: float = 0.0, price: float = 100.0) -> OrderIntent:
    return OrderIntent(ticker=ticker, qty=qty, price=price, stop=stop, module="t",
                       risk_dollars=0.0, order_type=order_type, protective_stop=protective_stop)


# ── order_type dispatch ──

def test_default_order_type_is_market_on_open() -> None:
    qc = FakeQC(); eng = _engine(qc); sym = FakeSym("AAPL"); qc._active = {sym}
    ctx = _ctx(qc); ctx.bar_state.sized_orders = [_intent("AAPL")]
    eng._fire(FIRE_ENTRIES, ctx)
    assert ("moo", "AAPL", 10) in qc.calls, "default order_type must dispatch market_on_open"


def test_order_type_market_dispatches_market_order() -> None:
    qc = FakeQC(); eng = _engine(qc); sym = FakeSym("AAPL"); qc._active = {sym}
    ctx = _ctx(qc); ctx.bar_state.sized_orders = [_intent("AAPL", order_type="market")]
    eng._fire(FIRE_ENTRIES, ctx)
    assert ("market", "AAPL", 10) in qc.calls and not any(c[0] == "moo" for c in qc.calls)


def test_unknown_order_type_raises() -> None:
    qc = FakeQC(); eng = _engine(qc); sym = FakeSym("AAPL"); qc._active = {sym}
    ctx = _ctx(qc); ctx.bar_state.sized_orders = [_intent("AAPL", order_type="teleport")]
    with pytest.raises(ConfigError, match="unknown OrderIntent.order_type"):
        eng._fire(FIRE_ENTRIES, ctx)


# ── #290 GTC protective stop ──

def test_protective_stop_placed_on_entry() -> None:
    qc = FakeQC(); eng = _engine(qc); sym = FakeSym("AAPL"); qc._active = {sym}
    ctx = _ctx(qc); ctx.bar_state.sized_orders = [_intent("AAPL", qty=10, protective_stop=90.0)]
    eng._fire(FIRE_ENTRIES, ctx)
    # the entry + a resting sell-stop at 90 for -10 (the catastrophic floor)
    assert ("stop_market", "AAPL", -10, 90.0) in qc.calls
    assert qc._position_meta[sym].get("protective_stop_ticket") is not None


def test_no_protective_stop_when_zero() -> None:
    # MUTATION-BITE control: protective_stop=0 → NO resting stop placed.
    qc = FakeQC(); eng = _engine(qc); sym = FakeSym("AAPL"); qc._active = {sym}
    ctx = _ctx(qc); ctx.bar_state.sized_orders = [_intent("AAPL", protective_stop=0.0)]
    eng._fire(FIRE_ENTRIES, ctx)
    assert not any(c[0] == "stop_market" for c in qc.calls)
    assert "protective_stop_ticket" not in qc._position_meta[sym]


# ── CANCEL-ON-EXIT (the hardest-hunted: no orphan double-sell) ──

def test_protective_stop_cancelled_on_runtime_exit() -> None:
    qc = FakeQC(); eng = _engine(qc); sym = FakeSym("AAPL"); qc._active = {sym}
    # enter with a protective stop
    ctx = _ctx(qc); ctx.bar_state.sized_orders = [_intent("AAPL", qty=10, protective_stop=90.0)]
    eng._fire(FIRE_ENTRIES, ctx)
    ticket = qc._position_meta[sym]["protective_stop_ticket"]
    assert ticket.cancelled is False
    # now the runtime exits the position → the resting GTC stop MUST be cancelled (no orphan)
    ctx2 = _ctx(qc); ctx2.bar_state.exit_intents = [_intent("AAPL", qty=-10)]
    eng._fire(FIRE_EXITS, ctx2)
    assert ticket.cancelled is True, "ORPHAN: protective stop NOT cancelled on runtime exit → double-sell risk"
    assert sym not in qc._position_meta  # meta cleared on exit


def test_exit_without_protective_stop_is_clean() -> None:
    # control: exiting a position that had NO protective stop → no crash, no spurious cancel.
    qc = FakeQC(); eng = _engine(qc); sym = FakeSym("AAPL"); qc._active = {sym}
    ctx = _ctx(qc); ctx.bar_state.sized_orders = [_intent("AAPL", protective_stop=0.0)]
    eng._fire(FIRE_ENTRIES, ctx)
    ctx2 = _ctx(qc); ctx2.bar_state.exit_intents = [_intent("AAPL", qty=-10)]
    eng._fire(FIRE_EXITS, ctx2)  # must not raise
    assert sym not in qc._position_meta


# ── #276a fail-loud GUARDS (HQ ruling A): trim/add/re-entry + live protective stop → RAISE ──
# (latent footguns until #276b's cancel-replace lifecycle; the guard FORCES that lifecycle to be
#  built before the combo is reachable. Each guard mutation-bites: remove it → over-sell runs.)

from engine.base import DegradedConfigError  # noqa: E402
from engine.engine import FIRE_ADDS, FIRE_TRIMS  # noqa: E402


def _entry_with_stop(eng, qc, sym, qty=10, stop=90.0):
    qc._active = {sym}
    ctx = _ctx(qc); ctx.bar_state.sized_orders = [_intent(sym.value, qty=qty, protective_stop=stop)]
    eng._fire(FIRE_ENTRIES, ctx)
    assert qc._position_meta[sym].get("protective_stop_ticket") is not None  # live stop


def test_guard_trim_with_live_protective_stop_raises() -> None:
    # GUARD-1: a trim on a position with a live protective stop → RAISE (would over-sell long→short).
    qc = FakeQC(); eng = _engine(qc); sym = FakeSym("AAPL")
    _entry_with_stop(eng, qc, sym)
    ctx = _ctx(qc); ctx.bar_state.trim_intents = [_intent("AAPL", qty=-4)]
    with pytest.raises(DegradedConfigError, match="trim on AAPL with a LIVE protective stop"):
        eng._fire(FIRE_TRIMS, ctx)


def test_guard_add_with_live_protective_stop_raises() -> None:
    # GUARD-2: an add on a position with a live protective stop → RAISE (added shares unprotected).
    qc = FakeQC(); eng = _engine(qc); sym = FakeSym("AAPL")
    _entry_with_stop(eng, qc, sym)
    ctx = _ctx(qc); ctx.bar_state.add_intents = [_intent("AAPL", qty=5)]
    with pytest.raises(DegradedConfigError, match="add on AAPL with a LIVE protective stop"):
        eng._fire(FIRE_ADDS, ctx)


def test_guard_reentry_with_live_protective_stop_raises() -> None:
    # GUARD-3: a re-entry on a symbol with a live protective stop → RAISE (orphans the prior stop).
    qc = FakeQC(); eng = _engine(qc); sym = FakeSym("AAPL")
    _entry_with_stop(eng, qc, sym)
    ctx = _ctx(qc); ctx.bar_state.sized_orders = [_intent("AAPL", qty=10, protective_stop=90.0)]
    with pytest.raises(DegradedConfigError, match="re-entry on AAPL with a LIVE protective stop"):
        eng._fire(FIRE_ENTRIES, ctx)


def test_guards_dormant_without_protective_stop() -> None:
    # CONTROL (mutation-bite anchor): NO protective stop → trim/add/re-entry are ALLOWED (the
    # guards fire ONLY when a live stop exists; the champion's no-stop path is unaffected).
    qc = FakeQC(); eng = _engine(qc); sym = FakeSym("AAPL"); qc._active = {sym}
    ctx = _ctx(qc); ctx.bar_state.sized_orders = [_intent("AAPL", qty=10, protective_stop=0.0)]
    eng._fire(FIRE_ENTRIES, ctx)  # no stop
    ctx2 = _ctx(qc); ctx2.bar_state.trim_intents = [_intent("AAPL", qty=-4)]
    eng._fire(FIRE_TRIMS, ctx2)  # must NOT raise (no live stop → no footgun)
    ctx3 = _ctx(qc); ctx3.bar_state.add_intents = [_intent("AAPL", qty=5)]
    eng._fire(FIRE_ADDS, ctx3)  # must NOT raise
