"""StubIntradaySizer (M1) — sizes the entry_trigger fired stubs AT THE FIRE PRICE (flat %), clamped to
gross headroom. Constructor: (Params(...), logger=None)."""
from datetime import datetime
from engine.context import PhaseContext, OrderIntent
from phases.intraday_sizing.stub_intraday_sizer.stub_intraday_sizer import StubIntradaySizer


class _PF:
    def __init__(self, tpv=100000.0, held=0.0): self.total_portfolio_value = tpv; self.total_holdings_value = held


class _QC:
    def __init__(self, tpv=100000.0, held=0.0): self.portfolio = _PF(tpv, held)


def _run(qc, stubs, **kw):
    p = StubIntradaySizer(StubIntradaySizer.Params(**kw), logger=None)
    ctx = PhaseContext(qc=qc, time=datetime(2025, 1, 3, 11, 0), data=None)
    ctx.bar_state.sized_orders = [OrderIntent(ticker=t, qty=0, price=px, stop=0.0, module="trig", risk_dollars=0.0, order_type="market") for t, px in stubs]
    p.evaluate(ctx)
    return ctx.bar_state.sized_orders


def test_sizes_at_fire_price():
    # position_pct 0.05 of 100k = 5k; price 100 → qty 50.
    qc = _QC(tpv=100000.0)
    out = _run(qc, [("AAA", 100.0)], position_pct=0.05)
    assert len(out) == 1 and out[0].qty == 50 and out[0].order_type == "market"


def test_gross_headroom_clamp():
    # already 98% invested → only 2k headroom → qty clamped to 2k/100=20, not the 5k flat.
    qc = _QC(tpv=100000.0, held=98000.0)
    out = _run(qc, [("AAA", 100.0)], position_pct=0.05, max_gross_pct=1.0)
    assert out[0].qty == 20


def test_zero_price_skipped():
    qc = _QC(); assert _run(qc, [("AAA", 0.0)]) == []
