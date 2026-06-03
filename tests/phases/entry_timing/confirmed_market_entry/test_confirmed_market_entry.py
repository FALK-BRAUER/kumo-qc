"""#276b-1 — ConfirmedMarketEntry: stamp order_type=market on the confirmed survivors.

#244 FIRE + DECLINE. FIRE: a confirmed candidate (the only thing entry_selection leaves in
sized_orders) gets order_type="market" + a provenance stamp, qty untouched (sizing owns qty).
DECLINE: an empty tick (all unconfirmed → already dropped upstream) produces no market intent.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from engine.context import OrderIntent, PhaseContext
from phases.entry_timing.confirmed_market_entry.confirmed_market_entry import ConfirmedMarketEntry


def _phase() -> ConfirmedMarketEntry:
    return ConfirmedMarketEntry(ConfirmedMarketEntry.Params(), logger=None)


def _ctx(tickers: list[str], qty: int = 0) -> PhaseContext:
    c = PhaseContext(qc=object(), time=datetime(2025, 2, 4), data=None)
    c.bar_state.sized_orders = [
        OrderIntent(ticker=t, qty=qty, price=0.0, stop=0.0, module="signal", risk_dollars=0.0)
        for t in tickers
    ]
    return c


def test_confirmed_candidate_gets_market_order_type() -> None:
    c = _ctx(["aapl", "tsla"])
    res = _phase().evaluate(c)
    assert all(i.order_type == "market" for i in c.bar_state.sized_orders)
    assert res.facts["market_intents"] == 2


def test_provenance_stamped() -> None:
    c = _ctx(["aapl"])
    _phase().evaluate(c)
    assert c.bar_state.sized_orders[0].module.endswith("entry_timing.confirmed_market_entry")


def test_qty_untouched_sizing_owns_it() -> None:
    # entry_timing sets TYPE, never qty — the stub stays qty=0 until sizing (FIRE_ENTRIES qty>0 guard).
    c = _ctx(["aapl"], qty=0)
    _phase().evaluate(c)
    assert c.bar_state.sized_orders[0].qty == 0
    assert c.bar_state.sized_orders[0].order_type == "market"


def test_empty_tick_produces_no_market_intent() -> None:
    c = _ctx([])
    res = _phase().evaluate(c)
    assert c.bar_state.sized_orders == []
    assert res.facts["market_intents"] == 0


def test_never_blocks_the_bar() -> None:
    assert _phase().evaluate(_ctx(["aapl"])).blocked is False


def test_intraday_clock_and_no_swept_axes() -> None:
    assert ConfirmedMarketEntry.PHASE_RESOLUTION == "intraday"
    assert ConfirmedMarketEntry.Params.space().axes == {}
    assert ConfirmedMarketEntry.COMPLEXITY.free_params == 0
