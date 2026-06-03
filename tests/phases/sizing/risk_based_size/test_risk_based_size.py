"""#339 RUN S2 — RiskBasedSize: size = $risk / stop_frac (entry−cloud_bottom), capped at position_cap.
Tight stop → bigger (to cap); wide stop → smaller. Constructor: (Params(...), logger=None)."""
from datetime import datetime

from engine.context import OrderIntent, PhaseContext
from phases.sizing.risk_based_size.risk_based_size import RiskBasedSize


class FakePortfolio(dict):
    def __init__(self, cash=100_000.0, total=100_000.0):
        super().__init__()
        self.cash = cash
        self.total_portfolio_value = total


class FakeSymbol:
    def __init__(self, value):
        self.value = value

    def __hash__(self):
        return hash(self.value)

    def __eq__(self, o):
        return self.value == o.value


class FakeSecurity:
    def __init__(self, price):
        self.price = price


class FakeQC:
    def __init__(self, cash=100_000.0, total=100_000.0):
        self.portfolio = FakePortfolio(cash, total)
        self._active = set()
        self.securities = {}
        self._snaps = {}

    def snapshot_for_entry(self, sym):
        return self._snaps.get(sym)


def _add(qc, name, price, cloud_bottom):
    sym = FakeSymbol(name)
    qc._active.add(sym)
    qc.securities[sym] = FakeSecurity(price)
    qc._snaps[sym] = {"daily_cloud_bottom": cloud_bottom} if cloud_bottom is not None else None
    return sym


def _ctx(qc, names):
    ctx = PhaseContext(qc=qc, time=datetime(2025, 1, 2), data=None)
    ctx.bar_state.sized_orders = [
        OrderIntent(ticker=t, qty=0, price=0.0, stop=0.0, module="stub", risk_dollars=0.0)
        for t in names
    ]
    return ctx


def _run(qc, names, risk=500.0, cap=0.10):
    ctx = _ctx(qc, names)
    RiskBasedSize(RiskBasedSize.Params(risk_dollars=risk, position_cap=cap), logger=None).evaluate(ctx)
    return {o.ticker: o.qty for o in ctx.bar_state.sized_orders}


def test_sizes_vary_by_stop_distance():
    # risk $500, equity 100k, cap 10% (=10k). AAPL stop_frac 0.10 → 500/0.10=5000 → qty 50.
    # MSFT stop_frac 0.20 → 500/0.20=2500 → qty 25. Tighter stop = bigger position.
    qc = FakeQC()
    _add(qc, "AAPL", 100.0, 90.0)   # stop_dist 10 → frac 0.10
    _add(qc, "MSFT", 100.0, 80.0)   # stop_dist 20 → frac 0.20
    q = _run(qc, ["AAPL", "MSFT"])
    assert q["AAPL"] == 50 and q["MSFT"] == 25  # SIZES VARY (the assert)
    assert q["AAPL"] > q["MSFT"]


def test_cap_enforced_on_tight_stop():
    # very tight stop (frac 0.01) → 500/0.01=50000, capped at 10k → qty 100.
    qc = FakeQC()
    _add(qc, "AAPL", 100.0, 99.0)
    assert _run(qc, ["AAPL"])["AAPL"] == 100


def test_degenerate_stop_falls_back_to_cap():
    # cloud_bottom >= entry → stop_dist<=0 → cap fallback (no div-by-zero) → qty 100.
    qc = FakeQC()
    _add(qc, "AAPL", 100.0, 100.0)
    assert _run(qc, ["AAPL"])["AAPL"] == 100


def test_no_snapshot_skipped():
    qc = FakeQC()
    _add(qc, "AAPL", 100.0, None)  # no snapshot → skip
    assert _run(qc, ["AAPL"]) == {}


def test_missing_cloud_bottom_field_skipped():
    # snapshot PRESENT but daily_cloud_bottom absent → skip (never silently undersize to ~$risk)
    qc = FakeQC()
    sym = FakeSymbol("AAPL")
    qc._active.add(sym)
    qc.securities[sym] = FakeSecurity(100.0)
    qc._snaps[sym] = {"signal_price": 100.0}  # no daily_cloud_bottom key
    assert _run(qc, ["AAPL"]) == {}


def test_cash_exhaustion_breaks():
    qc = FakeQC(cash=6000.0, total=100_000.0)  # only 6k cash
    _add(qc, "AAPL", 100.0, 90.0)   # target 5000 ✓ (fits)
    _add(qc, "MSFT", 100.0, 90.0)   # target 5000, only 1k left → break
    q = _run(qc, ["AAPL", "MSFT"])
    assert list(q.keys()) == ["AAPL"]


def test_never_blocks():
    qc = FakeQC()
    ctx = _ctx(qc, [])
    res = RiskBasedSize(RiskBasedSize.Params(), logger=None).evaluate(ctx)
    assert res.blocked is False
