"""#181 — the hard gross-exposure cap phase: the safety floor that prevents over-leverage.

Behavioral + mutation-bite: drops entries that breach the % ceiling, keeps those under, the cap
is a %-rule (not a count cap), parameterized + #302-modulatable.
"""
from __future__ import annotations

from datetime import datetime

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


def test_space_and_complexity_declared() -> None:
    # ADR templates: space() axis + COMPLEXITY free_params match.
    sp = GrossExposureCap.Params.space()
    assert "max_gross_pct" in sp.axes
    assert GrossExposureCap.COMPLEXITY.free_params == 1
