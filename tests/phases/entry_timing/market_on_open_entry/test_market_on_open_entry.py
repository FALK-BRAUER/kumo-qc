"""Behavioral tests for the MarketOnOpenEntry entry_timing baseline (#253).

The baseline is a pass-through that stages every sized/confirmed candidate as market-on-open
and stamps provenance. Tests: confirmed candidates -> staged (order emitted intent), none ->
none, never blocks, the order_type fact, determinism, empty space().
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from engine.context import OrderIntent, PhaseContext
from phases.entry_timing.market_on_open_entry.market_on_open_entry import MarketOnOpenEntry


def _ctx(intents: list[OrderIntent]) -> PhaseContext:
    ctx = PhaseContext(qc=object(), time=datetime(2025, 6, 2), data=None)
    ctx.bar_state.sized_orders = intents
    return ctx


def _intent(ticker: str) -> OrderIntent:
    return OrderIntent(
        ticker=ticker, qty=0, price=10.0, stop=0.0, module="signal.bct_score_full", risk_dollars=0.0
    )


def _phase() -> MarketOnOpenEntry:
    return MarketOnOpenEntry(MarketOnOpenEntry.Params(), logger=None)


def test_fire_stages_each_candidate() -> None:
    ctx = _ctx([_intent("AAPL"), _intent("MSFT")])
    res = _phase().evaluate(ctx)
    assert len(ctx.bar_state.sized_orders) == 2
    assert res.facts["staged"] == 2
    assert res.facts["order_type"] == "market_on_open"


def test_fire_stamps_timing_provenance() -> None:
    ctx = _ctx([_intent("AAPL")])
    _phase().evaluate(ctx)
    assert ctx.bar_state.sized_orders[0].module.endswith("entry_timing.market_on_open_entry")


def test_decline_no_candidates_emits_nothing() -> None:
    ctx = _ctx([])
    res = _phase().evaluate(ctx)
    assert ctx.bar_state.sized_orders == []
    assert res.facts["staged"] == 0


def test_preserves_qty_and_price() -> None:
    # baseline rewrites NOTHING about qty/price (MOO uses the open as the fill reference).
    intent = _intent("AAPL")
    ctx = _ctx([intent])
    _phase().evaluate(ctx)
    out = ctx.bar_state.sized_orders[0]
    assert out.qty == intent.qty and out.price == intent.price and out.stop == intent.stop


def test_never_blocks() -> None:
    assert _phase().evaluate(_ctx([_intent("AAPL")])).blocked is False


def test_space_is_empty_baseline() -> None:
    space = MarketOnOpenEntry.Params.space()
    assert space.axes == {}
    assert space.grid_size == 1
    assert space.free_param_count == 0


def test_complexity_matches_space() -> None:
    MarketOnOpenEntry.COMPLEXITY.validate(MarketOnOpenEntry.Params.space())  # must not raise
    assert MarketOnOpenEntry.COMPLEXITY.free_params == 0


def test_version_marker() -> None:
    assert _phase().version_marker == "market_on_open_entry_v1"


def test_deterministic() -> None:
    a = _phase().evaluate(_ctx([_intent("AAPL")])).facts["staged"]
    b = _phase().evaluate(_ctx([_intent("AAPL")])).facts["staged"]
    assert a == b == 1
