"""#340-reserve ReserveHeatcap — base-entry gross BUDGET (charter-compliant cash-reserve for the pyramid,
NOT a count/slot cap). Reserves (1 - budget) of portfolio value as cash only the pyramid adds may consume.
The reserve arithmetic lives in the inherited FlatPctHeatcap.evaluate (reads budget via getattr); this
subclass supplies the param. Constructor: ReserveHeatcap(ReserveHeatcap.Params(...), logger=None)."""
from datetime import datetime

from engine.context import OrderIntent, PhaseContext
from phases.sizing.reserve_heatcap.reserve_heatcap import ReserveHeatcap


class FakeHolding:
    def __init__(self, invested=False): self.invested = invested


class FakePortfolio(dict):
    def __init__(self, cash=100_000.0, total=100_000.0):
        super().__init__(); self.cash = cash; self.total_portfolio_value = total
    def __missing__(self, key): return FakeHolding()


class FakeSymbol:
    def __init__(self, value): self.value = value
    def __hash__(self): return hash(self.value)
    def __eq__(self, other): return self.value == other.value


class FakeSecurity:
    def __init__(self, price): self.price = price


class FakeQC:
    def __init__(self, cash=100_000.0, total=100_000.0):
        self.portfolio = FakePortfolio(cash=cash, total=total)
        self._active = set(); self.securities = {}


def _five_names(budget):
    # 5 fundable candidates @ 100, position_pct=0.10 → 10k each; cash=total=100k.
    qc = FakeQC(cash=100_000.0, total=100_000.0)
    names = ["A", "B", "C", "D", "E"]
    for n in names:
        sym = FakeSymbol(n); qc._active.add(sym); qc.securities[sym] = FakeSecurity(100.0)
    phase = ReserveHeatcap(ReserveHeatcap.Params(position_pct=0.10, base_entry_gross_budget=budget), logger=None)
    ctx = PhaseContext(qc=qc, time=datetime(2025, 1, 2), data=None)
    ctx.bar_state.sized_orders = [
        OrderIntent(ticker=n, qty=0, price=0.0, stop=0.0, module="stub", risk_dollars=0.0) for n in names
    ]
    res = phase.evaluate(ctx)
    return ctx, res


def test_marker_distinct_from_base():
    # distinct version_marker → distinct config identity from the champion sizer.
    assert ReserveHeatcap(ReserveHeatcap.Params(), logger=None).version_marker == "reserve_heatcap_v1"


def test_budget_default_1_0_is_noop():
    # budget=1.0 → reserve 0 → ALL 5 fill (50k < 100k) — behaviour-identical to the cash-only heat-cap.
    ctx, _ = _five_names(1.0)
    assert len(ctx.bar_state.sized_orders) == 5


def test_budget_binds_reserves_cash_for_the_pyramid():
    # budget=0.30 → reserve (1-0.30)×100k = 70k held back → base entries may use only 30k → 3 fills,
    # NOT 5. Mutation teeth: drop the `- reserve` term and this fills 5 (fails). Smaller budget = fewer.
    ctx30, _ = _five_names(0.30)
    assert len(ctx30.bar_state.sized_orders) == 3, "budget 0.30 must reserve 70k → only 3 base fills"
    ctx20, _ = _five_names(0.20)
    assert len(ctx20.bar_state.sized_orders) == 2, "smaller budget reserves MORE → fewer base fills"


def test_budget_holds_back_the_reserved_headroom_as_cash():
    # the reserve is literally HELD BACK as cash (what the pyramid adds then consume under the 1.0 gross
    # cap). committed base cash must not exceed budget×total; available − committed ≥ the reserve.
    ctx, res = _five_names(0.30)
    committed = res.facts["committed_cash"]
    assert committed <= 0.30 * 100_000.0 + 1e-6, "base entries must not breach the gross budget"
    assert 100_000.0 - committed >= 0.70 * 100_000.0 - 1e-6, "the (1-budget) headroom stays reserved as cash"


def test_budget_zero_reserves_everything_no_base_fills():
    # boundary: budget=0 → reserve = full tpv → base entries may touch NO cash → 0 base fills (all cash
    # reserved for the pyramid). The lower clamp boundary.
    ctx, _ = _five_names(0.0)
    assert len(ctx.bar_state.sized_orders) == 0


def test_budget_above_one_clamps_to_no_reserve():
    # boundary: budget>1.0 → (1-budget)<0 → max(0,·) clamps reserve to 0 → behaves as 1.0 (all 5 fill).
    ctx, _ = _five_names(1.5)
    assert len(ctx.bar_state.sized_orders) == 5
