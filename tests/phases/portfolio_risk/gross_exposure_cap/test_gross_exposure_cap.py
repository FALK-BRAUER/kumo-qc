"""#181 — the hard gross-exposure cap phase: the safety floor that prevents over-leverage.

Behavioral + mutation-bite: drops entries that breach the % ceiling, keeps those under, the cap
is a %-rule (not a count cap), parameterized + #302-modulatable.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from engine.base import DegradedDataError
from engine.context import OrderIntent, PhaseContext
from phases.portfolio_risk.gross_exposure_cap.gross_exposure_cap import GrossExposureCap


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


class FakePortfolio:
    def __init__(self, equity: float, held: float) -> None:
        self.total_portfolio_value = equity
        self.total_holdings_value = held


class FakeQC:
    def __init__(self, equity: float = 100_000.0, held: float = 0.0, price: float = 100.0) -> None:
        self.portfolio = FakePortfolio(equity, held)
        self.securities = FakeSecurities(price)
        self._active: set = set()
        self.logged: list[str] = []

    def Log(self, m: str) -> None: ...
    def log(self, m: str) -> None: self.logged.append(m)


def _phase(max_gross_pct: float = 1.0) -> GrossExposureCap:
    return GrossExposureCap(GrossExposureCap.Params(max_gross_pct=max_gross_pct), logger=None)


def _ctx(qc: FakeQC, orders: list[OrderIntent]) -> PhaseContext:
    c = PhaseContext(qc=qc, time=datetime(2025, 1, 2), data=None)
    c.bar_state.sized_orders = orders
    return c


def _intent(ticker: str, qty: int) -> OrderIntent:
    return OrderIntent(ticker=ticker, qty=qty, price=100.0, stop=0.0, module="t", risk_dollars=0.0)


def _wire(qc: FakeQC, tickers: list[str]) -> None:
    qc._active = {FakeSym(t) for t in tickers}


def test_under_cap_all_kept() -> None:
    # equity 100k, cap 100% → ceiling 100k. 5×($100×100=$10k)=$50k held=0 → all kept.
    qc = FakeQC(equity=100_000, held=0); _wire(qc, [f"T{i}" for i in range(5)])
    ctx = _ctx(qc, [_intent(f"T{i}", 100) for i in range(5)])
    _phase(1.0).evaluate(ctx)
    assert len(ctx.bar_state.sized_orders) == 5


def test_over_cap_drops_excess() -> None:
    # ceiling 100k; each order $10k; 0 held → only 10 fit, the 11th+ dropped.
    qc = FakeQC(equity=100_000, held=0); _wire(qc, [f"T{i}" for i in range(15)])
    ctx = _ctx(qc, [_intent(f"T{i}", 100) for i in range(15)])
    res = _phase(1.0).evaluate(ctx)
    assert len(ctx.bar_state.sized_orders) == 10  # 10×$10k = $100k ceiling
    assert res.facts["dropped"] == 5


def test_held_exposure_counts_against_cap() -> None:
    # 90k already held, ceiling 100k → only $10k room → 1 order kept, rest dropped.
    qc = FakeQC(equity=100_000, held=90_000); _wire(qc, [f"T{i}" for i in range(5)])
    ctx = _ctx(qc, [_intent(f"T{i}", 100) for i in range(5)])
    _phase(1.0).evaluate(ctx)
    assert len(ctx.bar_state.sized_orders) == 1, "held exposure must consume the cap"


def test_cap_is_parameterized() -> None:
    # MUTATION-BITE: the cap fraction binds. cap=0.5 → ceiling 50k → only 5 of the $10k orders.
    qc = FakeQC(equity=100_000, held=0); _wire(qc, [f"T{i}" for i in range(15)])
    ctx = _ctx(qc, [_intent(f"T{i}", 100) for i in range(15)])
    _phase(0.5).evaluate(ctx)
    assert len(ctx.bar_state.sized_orders) == 5, "max_gross_pct must bind (0.5×100k=50k → 5 orders)"


def test_never_blocks_the_bar() -> None:
    # the cap bounds what FIRES, never blocks the bar (blocked must be False even when it drops).
    qc = FakeQC(equity=100_000, held=200_000); _wire(qc, ["T0"])  # already over-leveraged
    ctx = _ctx(qc, [_intent("T0", 100)])
    res = _phase(1.0).evaluate(ctx)
    assert res.blocked is False
    assert len(ctx.bar_state.sized_orders) == 0  # over ceiling → dropped


def test_missing_holdings_attr_fails_loud() -> None:
    # FAIL-LOUD (#181/#261, the #276a review finding): a portfolio with NO total_holdings_value
    # must RAISE — never silently default to 0.0, which would measure new exposure against zero
    # held → permit max_gross_pct×equity on top of existing holdings (over-leverage).
    class PortfolioNoHoldings:
        total_portfolio_value = 100_000.0  # has equity but NOT total_holdings_value

    qc = FakeQC(); qc.portfolio = PortfolioNoHoldings(); _wire(qc, ["T0"])  # type: ignore[assignment]
    ctx = _ctx(qc, [_intent("T0", 100)])
    with pytest.raises(DegradedDataError, match="total_holdings_value"):
        _phase(1.0).evaluate(ctx)


def test_present_holdings_attr_does_not_raise() -> None:
    # MUTATION-BITE control (#263): the healthy path (attr present) must NOT raise — proves the
    # guard above fires on the degraded condition ONLY, not always (no tautology).
    qc = FakeQC(equity=100_000, held=0); _wire(qc, ["T0"])
    ctx = _ctx(qc, [_intent("T0", 100)])
    _phase(1.0).evaluate(ctx)  # no raise on the healthy path
    assert len(ctx.bar_state.sized_orders) == 1


# ── #181 BUG-2 Stage 0: commit-aware gross cap on ADDS (the FIRE_ADDS seam) ──

def _ctx_adds(qc: FakeQC, adds: list[OrderIntent]) -> PhaseContext:
    c = PhaseContext(qc=qc, time=datetime(2025, 1, 2), data=None)
    c.bar_state.add_intents = adds
    return c


def test_bound_adds_under_cap_passes() -> None:
    # ceiling 100k, 0 held, no in-flight entries → a $10k add fits.
    qc = FakeQC(equity=100_000, held=0); _wire(qc, ["T0"])
    ctx = _ctx_adds(qc, [_intent("T0", 100)])  # $100×100 = $10k
    _phase(1.0).bound_adds(ctx, in_flight_entry_value=0.0)
    assert len(ctx.bar_state.add_intents) == 1


def test_bound_adds_over_cap_blocked() -> None:
    # 95k held, ceiling 100k → only $5k room; a $10k add breaches → dropped.
    qc = FakeQC(equity=100_000, held=95_000); _wire(qc, ["T0"])
    ctx = _ctx_adds(qc, [_intent("T0", 100)])
    _phase(1.0).bound_adds(ctx, in_flight_entry_value=0.0)
    assert len(ctx.bar_state.add_intents) == 0, "add breaching the gross ceiling must be dropped"


def test_bound_adds_commit_aware_inflight_entries_consume_budget() -> None:
    # THE FILL-LAG TRAP (#181 BUG-2): total_holdings_value reads 0 (entries not yet filled this
    # tick), but $95k of entries were already SUBMITTED this tick. A $10k add must be DENIED —
    # held(0) + in-flight(95k) + add(10k) = 105k > 100k ceiling. Without commit-awareness the add
    # would wrongly pass against the stale 0 held → the leverage hole.
    qc = FakeQC(equity=100_000, held=0); _wire(qc, ["T0"])
    ctx = _ctx_adds(qc, [_intent("T0", 100)])  # $10k add
    _phase(1.0).bound_adds(ctx, in_flight_entry_value=95_000.0)
    assert len(ctx.bar_state.add_intents) == 0, "in-flight same-tick entries MUST consume the cap budget"


def test_bound_adds_control_inflight_within_budget_passes() -> None:
    # MUTATION-BITE control for the case above: drop the in-flight entries below the breach point
    # ($85k → 85k+10k=95k < 100k) and the SAME add now passes — proves the denial above is the
    # commit-aware math biting, not an always-deny.
    qc = FakeQC(equity=100_000, held=0); _wire(qc, ["T0"])
    ctx = _ctx_adds(qc, [_intent("T0", 100)])
    _phase(1.0).bound_adds(ctx, in_flight_entry_value=85_000.0)
    assert len(ctx.bar_state.add_intents) == 1


def test_bound_adds_disabled_is_noop() -> None:
    qc = FakeQC(equity=100_000, held=95_000); _wire(qc, ["T0"])
    ctx = _ctx_adds(qc, [_intent("T0", 100)])
    cap = GrossExposureCap(GrossExposureCap.Params(max_gross_pct=1.0, enabled=False), logger=None)
    cap.bound_adds(ctx, in_flight_entry_value=0.0)
    assert len(ctx.bar_state.add_intents) == 1, "disabled cap must not touch adds"


def test_bound_adds_missing_holdings_attr_fails_loud() -> None:
    # the BUG-1 fail-loud read is shared by the add seam too (single-source _held_gross).
    class PortfolioNoHoldings:
        total_portfolio_value = 100_000.0

    qc = FakeQC(); qc.portfolio = PortfolioNoHoldings(); _wire(qc, ["T0"])  # type: ignore[assignment]
    ctx = _ctx_adds(qc, [_intent("T0", 100)])
    with pytest.raises(DegradedDataError, match="total_holdings_value"):
        _phase(1.0).bound_adds(ctx, in_flight_entry_value=0.0)


def test_space_and_complexity_declared() -> None:
    # ADR templates: space() axis + COMPLEXITY free_params match.
    sp = GrossExposureCap.Params.space()
    assert "max_gross_pct" in sp.axes
    assert GrossExposureCap.COMPLEXITY.free_params == 1
