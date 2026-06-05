"""StubEntryTrigger (M1) — the intraday per-bar trigger teeth: armed+near-zone FIRES a market entry,
far-from-zone / already-held / empty DECLINE. Look-ahead-safe (close vs known zone). Constructor:
(Params(...), logger=None)."""
from engine.context import PhaseContext
from phases.entry_trigger.stub_trigger.stub_trigger import StubEntryTrigger
from datetime import datetime


class _Sym:
    def __init__(self, v): self.value = v
    def __hash__(self): return hash(self.value)
    def __eq__(self, o): return isinstance(o, _Sym) and o.value == self.value


class _Hold:
    def __init__(self, invested=False): self.invested = invested


class _Sec:
    def __init__(self, close): self.close = close


class _QC:
    def __init__(self): self.portfolio = {}; self.securities = {}; self._armed = {}


def _arm(qc, name, close, zone, held=False):
    s = _Sym(name)
    qc.portfolio[s] = _Hold(held); qc.securities[s] = _Sec(close)
    qc._armed[s] = {"zone": zone, "armed_date": "2025-01-02"}
    return s


def _run(qc, **kw):
    p = StubEntryTrigger(StubEntryTrigger.Params(**kw), logger=None)
    ctx = PhaseContext(qc=qc, time=datetime(2025, 1, 3, 11, 0), data=None)
    p.evaluate(ctx)
    return ctx.bar_state.sized_orders


def test_fires_armed_near_zone():
    # close 100.5 within 1% of zone 100 → FIRE a market entry stub.
    qc = _QC(); _arm(qc, "AAA", close=100.5, zone=100.0)
    out = _run(qc, near_pct=0.01)
    assert len(out) == 1 and out[0].ticker == "AAA" and out[0].order_type == "market" and out[0].qty == 0


def test_declines_far_from_zone():
    # close 110 is 10% from zone 100 > near_pct 1% → proximity-gate OFF → no fire.
    qc = _QC(); _arm(qc, "FAR", close=110.0, zone=100.0)
    assert _run(qc, near_pct=0.01) == []


def test_declines_already_held():
    # armed + near zone BUT already invested → not an entry candidate → no fire.
    qc = _QC(); _arm(qc, "HELD", close=100.0, zone=100.0, held=True)
    assert _run(qc, near_pct=0.01) == []


def test_empty_armed_no_fire():
    qc = _QC()
    assert _run(qc, near_pct=0.01) == []


def test_no_market_on_open_emitted():
    # the deleted 2nd-slot: this phase NEVER emits market_on_open — always intraday "market".
    qc = _QC(); _arm(qc, "AAA", close=100.0, zone=100.0)
    out = _run(qc, near_pct=0.01)
    assert all(o.order_type == "market" for o in out) and not any(o.order_type == "market_on_open" for o in out)
