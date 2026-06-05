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
    def __init__(self, quantity: int = 0) -> None:
        self.cancelled = False
        self.quantity = quantity  # #378: the resting stop's covered qty (resized in place)

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


class FakeHolding:
    def __init__(self, quantity: int = 0) -> None:
        self.quantity = quantity
        self.invested = quantity != 0


class FakePortfolio:
    def __init__(self, equity: float = 100_000.0, held: float = 0.0) -> None:
        self.total_portfolio_value = equity
        self.total_holdings_value = held
        self._holdings: dict = {}  # #378 reconcile: per-sym held qty

    def __getitem__(self, sym: object) -> FakeHolding:
        return self._holdings.get(sym, FakeHolding(0))

    def set(self, sym: object, quantity: int) -> None:
        self._holdings[sym] = FakeHolding(quantity)


class FakeQC:
    """Records every broker call so the fire-seam dispatch + GTC + cancel are assertable."""
    def __init__(self) -> None:
        self.securities = FakeSecurities()
        self.calls: list[tuple] = []
        self._tickets: list[FakeTicket] = []
        self._position_meta: dict = {}
        self._active: set = set()
        self.portfolio = FakePortfolio()
        self.update_ok = True          # #378: toggle to simulate a rejected OrderTicket.update
        self.update_calls: list[tuple] = []

    def Log(self, m: str) -> None: ...
    def log(self, m: str) -> None: ...

    def market_on_open_order(self, sym, qty, tag=""):
        self.calls.append(("moo", sym.value, qty)); return FakeTicket(quantity=qty)

    def market_order(self, sym, qty, tag=""):
        self.calls.append(("market", sym.value, qty)); return FakeTicket(quantity=qty)

    def limit_order(self, sym, qty, price, tag=""):
        self.calls.append(("limit", sym.value, qty, price)); return FakeTicket(quantity=qty)

    def stop_market_order(self, sym, qty, stop, tag=""):
        self.calls.append(("stop_market", sym.value, qty, stop))
        t = FakeTicket(quantity=qty); self._tickets.append(t); return t

    def update_order_quantity(self, ticket, new_qty) -> bool:
        # #378 hook the engine calls to atomically resize the resting stop in place. Mirrors the
        # runtime impl's contract (returns OrderResponse.is_success). Applies the new qty on success.
        self.update_calls.append((ticket, new_qty))
        if self.update_ok:
            ticket.quantity = new_qty
        return self.update_ok


class FakeQCNoResize(FakeQC):
    """#378: a qc WITHOUT the resize lifecycle wired (the hook absent) → an add onto a stop-protected
    position must FAIL LOUD (the #276a guard's reason stands)."""
    update_order_quantity = None  # type: ignore[assignment]


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


def test_fire_exits_dedups_same_symbol_no_oversell() -> None:
    # OVER-SELL GUARD (#339-RUN1 review): >1 exit phase (CloudAdherenceTrail + a loser-exit) can emit
    # an exit_intent for the SAME sym the same bar. The engine must fire EXACTLY ONE sell — a second
    # -qty submit on an already-closing position → over-sell → flips long→short (catastrophic).
    qc = FakeQC(); eng = _engine(qc); sym = FakeSym("AAPL"); qc._active = {sym}
    ctx = _ctx(qc)
    ctx.bar_state.exit_intents = [_intent("AAPL", qty=-10), _intent("AAPL", qty=-10)]
    eng._fire(FIRE_EXITS, ctx)
    moo_sells = [c for c in qc.calls if c[0] == "moo" and c[1] == "AAPL"]
    assert eng._fired_exits == 1 and len(moo_sells) == 1, "exactly ONE exit per sym/bar — no over-sell"


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


def test_guard_trim_with_live_protective_stop_raises_when_unwired() -> None:
    # #379: a trim on a stop-protected position with the resize lifecycle UNWIRED → RAISE (a full-qty
    # stop on a trimmed position over-sells long→short). When WIRED it resizes instead
    # (test_379_trim_resizes_stop_down_then_fires). The guard fires only when the lifecycle is absent.
    qc = FakeQCNoResize(); eng = _engine(qc); sym = FakeSym("AAPL")
    _entry_with_stop(eng, qc, sym)
    ctx = _ctx(qc); ctx.bar_state.trim_intents = [_intent("AAPL", qty=-4)]
    with pytest.raises(DegradedConfigError, match="stop-resize lifecycle .* is NOT wired"):
        eng._fire(FIRE_TRIMS, ctx)


