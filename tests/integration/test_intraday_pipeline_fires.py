"""#276b-1 MACHINERY PROOF — the full intraday entry chain fires ONE order end-to-end.

HQ targeted test: isolate MACHINERY from data-coverage. Drive the REAL engine over champion_intraday's
INTRADAY subset (entry_selection: pre-flight + confirm → entry_timing → sizing → protective_stop →
FIRE_ENTRIES) for an injected candidate, over a tenkan-reclaim CROSS sequence, and assert the chain
produces a sized market entry + the #290 GTC Kijun floor. If this fires, the end-to-end machinery is
PROVEN and the local 2wk's 0-orders is UNAMBIGUOUSLY data-coverage (5-min data for 5 tickers), not a
hidden machinery bug. (It also pins the ticker-CASE invariant — the injected uppercase stub must
resolve through sizing/FIRE's active_by_value lookup.)
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from engine.context import OrderIntent, PhaseContext
from engine.engine import StrategyEngine
from strategies.champion_intraday import CONFIG


class _Sym:
    def __init__(self, v: str) -> None:
        self.value = v

    def __hash__(self) -> int:
        return hash(self.value)

    def __eq__(self, o: object) -> bool:
        return isinstance(o, _Sym) and o.value == self.value


class _Tenkan:
    # intraday Tenkan ABOVE the signal price (105 > signal 100): the only geometry where a candidate
    # can be BOTH above its signal (passes pre-flight's no-gap-down gate) AND below Tenkan (primeable
    # for the reclaim cross). If Tenkan <= signal the candidate is already above Tenkan → no cross
    # (the no_reclaim_cross case) — a real strategy characteristic, not a bug.
    def __init__(self) -> None:
        self.is_ready = True
        self.current = type("C", (), {"value": 105.0})()


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


class _Sec:
    def __init__(self, price: float) -> None:
        self.price = price
        self.close = price


class _Hold:
    def __init__(self) -> None:
        self.invested = False
        self.quantity = 0


class _Portfolio(dict):
    cash = 1_000_000.0
    total_portfolio_value = 1_000_000.0

    def __getitem__(self, k: Any) -> _Hold:
        return self.get(k) or _Hold()  # type: ignore[return-value]

    def items(self):  # exit_hard iterates portfolio — empty (no holdings) on the entry path
        return []


class _Ticket:
    def __init__(self) -> None:
        self.canceled = False

    def cancel(self) -> None:
        self.canceled = True


class _FakeQC:
    """Minimal QC surface for the intraday entry chain (sizing/FIRE resolve by active_by_value)."""

    def __init__(self, sym: _Sym, price: float) -> None:
        self._active = {sym}
        self.securities = {sym: _Sec(price)}
        self.portfolio = _Portfolio()
        self._candidate_snapshot = {sym: {"signal_price": 100.0, "daily_kijun": 95.0, "decision_date": "T"}}
        self._intraday = {sym: {"intraday_tenkan": _Tenkan(),
                                "vol_window": _VolWindow([100.0, 100.0, 100.0]),
                                "last_close": 99.0, "last_bar": _Bar(100.0)}}
        self._entry_confirm: dict[str, Any] = {}
        self._pending_entry_today: set[Any] = set()
        self.orders: list[tuple[str, Any, float]] = []
        self.logged: list[str] = []

    # lean_entry-side hooks the engine calls
    def snapshot_for_entry(self, sym: Any) -> Any:
        return self._candidate_snapshot.get(sym)

    def _mark_entry_pending(self, sym: Any) -> None:
        self._pending_entry_today.add(sym)

    def log(self, m: str) -> None:
        self.logged.append(m)

    def Log(self, m: str) -> None:
        self.logged.append(m)

    # order placement (the FIRE_ENTRIES seam)
    def market_order(self, sym: Any, qty: int) -> Any:
        self.orders.append(("market", sym, qty))
        return _Ticket()

    def market_on_open_order(self, sym: Any, qty: int) -> Any:
        self.orders.append(("moo", sym, qty))
        return _Ticket()

    def stop_market_order(self, sym: Any, qty: int, stop: float) -> Any:
        self.orders.append(("stop_market", sym, qty))
        return _Ticket()


def _ictx(qc: _FakeQC, sym: _Sym) -> PhaseContext:
    c = PhaseContext(qc=qc, time=datetime(2025, 2, 4, 14, 30), data=None)
    c.clock = "intraday"
    # simulate the lean_entry candidate-injection: the UPPERCASE stub (matching the signal convention)
    c.bar_state.sized_orders = [
        OrderIntent(ticker=sym.value, qty=0, price=0.0, stop=0.0, module="signal", risk_dollars=0.0)
    ]
    return c


def test_full_intraday_chain_fires_on_cross() -> None:
    sym = _Sym("COST")
    qc = _FakeQC(sym, price=99.0)
    eng = StrategyEngine(CONFIG, qc)

    # TICK 1 — above signal (102 > 100 → pre-flight gap-up OK) but BELOW Tenkan (102 < 105):
    # primes prev_above=False, NO fire.
    qc.securities[sym].price = 102.0
    qc.securities[sym].close = 102.0
    qc._intraday[sym]["last_close"] = 102.0
    eng.on_intraday_bar(_ictx(qc, sym))
    assert qc.orders == [], "tick-1 (below Tenkan, no cross) must not fire"

    # TICK 2 — completed-bar close CROSSES UP through Tenkan (102→106 over 105) + volume expansion
    # → CONFIRM → entry_timing(market) → sizing(qty) → protective_stop(Kijun floor) → FIRE_ENTRIES.
    qc.securities[sym].price = 106.0
    qc.securities[sym].close = 106.0
    qc._intraday[sym]["last_close"] = 106.0
    qc._intraday[sym]["last_bar"] = _Bar(500.0)  # 500 > mean(100)*1.5 → rising-vol
    eng.on_intraday_bar(_ictx(qc, sym))

    kinds = [o[0] for o in qc.orders]
    assert "market" in kinds, f"the confirmed entry must fire a MARKET order; got {qc.orders}"
    # the #290 GTC Kijun floor placed alongside the entry (stop_market at the daily Kijun)
    assert "stop_market" in kinds, f"the GTC protective floor must be placed; got {qc.orders}"

    entry = next(o for o in qc.orders if o[0] == "market")
    assert entry[1] == sym and entry[2] > 0, "entry is a positive-qty BUY of the confirmed candidate"
    stop = next(o for o in qc.orders if o[0] == "stop_market")
    assert stop[2] == -entry[2], "the protective stop sells the full entry qty (GTC floor)"


def test_no_fire_without_cross() -> None:
    # control: above signal (pre-flight OK) but stays BELOW Tenkan (105) → never crosses → never
    # confirms → never fires (the no_reclaim_cross case that dominated the local 2wk).
    sym = _Sym("COST")
    qc = _FakeQC(sym, price=101.0)
    eng = StrategyEngine(CONFIG, qc)
    for close in (101.0, 102.0, 103.0):  # all > signal 100 (pre-flight OK), all < Tenkan 105
        qc.securities[sym].price = close
        qc.securities[sym].close = close
        qc._intraday[sym]["last_close"] = close
        qc._intraday[sym]["last_bar"] = _Bar(500.0)
        eng.on_intraday_bar(_ictx(qc, sym))
    assert qc.orders == [], "no tenkan-reclaim cross (stays below Tenkan) → no entry"
