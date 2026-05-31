"""Behavioral tests for the score-aware sizer (score_tier_heatcap).

The X/4 entry-confirm score BINDS on SIZE (the methodology tiers):
  FIRE:    4/4 -> full (position_pct) ; 3/4 -> 0.75x ; 2/4 -> 0.50x
  DECLINE: <2  -> 0.0 (no entry) ; missing _entry_confirm -> 0.0 (no entry, NO flat fall-back)
  HEAT-CAP composition: the tier target is bounded by gross cash (oracle break on exhaustion)
  EDGE: zero-price skip, score-boundary, whole-dict-missing

Constructor: ScoreTierHeatcap(ScoreTierHeatcap.Params(...), logger=None). No slot mechanic
(charter: no fixed slots) — exposure is the tier target bounded by the cash heat-cap.
"""
from datetime import datetime

from engine.context import OrderIntent, PhaseContext
from phases.sizing.score_tier_heatcap.score_tier_heatcap import ScoreTierHeatcap


class FakeSymbol:
    def __init__(self, value):
        self.value = value
    def __hash__(self): return hash(self.value)
    def __eq__(self, other): return self.value == other.value


class FakeSecurity:
    def __init__(self, price):
        self.price = price


class FakePortfolio:
    def __init__(self, cash=1_000_000.0, total=1_000_000.0):
        self.cash = cash
        self.total_portfolio_value = total


class FakeQC:
    def __init__(self, cash=1_000_000.0, total=1_000_000.0):
        self.portfolio = FakePortfolio(cash=cash, total=total)
        self._active = set()
        self.securities = {}
        self._entry_confirm = {}


def _add_symbol(qc, name, price):
    sym = FakeSymbol(name)
    qc._active.add(sym)
    qc.securities[sym] = FakeSecurity(price)
    return sym


def make_ctx(qc, candidates):
    ctx = PhaseContext(qc=qc, time=datetime(2025, 1, 2), data=None)
    ctx.bar_state.sized_orders = [
        OrderIntent(ticker=t, qty=0, price=0.0, stop=0.0, module="stub", risk_dollars=0.0)
        for t in candidates
    ]
    return ctx


def _phase(**kw):
    return ScoreTierHeatcap(ScoreTierHeatcap.Params(**kw), logger=None)


# ---- FIRE: the tier curve binds (4/4 full, 3/4 0.75x, 2/4 0.50x) ----

def test_4of4_full_size():
    # PV=1M, position_pct=0.10, tier=full(1.0) -> target 100k @ price 100 -> qty 1000
    qc = FakeQC()
    _add_symbol(qc, "AAPL", 100.0)
    qc._entry_confirm = {"AAPL": 4}
    ctx = make_ctx(qc, ["AAPL"])
    _phase(position_pct=0.10).evaluate(ctx)
    assert len(ctx.bar_state.sized_orders) == 1
    assert ctx.bar_state.sized_orders[0].qty == 1000          # 100_000 / 100
    assert ctx.bar_state.sized_orders[0].risk_dollars == 100_000.0


def test_3of4_three_quarter_size():
    qc = FakeQC()
    _add_symbol(qc, "MSFT", 100.0)
    qc._entry_confirm = {"MSFT": 3}
    ctx = make_ctx(qc, ["MSFT"])
    _phase(position_pct=0.10).evaluate(ctx)
    assert ctx.bar_state.sized_orders[0].qty == 750           # 0.75 * 100_000 / 100
    assert ctx.bar_state.sized_orders[0].risk_dollars == 75_000.0


def test_2of4_half_size():
    qc = FakeQC()
    _add_symbol(qc, "GOOG", 100.0)
    qc._entry_confirm = {"GOOG": 2}
    ctx = make_ctx(qc, ["GOOG"])
    _phase(position_pct=0.10).evaluate(ctx)
    assert ctx.bar_state.sized_orders[0].qty == 500           # 0.50 * 100_000 / 100
    assert ctx.bar_state.sized_orders[0].risk_dollars == 50_000.0


def test_tier_ordering_4_gt_3_gt_2():
    # The methodology curve must be monotone: 4/4 sizes > 3/4 > 2/4 at the same price/PV.
    qc = FakeQC()
    for n, p in [("A", 4), ("B", 3), ("C", 2)]:
        _add_symbol(qc, n, 100.0)
    qc._entry_confirm = {"A": 4, "B": 3, "C": 2}
    ctx = make_ctx(qc, ["A", "B", "C"])
    _phase(position_pct=0.10).evaluate(ctx)
    by_t = {o.ticker: o.qty for o in ctx.bar_state.sized_orders}
    assert by_t["A"] > by_t["B"] > by_t["C"]


# ---- DECLINE: below min_score, missing score ----