# ── #378 floor-safe pyramid: add onto a stop-protected position RESIZES the stop (not raises) ──
# Falk's integration-test rule: exercise the add through the REAL engine + the live protective-stop
# lifecycle (a resting stop present at orig qty — the exact S1 condition that broke the prover), NOT
# an isolated mock. Each test asserts the FLOOR INVARIANT: held shares are never left uncovered.

def test_378_add_with_live_stop_resizes_then_fires() -> None:
    # THE mandated integration test: an add onto a position carrying a CloudProtectiveStop @orig qty
    # → the stop is atomically grown to (orig+add) FIRST, THEN the add fires. No raise.
    qc = FakeQC(); eng = _engine(qc); sym = FakeSym("AAPL")
    _entry_with_stop(eng, qc, sym, qty=10)          # held 10, resting stop covers -10
    ticket = qc._position_meta[sym]["protective_stop_ticket"]
    ctx = _ctx(qc); ctx.bar_state.add_intents = [_intent("AAPL", qty=5)]
    eng._fire(FIRE_ADDS, ctx)
    assert (ticket, -15) in qc.update_calls, "stop must be resized to cover orig+add (-15) before the add"
    assert qc._position_meta[sym]["protective_stop_qty"] == -15
    assert ticket.quantity == -15, "the resting stop's qty grew in place (atomic update, no cancel-replace)"
    assert ("moo", "AAPL", 5) in qc.calls and eng._fired_adds == 1, "the add fires AFTER the resize"


def test_378_add_skipped_when_resize_fails_no_gap() -> None:
    # TEETH: the resize is REJECTED (OrderResponse not success) → the add is SKIPPED, the stop stays at
    # orig → at no instant are held shares left without a covering stop.
    qc = FakeQC(); qc.update_ok = False; eng = _engine(qc); sym = FakeSym("AAPL")
    _entry_with_stop(eng, qc, sym, qty=10)
    ctx = _ctx(qc); ctx.bar_state.add_intents = [_intent("AAPL", qty=5)]
    eng._fire(FIRE_ADDS, ctx)
    assert eng._fired_adds == 0 and not any(c == ("moo", "AAPL", 5) for c in qc.calls), "add must NOT fire"
    assert qc._position_meta[sym]["protective_stop_qty"] == -10, "stop stays at orig (still covers held 10)"


def test_378_add_with_stop_but_resize_unwired_raises() -> None:
    # the #276a guard's reason still stands when the resize LIFECYCLE is absent: an add onto a
    # stop-protected position with no qc.update_order_quantity hook → RAISE (would under-size the stop).
    qc = FakeQCNoResize(); eng = _engine(qc); sym = FakeSym("AAPL")
    _entry_with_stop(eng, qc, sym, qty=10)
    ctx = _ctx(qc); ctx.bar_state.add_intents = [_intent("AAPL", qty=5)]
    with pytest.raises(DegradedConfigError, match="stop-resize lifecycle .* is NOT wired"):
        eng._fire(FIRE_ADDS, ctx)


def test_378_reconcile_shrinks_stop_when_add_rejected() -> None:
    # HQ edge: resize pre-grew the stop to (orig+add), but the add then DID NOT fill (reject/halt) →
    # the stop is left over-sized. reconcile (called from on_order_event on the terminal event) must
    # resize it BACK to the actual held qty so a later trigger can't over-sell-to-short.
    qc = FakeQC(); eng = _engine(qc); sym = FakeSym("AAPL")
    _entry_with_stop(eng, qc, sym, qty=10)
    ticket = qc._position_meta[sym]["protective_stop_ticket"]
    qc.portfolio.set(sym, 10)                        # actually held: 10 (the add has not filled yet)
    ctx = _ctx(qc); ctx.bar_state.add_intents = [_intent("AAPL", qty=5)]
    eng._fire(FIRE_ADDS, ctx)                        # stop pre-grown to -15, add submitted
    assert qc._position_meta[sym]["protective_stop_qty"] == -15
    # the add is REJECTED → position stays 10 → reconcile on the terminal event
    eng.reconcile_protective_stop_to_position(qc, sym, "d")
    assert (ticket, -10) in qc.update_calls and qc._position_meta[sym]["protective_stop_qty"] == -10
    assert ticket.quantity == -10, "dangling over-sized stop shrunk back to the held qty"


