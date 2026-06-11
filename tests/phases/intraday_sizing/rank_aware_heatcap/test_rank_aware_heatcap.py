from __future__ import annotations

from datetime import datetime

from engine.context import OrderIntent, PhaseContext
from phases.intraday_sizing.rank_aware_heatcap.rank_aware_heatcap import RankAwareHeatcap


class FakeSymbol:
    def __init__(self, value: str) -> None:
        self.value = value

    def __hash__(self) -> int:
        return hash(self.value)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, FakeSymbol) and self.value == other.value


class FakeSecurity:
    def __init__(self, price: float) -> None:
        self.price = price


class FakePortfolio:
    cash = 100_000.0
    total_portfolio_value = 100_000.0


class FakeQC:
    def __init__(self) -> None:
        self.portfolio = FakePortfolio()
        self.sym = FakeSymbol("AAA")
        self._active = {self.sym}
        self.securities = {self.sym: FakeSecurity(200.0)}
        self._candidate_snapshot = {self.sym: {"scanner_rank": 4}}

    def snapshot_for_entry(self, sym: FakeSymbol) -> dict[str, object] | None:
        return self._candidate_snapshot.get(sym)


def test_intraday_adapter_declares_intraday_sizing_kind() -> None:
    phase = RankAwareHeatcap(RankAwareHeatcap.Params(), logger=None)

    assert phase.PHASE_KIND == "intraday_sizing"
    assert phase.PHASE_RESOLUTION == "intraday"
    assert phase.version_marker == "intraday_rank_aware_heatcap_v1"


def test_sizes_at_fire_price_and_preserves_intent_contract() -> None:
    qc = FakeQC()
    phase = RankAwareHeatcap(
        RankAwareHeatcap.Params(position_pct=0.05, top_multiplier=1.25),
        logger=None,
    )
    ctx = PhaseContext(qc=qc, time=datetime(2025, 1, 2, 10, 0), data=None, clock="intraday")
    ctx.bar_state.sized_orders = [
        OrderIntent(
            ticker="AAA",
            qty=0,
            price=100.0,
            stop=94.0,
            module="entry_trigger.stub",
            risk_dollars=0.0,
            order_type="market",
            protective_stop=91.0,
        )
    ]

    result = phase.evaluate(ctx)

    assert result.facts["filled"] == 1
    intent = ctx.bar_state.sized_orders[0]
    assert intent.qty == 62
    assert intent.price == 100.0
    assert intent.stop == 94.0
    assert intent.order_type == "market"
    assert intent.protective_stop == 91.0
    assert intent.module == "entry_trigger.stub|sizing.rank_aware_heatcap"
