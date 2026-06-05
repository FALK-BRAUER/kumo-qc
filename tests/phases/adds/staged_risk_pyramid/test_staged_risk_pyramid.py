"""StagedRiskPyramid (#340-B / Pe-rampup) — the add DECISION: fires on (in-profit AND fresh Tenkan>
Kijun cross) within the max-adds cap; declines otherwise (no cross / not in profit / cap reached);
first-touch seeds state without adding; staged-risk sizing ($200 then $400). Constructor: (Params, logger)."""
from datetime import datetime

from engine.context import PhaseContext
from phases.adds.staged_risk_pyramid.staged_risk_pyramid import StagedRiskPyramid

_ENTRY = datetime(2025, 1, 2)


def _ind(tenkan: float, kijun: float, ready: bool = True):
    v = lambda x: type("V", (), {"current": type("C", (), {"value": x})()})()  # noqa: E731
    return type("I", (), {"is_ready": ready, "tenkan": v(tenkan), "kijun": v(kijun)})()


class _Hold:
    def __init__(self, invested=True, quantity=100):
        self.invested = invested
        self.quantity = quantity  # #340-C: position_value = quantity × close (Pe-posfrac/Pe-convstack)


class _Sec:
    def __init__(self, close):
        self.close = close


class _Order:
    """Minimal LEAN-order stand-in: only `.type` (the field the guard inspects)."""
    def __init__(self, order_type: str):
        self.type = order_type


class _Txn:
    def __init__(self, open_orders=None):
        self._open = open_orders or []

    def get_open_orders(self, symbol=None):
        return list(self._open)


class _QC:
    def __init__(self):
        self.portfolio = {}
        self.securities = {}
        self._indicators = {}
        self._position_meta = {}
        self.transactions = _Txn()


def _sym(name="HOOD"):
    return type("Symbol", (), {"value": name})()


def _setup(close, entry_price, tenkan, kijun, qty=100):
    qc = _QC()
    s = _sym()
    qc.portfolio[s] = _Hold(invested=True, quantity=qty)
    qc.securities[s] = _Sec(close)
    qc._indicators[s] = {"d_ichi": _ind(tenkan, kijun)}
    qc._position_meta[s] = {"entry_price": entry_price, "entry_date": _ENTRY}
    return qc, s


def _phase(max_adds=2, variant="Pe-rampup"):
    return StagedRiskPyramid(StagedRiskPyramid.Params(variant=variant, max_adds=max_adds), logger=None)


def test_fresh_cross_in_profit_adds():
    p = _phase()
    qc, s = _setup(close=110.0, entry_price=100.0, tenkan=12.0, kijun=10.0)  # tk_above + in profit
    p._state[s] = {"entry_date": _ENTRY, "lots": 1, "prev_tk_above": False}   # prior: below → this = FRESH cross
    ctx = PhaseContext(qc=qc, time=datetime(2025, 3, 1), data=None)
    p.evaluate(ctx)
    assert len(ctx.bar_state.add_intents) == 1
    add = ctx.bar_state.add_intents[0]
    assert add.qty == int(200.0 / 110.0) and add.qty >= 1 and add.risk_dollars == 200.0  # Pe-rampup lot-2 = $200
    assert p._state[s]["lots"] == 2


def test_no_fresh_cross_no_add():
    p = _phase()
    qc, s = _setup(close=110.0, entry_price=100.0, tenkan=12.0, kijun=10.0)  # tk_above, but...
    p._state[s] = {"entry_date": _ENTRY, "lots": 1, "prev_tk_above": True}    # ...already above → NOT a fresh cross
    ctx = PhaseContext(qc=qc, time=datetime(2025, 3, 1), data=None)
    p.evaluate(ctx)
    assert ctx.bar_state.add_intents == [] and p._state[s]["lots"] == 1


def test_not_in_profit_no_add():
    p = _phase()
    qc, s = _setup(close=95.0, entry_price=100.0, tenkan=12.0, kijun=10.0)    # fresh cross but BELOW entry
    p._state[s] = {"entry_date": _ENTRY, "lots": 1, "prev_tk_above": False}
    ctx = PhaseContext(qc=qc, time=datetime(2025, 3, 1), data=None)
    p.evaluate(ctx)
    assert ctx.bar_state.add_intents == []   # ADD-TO-WINNERS-ONLY — never average down


def test_max_adds_cap_blocks():
    p = _phase(max_adds=2)
    qc, s = _setup(close=110.0, entry_price=100.0, tenkan=12.0, kijun=10.0)
    p._state[s] = {"entry_date": _ENTRY, "lots": 3, "prev_tk_above": False}   # lots-1 == max_adds → capped
    ctx = PhaseContext(qc=qc, time=datetime(2025, 3, 1), data=None)
    p.evaluate(ctx)
    assert ctx.bar_state.add_intents == []