def test_378_add_raises_when_stop_qty_invariant_missing() -> None:
    # fix #5: a live stop ticket WITHOUT its tracked covered-qty is an invariant break — _resize must
    # FAIL LOUD (never default-0 → never resize the floor to cover only the added shares).
    qc = FakeQC(); eng = _engine(qc); sym = FakeSym("AAPL")
    _entry_with_stop(eng, qc, sym, qty=10)
    del qc._position_meta[sym]["protective_stop_qty"]   # corrupt: ticket present, covered-qty gone
    ctx = _ctx(qc); ctx.bar_state.add_intents = [_intent("AAPL", qty=5)]
    with pytest.raises(DegradedConfigError, match="protective_stop_qty missing"):
        eng._fire(FIRE_ADDS, ctx)


def test_378_reconcile_noop_when_stop_qty_invariant_missing() -> None:
    # fix #5 on the reconcile path (runs in on_order_event) — the same corrupt meta must NOT crash and
    # must NOT resize (don't guess the floor); a safe return.
    qc = FakeQC(); eng = _engine(qc); sym = FakeSym("AAPL")
    _entry_with_stop(eng, qc, sym, qty=10)
    qc.portfolio.set(sym, 10)
    del qc._position_meta[sym]["protective_stop_qty"]
    eng.reconcile_protective_stop_to_position(qc, sym, "d")   # must not raise
    assert qc.update_calls == [], "no resize attempted on a missing-invariant meta"


# ── #379 trim-side floor-lifecycle: resize the stop DOWN on a partial trim (mirror of #378, opposite
# direction) + exit-supersedes-trim over-sell guard. Real-engine harness; floor code = mutation-proven.

def test_379_trim_resizes_stop_down_then_fires() -> None:
    # a partial trim (sell 4 of held 10) → the protective stop SHRINKS -10 → -6 (remaining) FIRST,
    # then the trim fires. The stop is never over-sized → no over-sell.
    qc = FakeQC(); eng = _engine(qc); sym = FakeSym("AAPL")
    _entry_with_stop(eng, qc, sym, qty=10)
    ticket = qc._position_meta[sym]["protective_stop_ticket"]
    ctx = _ctx(qc); ctx.bar_state.trim_intents = [_intent("AAPL", qty=-4)]   # sell 4 (negative)
    eng._fire(FIRE_TRIMS, ctx)
    assert (ticket, -6) in qc.update_calls, "stop must shrink to the remaining qty (-6) before the trim"
    assert qc._position_meta[sym]["protective_stop_qty"] == -6 and ticket.quantity == -6
    assert ("moo", "AAPL", -4) in qc.calls and eng._fired_trims == 1


def test_379_trim_skipped_when_resize_fails_no_oversell() -> None:
    # TEETH: the resize is rejected → the trim is SKIPPED, the stop stays at -10 (still covers held 10,
    # never over-sized). No naked over-sell.
    qc = FakeQC(); qc.update_ok = False; eng = _engine(qc); sym = FakeSym("AAPL")
    _entry_with_stop(eng, qc, sym, qty=10)
    ctx = _ctx(qc); ctx.bar_state.trim_intents = [_intent("AAPL", qty=-4)]
    eng._fire(FIRE_TRIMS, ctx)
    assert eng._fired_trims == 0 and not any(c == ("moo", "AAPL", -4) for c in qc.calls)
    assert qc._position_meta[sym]["protective_stop_qty"] == -10


def test_379_trim_with_stop_but_resize_unwired_raises() -> None:
    qc = FakeQCNoResize(); eng = _engine(qc); sym = FakeSym("AAPL")
    _entry_with_stop(eng, qc, sym, qty=10)
    ctx = _ctx(qc); ctx.bar_state.trim_intents = [_intent("AAPL", qty=-4)]
    with pytest.raises(DegradedConfigError, match="stop-resize lifecycle .* is NOT wired"):
        eng._fire(FIRE_TRIMS, ctx)


