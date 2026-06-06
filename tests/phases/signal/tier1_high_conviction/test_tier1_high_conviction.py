"""Tier1HighConviction: keeps only ranked_candidates in the tier1 set, writes qty=0 stubs."""
from datetime import datetime
from engine.context import PhaseContext, BarState
from phases.signal.tier1_high_conviction.tier1_high_conviction import Tier1HighConviction


class _Sym:
    def __init__(self, v): self.value = v
    def __hash__(self): return hash(self.value)
    def __eq__(self, o): return isinstance(o, _Sym) and o.value == self.value


class _Sec:
    def __init__(self, price): self.price = price


class _QC:
    def __init__(self, names):
        self._active = {_Sym(n) for n in names}
        self.securities = {_Sym(n): _Sec(100.0) for n in names}


def _run(candidates, active, tier1=("AAA", "BBB")):
    qc = _QC(active)
    p = Tier1HighConviction(Tier1HighConviction.Params(tier1_set=tier1), logger=None)
    ctx = PhaseContext(qc=qc, time=datetime(2025, 1, 2), data=None)
    ctx.bar_state.ranked_candidates = candidates
    p.evaluate(ctx)
    return ctx.bar_state.sized_orders


def test_keeps_only_tier1_names():
    orders = _run(["AAA", "ZZZ", "BBB", "QQQ"], ["AAA", "BBB", "ZZZ", "QQQ"], tier1=("AAA", "BBB"))
    assert sorted(o.ticker for o in orders) == ["AAA", "BBB"]  # ZZZ/QQQ not tier1 → dropped


def test_stubs_are_qty_zero():
    orders = _run(["AAA"], ["AAA"], tier1=("AAA",))
    assert orders and orders[0].qty == 0 and orders[0].module == "signal.tier1_high_conviction"


def test_no_tier1_candidates_empty():
    assert _run(["XXX", "YYY"], ["XXX", "YYY"], tier1=("AAA",)) == []


def test_skips_unsubscribed_tier1_name():
    # CCC is tier1 + ranked but NOT in _active/securities → skipped (no stub)
    orders = _run(["AAA", "CCC"], ["AAA"], tier1=("AAA", "CCC"))
    assert [o.ticker for o in orders] == ["AAA"]