def test_score_below_min_no_entry():
    qc = FakeQC()
    _add_symbol(qc, "AAPL", 100.0)
    qc._entry_confirm = {"AAPL": 1}   # <2 -> tier 0.0 -> no entry
    ctx = make_ctx(qc, ["AAPL"])
    res = _phase(position_pct=0.10).evaluate(ctx)
    assert len(ctx.bar_state.sized_orders) == 0
    assert res.facts["declined_score"] == 1


def test_missing_score_declines_no_flat_fallback():
    # FLAGGED contract decision: a candidate with NO published _entry_confirm entry is DECLINED
    # (NOT sized flat). A wiring bug must fail visibly (zero entries), never masquerade as flat.
    qc = FakeQC()
    _add_symbol(qc, "AAPL", 100.0)
    qc._entry_confirm = {"MSFT": 4}   # AAPL has no score
    ctx = make_ctx(qc, ["AAPL"])
    res = _phase(position_pct=0.10).evaluate(ctx)
    assert len(ctx.bar_state.sized_orders) == 0
    assert res.facts["declined_missing"] == 1


def test_whole_dict_missing_declines_all():
    # No entry_confirm phase wired at all (attribute absent) -> every candidate declines -> 0 orders.
    qc = FakeQC()
    del qc._entry_confirm
    _add_symbol(qc, "AAPL", 100.0)
    ctx = make_ctx(qc, ["AAPL"])
    res = _phase(position_pct=0.10).evaluate(ctx)
    assert len(ctx.bar_state.sized_orders) == 0
    assert res.facts["declined_missing"] == 1


# ---- HEAT-CAP composition: tier target bounded by gross cash ----

def test_heat_cap_bounds_tier_targets():
    # cash=120k; AAPL 4/4 target=100k (fits), MSFT 4/4 target=100k (only 20k left -> stop).
    qc = FakeQC(cash=120_000.0, total=1_000_000.0)
    _add_symbol(qc, "AAPL", 100.0)
    _add_symbol(qc, "MSFT", 100.0)
    qc._entry_confirm = {"AAPL": 4, "MSFT": 4}
    ctx = make_ctx(qc, ["AAPL", "MSFT"])
    res = _phase(position_pct=0.10).evaluate(ctx)
    assert len(ctx.bar_state.sized_orders) == 1
    assert res.facts["skipped_cash"] == 1


def test_smaller_tier_lets_more_names_fit():
    # Same 120k cash but both 2/4 -> targets 50k each -> BOTH fit (tier shrinks the per-name claim).
    qc = FakeQC(cash=120_000.0, total=1_000_000.0)
    _add_symbol(qc, "AAPL", 100.0)
    _add_symbol(qc, "MSFT", 100.0)
    qc._entry_confirm = {"AAPL": 2, "MSFT": 2}
    ctx = make_ctx(qc, ["AAPL", "MSFT"])
    _phase(position_pct=0.10).evaluate(ctx)
    assert len(ctx.bar_state.sized_orders) == 2


# ---- EDGE ----

def test_zero_price_skipped():
    qc = FakeQC()
    _add_symbol(qc, "AAPL", 0.0)
    qc._entry_confirm = {"AAPL": 4}
    ctx = make_ctx(qc, ["AAPL"])
    _phase().evaluate(ctx)
    assert len(ctx.bar_state.sized_orders) == 0


def test_case_insensitive_score_lookup():
    # _entry_confirm keyed lowercase, active Symbol.value uppercase -> still matches.
    qc = FakeQC()
    _add_symbol(qc, "AAPL", 100.0)
    qc._entry_confirm = {"aapl": 4}
    ctx = make_ctx(qc, ["AAPL"])
    _phase(position_pct=0.10).evaluate(ctx)
    assert len(ctx.bar_state.sized_orders) == 1
    assert ctx.bar_state.sized_orders[0].qty == 1000


def test_min_score_3_excludes_2of4():
    # Raising the entry floor to 3 turns a 2/4 into a no-entry.
    qc = FakeQC()
    _add_symbol(qc, "AAPL", 100.0)
    qc._entry_confirm = {"AAPL": 2}
    ctx = make_ctx(qc, ["AAPL"])
    res = _phase(position_pct=0.10, min_score=3).evaluate(ctx)
    assert len(ctx.bar_state.sized_orders) == 0
    assert res.facts["declined_score"] == 1


def test_sizing_never_blocks():
    qc = FakeQC()
    res = _phase().evaluate(make_ctx(qc, []))
    assert res.blocked is False


def test_determinism():
    def run():
        qc = FakeQC()
        for n, s in [("A", 4), ("B", 3), ("C", 2)]:
            _add_symbol(qc, n, 100.0)
        qc._entry_confirm = {"A": 4, "B": 3, "C": 2}
        ctx = make_ctx(qc, ["A", "B", "C"])
        _phase(position_pct=0.10).evaluate(ctx)
        return [(o.ticker, o.qty) for o in ctx.bar_state.sized_orders]
    assert run() == run()