def test_379_trim_invariant_refuses_overtrim() -> None:
    # INVARIANT (HQ): the stop must never cover MORE than held. An over-trim (sell 12 of 10) → the new
    # stop qty would cross 0 (-10+12=+2, flip to a buy-stop) → REFUSED, trim NOT fired, stop unchanged.
    qc = FakeQC(); eng = _engine(qc); sym = FakeSym("AAPL")
    _entry_with_stop(eng, qc, sym, qty=10)
    ctx = _ctx(qc); ctx.bar_state.trim_intents = [_intent("AAPL", qty=-12)]
    eng._fire(FIRE_TRIMS, ctx)
    assert eng._fired_trims == 0 and qc._position_meta[sym]["protective_stop_qty"] == -10


def test_379_co_clock_invariant_raises_on_exit_profit_split() -> None:
    # CRITICAL (#379 review): exit_hard (daily) + profit (intraday) = SPLIT clocks → FIRE_EXITS and
    # FIRE_TRIMS land in separate _run_clock calls → `_exited_this_bar` resets between them → the
    # exit-supersedes-trim over-sell guard silently fails. The init invariant must REFUSE the config.
    qc = FakeQC()
    cfg = StrategyConfig(name="t", version="1.0.0", is_fixture=True, phases={
        "universe": slot("universe"), "signal": slot("signal"), "sizing": slot("sizing"),
        "exit_hard": slot("exit_hard", resolution="daily"),
        "profit": slot("profit", resolution="intraday"),
    })
    with pytest.raises(ConfigError, match="exit_hard clock .* != profit clock"):
        StrategyEngine(config=cfg, qc=qc)


def test_379_co_clock_same_clock_ok() -> None:
    # CONTROL: exit_hard + profit BOTH daily (the methodology — EOD-only exits) → no raise.
    qc = FakeQC()
    cfg = StrategyConfig(name="t", version="1.0.0", is_fixture=True, phases={
        "universe": slot("universe"), "signal": slot("signal"), "sizing": slot("sizing"),
        "exit_hard": slot("exit_hard", resolution="daily"),
        "profit": slot("profit", resolution="daily"),
    })
    StrategyEngine(config=cfg, qc=qc)  # must NOT raise


def test_379_trim_full_qty_refused_use_exit() -> None:
    # #379 review bug: a FULL trim (sell all 10 of held 10) → new_qty 0 → REFUSED (a full liquidation
    # is an EXIT — FIRE_EXITS cancels the stop + pops meta; a 0-qty trim would orphan a 0-qty stop +
    # stale meta). Trim NOT fired, stop unchanged.
    qc = FakeQC(); eng = _engine(qc); sym = FakeSym("AAPL")
    _entry_with_stop(eng, qc, sym, qty=10)
    ctx = _ctx(qc); ctx.bar_state.trim_intents = [_intent("AAPL", qty=-10)]
    eng._fire(FIRE_TRIMS, ctx)
    assert eng._fired_trims == 0 and qc._position_meta[sym]["protective_stop_qty"] == -10


def test_379_exit_supersedes_trim_no_double_sell() -> None:
    # GAP-1 (#379 review): a fader BOTH structure-exits AND age-trims the same bar. FIRE_EXITS runs
    # first + fully closes the position; the trim on the gone position would over-sell. Exit supersedes:
    # FIRE_TRIMS skips a sym exited this bar.
    qc = FakeQC(); eng = _engine(qc); sym = FakeSym("AAPL")
    _entry_with_stop(eng, qc, sym, qty=10)
    ctx = _ctx(qc)
    ctx.bar_state.exit_intents = [_intent("AAPL", qty=-10)]
    eng._fire(FIRE_EXITS, ctx)
    assert eng._fired_exits == 1 and sym not in qc._position_meta   # fully exited
    ctx.bar_state.trim_intents = [_intent("AAPL", qty=-4)]
    eng._fire(FIRE_TRIMS, ctx)
    assert eng._fired_trims == 0, "exit supersedes trim — must NOT trim an already-exited position"


