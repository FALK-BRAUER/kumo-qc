"""RiskRewardFilter: rejects low reward/risk candidates, keeps missing refs fail-open."""
from datetime import datetime

from engine.context import OrderIntent, PhaseContext
from phases.entry_selection.risk_reward_filter.risk_reward_filter import RiskRewardFilter


class _QC:
    def __init__(self) -> None:
        self._entry_targets = {}
        self._entry_stops = {}


def _intent(ticker: str, price: float = 100.0) -> OrderIntent:
    return OrderIntent(ticker=ticker, qty=0, price=price, stop=0.0, module="signal", risk_dollars=0.0)


def _run(qc: _QC, intents: list[OrderIntent], min_rr: float = 2.0) -> list[str]:
    ctx = PhaseContext(qc=qc, time=datetime(2025, 1, 2), data=None)
    ctx.bar_state.sized_orders = intents
    RiskRewardFilter(RiskRewardFilter.Params(min_rr=min_rr), logger=None).evaluate(ctx)
    return [o.ticker for o in ctx.bar_state.sized_orders]


def test_keeps_candidate_at_or_above_min_rr() -> None:
    qc = _QC()
    qc._entry_targets = {"AAA": 120.0}
    qc._entry_stops = {"AAA": 90.0}
    assert _run(qc, [_intent("AAA")]) == ["AAA"]


def test_rejects_low_rr_candidate() -> None:
    qc = _QC()
    qc._entry_targets = {"AAA": 110.0}
    qc._entry_stops = {"AAA": 90.0}
    assert _run(qc, [_intent("AAA")]) == []


def test_missing_reference_keeps_candidate() -> None:
    assert _run(_QC(), [_intent("AAA")]) == ["AAA"]