def test_first_touch_seeds_no_add():
    p = _phase()
    qc, s = _setup(close=110.0, entry_price=100.0, tenkan=12.0, kijun=10.0)   # no prior state
    ctx = PhaseContext(qc=qc, time=datetime(2025, 3, 1), data=None)
    p.evaluate(ctx)
    assert ctx.bar_state.add_intents == []          # first sight → seed, never add (no prior cross)
    assert p._state[s] == {"entry_date": _ENTRY, "lots": 1, "prev_tk_above": True}


def test_staged_sizing_second_add_is_400():
    p = _phase()
    qc, s = _setup(close=110.0, entry_price=100.0, tenkan=12.0, kijun=10.0)
    p._state[s] = {"entry_date": _ENTRY, "lots": 2, "prev_tk_above": False}   # lot-3 add → Pe-rampup $400
    ctx = PhaseContext(qc=qc, time=datetime(2025, 3, 1), data=None)
    p.evaluate(ctx)
    assert len(ctx.bar_state.add_intents) == 1 and ctx.bar_state.add_intents[0].risk_dollars == 400.0


# ── #340-C value-scaled variants (V2 Pe-posfrac, V3 Pe-convstack) — the sizing screen ──

def test_v2_posfrac_sizes_quarter_of_position():
    # V2: add = 0.25 × position_value (held_qty × close). qty=100, close=110 → posval 11000 → $2750.
    p = _phase(variant="Pe-posfrac")
    qc, s = _setup(close=110.0, entry_price=100.0, tenkan=12.0, kijun=10.0, qty=100)
    p._state[s] = {"entry_date": _ENTRY, "lots": 1, "prev_tk_above": False}  # fresh cross + in profit
    ctx = PhaseContext(qc=qc, time=datetime(2025, 3, 1), data=None)
    p.evaluate(ctx)
    assert len(ctx.bar_state.add_intents) == 1
    assert ctx.bar_state.add_intents[0].risk_dollars == 2750.0          # 0.25 × 11000 (scales w/ the winner)
    assert ctx.bar_state.add_intents[0].qty == int(2750.0 / 110.0)


def test_v2_posfrac_floored_at_200_on_small_position():
    # V2 floor: a tiny position (qty=5, close=110 → posval 550 → 0.25×550=137.5) floors UP to $200
    # (avoids the qty-lt-1 bug on high-price names).
    p = _phase(variant="Pe-posfrac")
    qc, s = _setup(close=110.0, entry_price=100.0, tenkan=12.0, kijun=10.0, qty=5)
    p._state[s] = {"entry_date": _ENTRY, "lots": 1, "prev_tk_above": False}
    ctx = PhaseContext(qc=qc, time=datetime(2025, 3, 1), data=None)
    p.evaluate(ctx)
    assert ctx.bar_state.add_intents[0].risk_dollars == 200.0


def test_v2_posfrac_floor_affords_one_share_on_high_price():
    # the floor must buy ≥1 SHARE on a high-price name: close=300, qty=2 → posval 600 → 0.25×600=$150,
    # but a flat $200 floor → int(200/300)=0 → SKIP. The share-aware floor = max($200, $300) → $300 →
    # int(300/300)=1 share FIRES. (the review #340-C bug fix: the floor solves qty-lt-1 for real.)
    p = _phase(variant="Pe-posfrac")
    qc, s = _setup(close=300.0, entry_price=250.0, tenkan=12.0, kijun=10.0, qty=2)  # in profit, fresh cross
    p._state[s] = {"entry_date": _ENTRY, "lots": 1, "prev_tk_above": False}
    ctx = PhaseContext(qc=qc, time=datetime(2025, 3, 1), data=None)
    p.evaluate(ctx)
    assert len(ctx.bar_state.add_intents) == 1, "high-price floor must FIRE ≥1 share, not skip on qty-lt-1"
    assert ctx.bar_state.add_intents[0].risk_dollars == 300.0 and ctx.bar_state.add_intents[0].qty == 1


def test_v3_convstack_high_conviction_3x():
    # V3: mult = clamp(unrealized%/10, 0.5, 3.0). +30% → 3.0×. qty=100,close=130 → posval 13000 →
    # 0.25×13000×3.0 = $9750 (the biggest add to the strongest winner — the monster).
    p = _phase(variant="Pe-convstack")
    qc, s = _setup(close=130.0, entry_price=100.0, tenkan=12.0, kijun=10.0, qty=100)
    p._state[s] = {"entry_date": _ENTRY, "lots": 1, "prev_tk_above": False}
    ctx = PhaseContext(qc=qc, time=datetime(2025, 3, 1), data=None)
    p.evaluate(ctx)
    assert ctx.bar_state.add_intents[0].risk_dollars == 9750.0


