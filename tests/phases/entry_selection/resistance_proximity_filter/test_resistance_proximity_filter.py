"""ResistanceProximityFilter: reject within buffer% of 52wk high, keep further below, fail-open on no high."""
from datetime import datetime
from engine.context import PhaseContext, OrderIntent
from phases.entry_selection.resistance_proximity_filter.resistance_proximity_filter import ResistanceProximityFilter


class _Sym:
    def __init__(self, v): self.value = v
    def __hash__(self): return hash(self.value)
    def __eq__(self, o): return isinstance(o, _Sym) and o.value == self.value


class _QC:
    def __init__(self, highs):
        self._active = {_Sym(n) for n in highs}
        self._high_52w = {_Sym(n): h for n, h in highs.items()}


def _run(intents, highs, buffer_pct=0.03):
    qc = _QC(highs)
    p = ResistanceProximityFilter(ResistanceProximityFilter.Params(buffer_pct=buffer_pct), logger=None)
    ctx = PhaseContext(qc=qc, time=datetime(2025, 1, 2), data=None)
    ctx.bar_state.sized_orders = intents
    p.evaluate(ctx)
    return [o.ticker for o in ctx.bar_state.sized_orders]


def _intent(t, price): return OrderIntent(ticker=t, qty=0, price=price, stop=0.0, module="s", risk_dollars=0.0)


def test_rejects_within_buffer_of_high():
    # AAA price 98, 52wk high 100 → within 3% (98 >= 97) → REJECT
    assert _run([_intent("AAA", 98.0)], {"AAA": 100.0}, 0.03) == []


def test_keeps_well_below_high():
    # BBB price 90, high 100 → 10% below (90 < 97) → KEEP
    assert _run([_intent("BBB", 90.0)], {"BBB": 100.0}, 0.03) == ["BBB"]


def test_fail_open_no_high():
    # no 52wk high → cannot reject → KEEP
    assert _run([_intent("CCC", 99.0)], {}, 0.03) == ["CCC"]


def test_param_buffer_2pct_for_scenario_c():
    # price 97.5, high 100 → 2.5% below: rejected at 3% (97.5>=97), KEPT at 2% (97.5<98)
    assert _run([_intent("DDD", 97.5)], {"DDD": 100.0}, 0.03) == []
    assert _run([_intent("DDD", 97.5)], {"DDD": 100.0}, 0.02) == ["DDD"]
