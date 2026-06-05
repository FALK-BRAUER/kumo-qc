"""StubArm (M1) — writes day candidates into qc._armed (LEAN-sym keyed, {zone,armed_date}), PERSISTS
across days, engine never computes the zone. Constructor: (Params(), logger=None)."""
from datetime import datetime
from engine.context import PhaseContext, OrderIntent
from phases.arm.stub_arm.stub_arm import StubArm


class _Sym:
    def __init__(self, v): self.value = v
    def __hash__(self): return hash(self.value)
    def __eq__(self, o): return isinstance(o, _Sym) and o.value == self.value


class _Sec:
    def __init__(self, close): self.close = close


class _QC:
    def __init__(self): self.securities = {}; self._active = set(); self._armed = {}


def _cand(qc, name, close):
    s = _Sym(name); qc._active.add(s); qc.securities[s] = _Sec(close); return s


def _run(qc, tickers):
    p = StubArm(StubArm.Params(), logger=None)
    ctx = PhaseContext(qc=qc, time=datetime(2025, 1, 2), data=None)
    ctx.bar_state.sized_orders = [OrderIntent(ticker=t, qty=0, price=0.0, stop=0.0, module="s", risk_dollars=0.0) for t in tickers]
    p.evaluate(ctx)


def test_arms_candidates_with_zone():
    qc = _QC(); s = _cand(qc, "AAA", close=100.0)
    _run(qc, ["AAA"])
    assert s in qc._armed and qc._armed[s]["zone"] == 100.0 and qc._armed[s]["armed_date"] == "2025-01-02"


def test_persists_across_days():
    # day 1 arms AAA; day 2 arms BBB → AAA STILL armed (carry persists, not a fresh scan).
    qc = _QC(); a = _cand(qc, "AAA", 100.0); _run(qc, ["AAA"])
    b = _cand(qc, "BBB", 50.0); _run(qc, ["BBB"])
    assert a in qc._armed and b in qc._armed


def test_no_candidates_no_write():
    qc = _QC(); _run(qc, [])
    assert qc._armed == {}
