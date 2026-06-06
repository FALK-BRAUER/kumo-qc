"""CompositeRanking: deterministic multi-factor ordering."""
from datetime import datetime

from engine.context import OrderIntent, PhaseContext
from phases.ranking.composite_ranking.composite_ranking import CompositeRanking


class _QC:
    def __init__(self) -> None:
        self._composite_score = {}
        self._momentum_20d = {}
        self._trailing_dv = {}
        self._volatility = {}
        self._active = set()


def _intent(ticker: str) -> OrderIntent:
    return OrderIntent(ticker=ticker, qty=0, price=100.0, stop=0.0, module="signal", risk_dollars=0.0)


def _run(qc: _QC, tickers: list[str]) -> list[str]:
    ctx = PhaseContext(qc=qc, time=datetime(2025, 1, 2), data=None)
    ctx.bar_state.sized_orders = [_intent(t) for t in tickers]
    CompositeRanking(CompositeRanking.Params(), logger=None).evaluate(ctx)
    return [o.ticker for o in ctx.bar_state.sized_orders]


def test_override_score_orders_descending() -> None:
    qc = _QC()
    qc._composite_score = {"AAA": 1.0, "BBB": 5.0, "CCC": 3.0}
    assert _run(qc, ["AAA", "BBB", "CCC"]) == ["BBB", "CCC", "AAA"]


def test_ticker_tiebreak_is_deterministic() -> None:
    qc = _QC()
    qc._composite_score = {"AAA": 2.0, "BBB": 2.0}
    assert _run(qc, ["BBB", "AAA"]) == ["AAA", "BBB"]


def test_fallback_rewards_momentum_and_penalizes_volatility() -> None:
    qc = _QC()
    qc._momentum_20d = {"AAA": 0.02, "BBB": 0.20}
    qc._volatility = {"AAA": 0.01, "BBB": 0.01}
    assert _run(qc, ["AAA", "BBB"]) == ["BBB", "AAA"]
