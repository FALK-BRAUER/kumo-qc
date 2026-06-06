"""ScoreDvRanking: orders sized_orders by trailing $-vol descending; missing DV → 0 (last)."""
from datetime import datetime
from engine.context import PhaseContext, OrderIntent
from phases.ranking.score_dv_ranking.score_dv_ranking import ScoreDvRanking


class _QC:
    def __init__(self, dv): self._trailing_dv = dv


def _i(t): return OrderIntent(ticker=t, qty=0, price=100.0, stop=0.0, module="s", risk_dollars=0.0)


def _run(tickers, dv):
    p = ScoreDvRanking(ScoreDvRanking.Params(), logger=None)
    ctx = PhaseContext(qc=_QC(dv), time=datetime(2025, 1, 2), data=None)
    ctx.bar_state.sized_orders = [_i(t) for t in tickers]
    p.evaluate(ctx)
    return [o.ticker for o in ctx.bar_state.sized_orders]


def test_orders_by_dv_desc():
    assert _run(["a", "b", "c"], {"a": 1e6, "b": 9e6, "c": 5e6}) == ["b", "c", "a"]


def test_missing_dv_sorts_last():
    assert _run(["x", "y"], {"y": 1e6}) == ["y", "x"]  # x has no DV → 0 → last


def test_shuffle_same_order_determinism():
    dv = {"a": 3.0, "b": 2.0, "c": 1.0}
    assert _run(["c", "a", "b"], dv) == _run(["b", "c", "a"], dv) == ["a", "b", "c"]