def test_v3_convstack_marginal_winner_half():
    # V3 damps marginal winners: +5% → mult 0.5×. qty=100,close=105 → posval 10500 →
    # 0.25×10500×0.5 = $1312.50 (small add to a marginal winner).
    p = _phase(variant="Pe-convstack")
    qc, s = _setup(close=105.0, entry_price=100.0, tenkan=12.0, kijun=10.0, qty=100)
    p._state[s] = {"entry_date": _ENTRY, "lots": 1, "prev_tk_above": False}
    ctx = PhaseContext(qc=qc, time=datetime(2025, 3, 1), data=None)
    p.evaluate(ctx)
    assert round(ctx.bar_state.add_intents[0].risk_dollars, 4) == 1312.5  # 0.25×10500×0.5 (float-safe)


def test_v2v3_decline_without_fresh_cross():
    # the DECLINE half (Falk's rule): the value-scaled variants still obey the SAME Pe-trigger —
    # no fresh cross → no add, regardless of sizing scheme (isolates sizing, not trigger).
    for variant in ("Pe-posfrac", "Pe-convstack"):
        p = _phase(variant=variant)
        qc, s = _setup(close=110.0, entry_price=100.0, tenkan=12.0, kijun=10.0, qty=100)
        p._state[s] = {"entry_date": _ENTRY, "lots": 1, "prev_tk_above": True}  # already above → not fresh
        ctx = PhaseContext(qc=qc, time=datetime(2025, 3, 1), data=None)
        p.evaluate(ctx)
        assert ctx.bar_state.add_intents == [], f"{variant} must obey the Pe-trigger (no add w/o fresh cross)"


def test_resting_protective_stop_does_NOT_block_add():
    """#340-B regression: every held position carries a GTC StopMarket protective stop. The add MUST
    still fire — the resting stop is excluded from the open-order guard. (The bug: it blocked 100% of
    adds → byte-identical-to-S1 no-op. The mock previously returned [] open orders, hiding it.)"""
    p = _phase()
    qc, s = _setup(close=110.0, entry_price=100.0, tenkan=12.0, kijun=10.0)  # fresh cross + in profit
    qc.transactions = _Txn(open_orders=[_Order("StopMarket")])               # the protective stop
    p._state[s] = {"entry_date": _ENTRY, "lots": 1, "prev_tk_above": False}
    ctx = PhaseContext(qc=qc, time=datetime(2025, 3, 1), data=None)
    p.evaluate(ctx)
    assert len(ctx.bar_state.add_intents) == 1   # add FIRES despite the resting stop
    assert p._state[s]["lots"] == 2


def test_pending_entry_or_add_DOES_block_add():
    """The guard's real purpose is preserved: a pending ENTRY/ADD (Market/MarketOnOpen) still blocks a
    new add → no STACKING duplicate adds on an unfilled order."""
    p = _phase()
    for ot in ("MarketOnOpen", "Market", "Limit"):
        qc, s = _setup(close=110.0, entry_price=100.0, tenkan=12.0, kijun=10.0)
        qc.transactions = _Txn(open_orders=[_Order(ot)])                      # pending entry/add in flight
        p._state[s] = {"entry_date": _ENTRY, "lots": 1, "prev_tk_above": False}
        ctx = PhaseContext(qc=qc, time=datetime(2025, 3, 1), data=None)
        p.evaluate(ctx)
        assert ctx.bar_state.add_intents == [], f"{ot} should block the add (no stacking)"


def test_stop_present_but_pending_entry_also_present_blocks():
    """Mixed open orders (a resting stop + a pending entry) → the pending entry still blocks; the stop
    is correctly ignored but does not un-block."""
    p = _phase()
    qc, s = _setup(close=110.0, entry_price=100.0, tenkan=12.0, kijun=10.0)
    qc.transactions = _Txn(open_orders=[_Order("StopMarket"), _Order("MarketOnOpen")])
    p._state[s] = {"entry_date": _ENTRY, "lots": 1, "prev_tk_above": False}
    ctx = PhaseContext(qc=qc, time=datetime(2025, 3, 1), data=None)
    p.evaluate(ctx)
    assert ctx.bar_state.add_intents == []   # pending entry blocks; stop alone would not have


def test_closed_position_state_gc():
    p = _phase()
    qc, s = _setup(close=110.0, entry_price=100.0, tenkan=12.0, kijun=10.0)
    p._state[s] = {"entry_date": _ENTRY, "lots": 2, "prev_tk_above": True}
    qc.portfolio[s].invested = False                # position closed
    ctx = PhaseContext(qc=qc, time=datetime(2025, 3, 1), data=None)
    p.evaluate(ctx)
    assert s not in p._state                        # GC'd → no stale lots leak into a re-entry