def test_378_reconcile_noop_when_add_filled() -> None:
    # CONTROL (mutation-bite): the add DID fill → held becomes 15, stop already -15 → reconcile no-ops
    # (proves the shrink above is the reject path biting, not an always-shrink).
    qc = FakeQC(); eng = _engine(qc); sym = FakeSym("AAPL")
    _entry_with_stop(eng, qc, sym, qty=10)
    ctx = _ctx(qc); ctx.bar_state.add_intents = [_intent("AAPL", qty=5)]
    eng._fire(FIRE_ADDS, ctx)                        # stop -15
    qc.portfolio.set(sym, 15)                        # add filled → held 15
    n_before = len(qc.update_calls)
    eng.reconcile_protective_stop_to_position(qc, sym, "d")
    assert len(qc.update_calls) == n_before, "stop already matches held 15 → no reconcile"
    assert qc._position_meta[sym]["protective_stop_qty"] == -15


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


# ── #181 BUG-2 Stage 0: commit-aware gross cap at the FIRE_ADDS seam (engine wiring) ──

from phases.portfolio_risk.gross_exposure_cap.gross_exposure_cap import GrossExposureCap  # noqa: E402


def _engine_with_cap(qc: FakeQC, max_gross_pct: float = 1.0) -> StrategyEngine:
    eng = _engine(qc)
    eng.phases["portfolio_risk"] = [
        GrossExposureCap(GrossExposureCap.Params(max_gross_pct=max_gross_pct), logger=None)
    ]
    return eng


def test_fire_entries_accumulates_tick_entry_value() -> None:
    # the commit-aware bookkeeping: FIRE_ENTRIES sums |qty|×price of submitted entries this tick.
    qc = FakeQC(); eng = _engine(qc); sym = FakeSym("AAPL"); qc._active = {sym}
    ctx = _ctx(qc); ctx.bar_state.sized_orders = [_intent("AAPL", qty=950)]  # 950×$100 = $95k
    eng._fire(FIRE_ENTRIES, ctx)
    assert eng._tick_entry_value == 95_000.0


def test_commit_aware_seam_denies_add_when_inflight_entry_consumes_budget() -> None:
    # END-TO-END leverage-hole closure (#181 BUG-2): a $95k entry fires this tick (holdings not yet
    # updated → fill lag), then a $10k add. The seam counts the in-flight entry → 0+95k+10k=105k >
    # 100k ceiling → add DENIED. Without the commit-aware seam the add fires uncapped = the hole.
    qc = FakeQC(); eng = _engine_with_cap(qc); sym = FakeSym("AAPL"); qc._active = {sym}
    ctx = _ctx(qc)
    ctx.bar_state.sized_orders = [_intent("AAPL", qty=950)]   # $95k entry, no protective stop
    eng._fire(FIRE_ENTRIES, ctx)
    ctx.bar_state.add_intents = [_intent("AAPL", qty=100)]    # $10k add
    eng._bound_adds_to_gross_cap(ctx)                         # the commit-aware second seam
    assert ctx.bar_state.add_intents == [], "in-flight entry must consume the cap budget → add denied"
    eng._fire(FIRE_ADDS, ctx)
    assert eng._fired_adds == 0, "no add should fire — it breached the gross cap commit-aware"


def test_commit_aware_seam_allows_add_within_budget() -> None:
    # MUTATION-BITE control: a smaller $40k entry leaves room (40k+10k=50k < 100k) → the SAME add
    # passes the seam and fires. Proves the denial above is the cap biting, not an always-deny.
    qc = FakeQC(); eng = _engine_with_cap(qc); sym = FakeSym("AAPL"); qc._active = {sym}
    ctx = _ctx(qc)
    ctx.bar_state.sized_orders = [_intent("AAPL", qty=400)]   # $40k entry
    eng._fire(FIRE_ENTRIES, ctx)
    ctx.bar_state.add_intents = [_intent("AAPL", qty=100)]    # $10k add
    eng._bound_adds_to_gross_cap(ctx)
    assert len(ctx.bar_state.add_intents) == 1
    eng._fire(FIRE_ADDS, ctx)
    assert eng._fired_adds == 1


def test_no_portfolio_risk_phase_means_seam_is_noop() -> None:
    # behaviour-unchanged: with NO portfolio_risk phase wired (the champion_asis fixture), the seam
    # leaves add_intents untouched.
    qc = FakeQC(); eng = _engine(qc); sym = FakeSym("AAPL"); qc._active = {sym}
    ctx = _ctx(qc); ctx.bar_state.add_intents = [_intent("AAPL", qty=100)]
    eng._bound_adds_to_gross_cap(ctx)
    assert len(ctx.bar_state.add_intents) == 1
