from __future__ import annotations

from datetime import datetime

from engine.context import OrderIntent, PhaseContext
from phases.sizing.rank_aware_heatcap.rank_aware_heatcap import RankAwareHeatcap, rank_multiplier


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
    def __init__(self, *, cash: float = 100_000.0, total: float = 100_000.0) -> None:
        self.cash = cash
        self.total_portfolio_value = total


class FakeQC:
    def __init__(self, *, cash: float = 100_000.0, total: float = 100_000.0) -> None:
        self.portfolio = FakePortfolio(cash=cash, total=total)
        self._active: set[FakeSymbol] = set()
        self.securities: dict[FakeSymbol, FakeSecurity] = {}
        self._candidate_snapshot: dict[FakeSymbol, dict[str, object]] = {}

    def snapshot_for_entry(self, sym: FakeSymbol) -> dict[str, object] | None:
        return self._candidate_snapshot.get(sym)


def _add_symbol(qc: FakeQC, ticker: str, *, price: float, scanner_rank: int | None) -> FakeSymbol:
    sym = FakeSymbol(ticker)
    qc._active.add(sym)
    qc.securities[sym] = FakeSecurity(price)
    snap: dict[str, object] = {"signal_price": price}
    if scanner_rank is not None:
        snap["scanner_rank"] = scanner_rank
    qc._candidate_snapshot[sym] = snap
    return sym


def _ctx(qc: FakeQC, tickers: list[str]) -> PhaseContext:
    ctx = PhaseContext(qc=qc, time=datetime(2025, 1, 2, 14, 35), data=None, clock="intraday")
    ctx.bar_state.sized_orders = [
        OrderIntent(
            ticker=ticker,
            qty=0,
            price=0.0,
            stop=0.0,
            module="entry",
            risk_dollars=0.0,
            order_type="market",
            protective_stop=88.0,
        )
        for ticker in tickers
    ]
    return ctx


def test_rank_multiplier_buckets() -> None:
    assert rank_multiplier(
        scanner_rank=3,
        top_rank_max=10,
        mid_rank_max=20,
        top_multiplier=1.25,
        mid_multiplier=1.0,
        tail_multiplier=0.5,
    ) == (1.25, "top")
    assert rank_multiplier(
        scanner_rank=15,
        top_rank_max=10,
        mid_rank_max=20,
        top_multiplier=1.25,
        mid_multiplier=1.0,
        tail_multiplier=0.5,
    ) == (1.0, "mid")
    assert rank_multiplier(
        scanner_rank=35,
        top_rank_max=10,
        mid_rank_max=20,
        top_multiplier=1.25,
        mid_multiplier=1.0,
        tail_multiplier=0.5,
    ) == (0.5, "tail")
    assert rank_multiplier(
        scanner_rank=None,
        top_rank_max=10,
        mid_rank_max=20,
        top_multiplier=1.25,
        mid_multiplier=1.0,
        tail_multiplier=0.5,
    ) == (0.0, "missing")


def test_sizes_by_scanner_rank_bucket_and_preserves_order_contract() -> None:
    qc = FakeQC()
    _add_symbol(qc, "AAA", price=100.0, scanner_rank=3)
    _add_symbol(qc, "BBB", price=100.0, scanner_rank=15)
    _add_symbol(qc, "CCC", price=100.0, scanner_rank=35)
    phase = RankAwareHeatcap(
        RankAwareHeatcap.Params(
            position_pct=0.05,
            top_multiplier=1.25,
            mid_multiplier=1.00,
            tail_multiplier=0.50,
        ),
        logger=None,
    )

    ctx = _ctx(qc, ["AAA", "BBB", "CCC"])
    result = phase.evaluate(ctx)

    by_ticker = {intent.ticker: intent for intent in ctx.bar_state.sized_orders}
    assert by_ticker["AAA"].qty == 62
    assert by_ticker["AAA"].risk_dollars == 6250.0
    assert by_ticker["BBB"].qty == 50
    assert by_ticker["BBB"].risk_dollars == 5000.0
    assert by_ticker["CCC"].qty == 25
    assert by_ticker["CCC"].risk_dollars == 2500.0
    assert all(intent.order_type == "market" for intent in by_ticker.values())
    assert all(intent.protective_stop == 88.0 for intent in by_ticker.values())
    assert result.facts["bucket_top"] == 1
    assert result.facts["bucket_mid"] == 1
    assert result.facts["bucket_tail"] == 1


def test_declines_candidate_without_scanner_rank() -> None:
    qc = FakeQC()
    _add_symbol(qc, "AAA", price=100.0, scanner_rank=None)
    phase = RankAwareHeatcap(RankAwareHeatcap.Params(), logger=None)

    ctx = _ctx(qc, ["AAA"])
    result = phase.evaluate(ctx)

    assert ctx.bar_state.sized_orders == []
    assert result.facts["declined_missing"] == 1
    assert result.facts["bucket_missing"] == 1


def test_heat_cap_still_breaks_on_cash_exhaustion() -> None:
    qc = FakeQC(cash=9_000.0, total=100_000.0)
    _add_symbol(qc, "AAA", price=100.0, scanner_rank=3)
    _add_symbol(qc, "BBB", price=100.0, scanner_rank=15)
    phase = RankAwareHeatcap(
        RankAwareHeatcap.Params(
            position_pct=0.05,
            top_multiplier=1.25,
            mid_multiplier=1.00,
        ),
        logger=None,
    )

    ctx = _ctx(qc, ["AAA", "BBB"])
    result = phase.evaluate(ctx)

    assert [intent.ticker for intent in ctx.bar_state.sized_orders] == ["AAA"]
    assert result.facts["skipped_cash"] == 1
