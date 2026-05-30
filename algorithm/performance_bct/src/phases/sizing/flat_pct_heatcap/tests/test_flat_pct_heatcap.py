from datetime import datetime
from engine.context import PhaseContext, OrderIntent
from phases.sizing.flat_pct_heatcap.flat_pct_heatcap import FlatPctHeatcap


class FakeHolding:
    def __init__(self, invested=False):
        self.invested = invested


class FakePortfolio(dict):
    def __init__(self, cash=100_000.0, total=100_000.0):
        super().__init__()
        self.cash = cash
        self.total_portfolio_value = total

    def __missing__(self, key):
        return FakeHolding()


class FakeTransactions:
    def get_open_orders(self):
        return []


class FakeSymbol:
    def __init__(self, value):
        self.value = value
    def __hash__(self): return hash(self.value)
    def __eq__(self, other): return self.value == other.value


class FakeSecurity:
    def __init__(self, price):
        self.price = price


class FakeQC:
    def __init__(self, cash=100_000.0, total=100_000.0):
        self.portfolio = FakePortfolio(cash=cash, total=total)
        self.transactions = FakeTransactions()
        self._active = set()
        self.securities = {}


def make_ctx(qc, candidates):
    ctx = PhaseContext(qc=qc, time=datetime(2025, 1, 2), data=None)
    ctx.bar_state.sized_orders = [
        OrderIntent(ticker=t, qty=0, price=0.0, stop=0.0, module="stub", risk_dollars=0.0)
        for t in candidates
    ]
    return ctx


def _add_symbol(qc, name, price):
    sym = FakeSymbol(name)
    qc._active.add(sym)
    qc.securities[sym] = FakeSecurity(price)
    return sym


def test_sizes_at_10pct_portfolio_value():
    qc = FakeQC(cash=100_000.0, total=100_000.0)
    _add_symbol(qc, "AAPL", 100.0)  # target = 10k → qty=100
    phase = FlatPctHeatcap(params={"position_pct": 0.10}, logger=None)
    ctx = make_ctx(qc, ["AAPL"])
    phase.evaluate(ctx)
    assert len(ctx.bar_state.sized_orders) == 1
    assert ctx.bar_state.sized_orders[0].qty == 100  # 10000 / 100 = 100


def test_heat_cap_stops_on_cash_exhaustion():
    qc = FakeQC(cash=15_000.0, total=100_000.0)  # only 15k cash, target=10k each
    _add_symbol(qc, "AAPL", 100.0)  # first: 10k ✓
    _add_symbol(qc, "MSFT", 100.0)  # second: needs 10k, only 5k left → stop
    _add_symbol(qc, "GOOG", 100.0)  # third: never reached (oracle uses break)
    phase = FlatPctHeatcap(params={"position_pct": 0.10}, logger=None)
    ctx = make_ctx(qc, ["AAPL", "MSFT", "GOOG"])
    phase.evaluate(ctx)
    assert len(ctx.bar_state.sized_orders) == 1  # only AAPL fits


def test_no_slots_returns_empty():
    qc = FakeQC()
    aapl = _add_symbol(qc, "AAPL", 100.0)
    qc.portfolio[aapl] = FakeHolding(invested=True)  # already open
    phase = FlatPctHeatcap(params={"position_pct": 0.10, "max_positions": 1}, logger=None)
    ctx = make_ctx(qc, ["MSFT"])
    _add_symbol(qc, "MSFT", 100.0)
    result = phase.evaluate(ctx)
    assert result.decision == "no_slots"
    assert ctx.bar_state.sized_orders == []


def test_zero_price_skipped():
    qc = FakeQC(cash=100_000.0, total=100_000.0)
    _add_symbol(qc, "AAPL", 0.0)  # price=0 → qty=0 → skip
    phase = FlatPctHeatcap(params={}, logger=None)
    ctx = make_ctx(qc, ["AAPL"])
    phase.evaluate(ctx)
    assert len(ctx.bar_state.sized_orders) == 0


def test_sizing_never_blocks():
    qc = FakeQC()
    phase = FlatPctHeatcap(params={}, logger=None)
    ctx = make_ctx(qc, [])
    result = phase.evaluate(ctx)
    assert result.blocked is False


def test_vix_tier_slot_cap_respected():
    qc = FakeQC(cash=1_000_000.0, total=1_000_000.0)
    for name in ["AAPL", "MSFT", "GOOG"]:
        _add_symbol(qc, name, 100.0)
    phase = FlatPctHeatcap(params={"position_pct": 0.10}, logger=None)
    ctx = make_ctx(qc, ["AAPL", "MSFT", "GOOG"])
    # Inject vix_tier cap of 2 slots (0 open → only 2 can be filled)
    ctx.bar_state.phase_outputs["vix_tier"] = [{"max_positions": 2, "tier": 1}]
    phase.evaluate(ctx)
    assert len(ctx.bar_state.sized_orders) == 2
