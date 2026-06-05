"""
v2-delta: constructor is FlatPctHeatcap(FlatPctHeatcap.Params(...), logger=None).
Slot mechanic removed (charter: no fixed slots) — exposure is cash-heat-capped only.
"""
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
    phase = FlatPctHeatcap(FlatPctHeatcap.Params(position_pct=0.10), logger=None)
    ctx = make_ctx(qc, ["AAPL"])
    phase.evaluate(ctx)
    assert len(ctx.bar_state.sized_orders) == 1
    assert ctx.bar_state.sized_orders[0].qty == 100  # 10000 / 100 = 100


def test_heat_cap_stops_on_cash_exhaustion():
    qc = FakeQC(cash=15_000.0, total=100_000.0)  # only 15k cash, target=10k each
    _add_symbol(qc, "AAPL", 100.0)  # first: 10k ✓
    _add_symbol(qc, "MSFT", 100.0)  # second: needs 10k, only 5k left → stop
    _add_symbol(qc, "GOOG", 100.0)  # third: never reached (oracle uses break)
    phase = FlatPctHeatcap(FlatPctHeatcap.Params(position_pct=0.10), logger=None)
    ctx = make_ctx(qc, ["AAPL", "MSFT", "GOOG"])
    phase.evaluate(ctx)
    assert len(ctx.bar_state.sized_orders) == 1  # only AAPL fits


def test_zero_price_skipped():
    qc = FakeQC(cash=100_000.0, total=100_000.0)
    _add_symbol(qc, "AAPL", 0.0)  # price=0 → qty=0 → skip
    phase = FlatPctHeatcap(FlatPctHeatcap.Params(), logger=None)
    ctx = make_ctx(qc, ["AAPL"])
    phase.evaluate(ctx)
    assert len(ctx.bar_state.sized_orders) == 0


def test_sizing_never_blocks():
    qc = FakeQC()
    phase = FlatPctHeatcap(FlatPctHeatcap.Params(), logger=None)
    ctx = make_ctx(qc, [])
    result = phase.evaluate(ctx)
    assert result.blocked is False


def test_all_candidates_filled_when_cash_ample():
    # No slot cap: cash-ample → all ranked candidates fill (slot mechanic gone)
    qc = FakeQC(cash=1_000_000.0, total=1_000_000.0)
    for name in ["AAPL", "MSFT", "GOOG"]:
        _add_symbol(qc, name, 100.0)
    phase = FlatPctHeatcap(FlatPctHeatcap.Params(position_pct=0.10), logger=None)
    ctx = make_ctx(qc, ["AAPL", "MSFT", "GOOG"])
    phase.evaluate(ctx)
    assert len(ctx.bar_state.sized_orders) == 3


def test_base_params_has_no_reserve_field():
    # the #340-reserve param lives ONLY on ReserveHeatcap.Params — keeping FlatPctHeatcap.Params (and the
    # champion config_hash e573e84b1ce1) byte-identical. Guard against re-adding it to the base by mistake.
    assert not hasattr(FlatPctHeatcap.Params(), "base_entry_gross_budget")
