"""CloudBottomStop: stamps min(SenkouA,B) for invested positions, skips uninvested/cold/already-stopped."""
from datetime import datetime
from engine.context import PhaseContext
from phases.stops_initial.cloud_bottom_stop.cloud_bottom_stop import CloudBottomStop, cloud_bottom


class _Cur:
    def __init__(self, v): self.current = type("C", (), {"value": v})()
class _DIchi:
    def __init__(self, a, b, ready=True): self.senkou_a = _Cur(a); self.senkou_b = _Cur(b); self.is_ready = ready
class _Sym:
    def __init__(self, v): self.value = v
    def __hash__(self): return hash(self.value)
    def __eq__(self, o): return isinstance(o, _Sym) and o.value == self.value
class _Hold:
    def __init__(self, inv): self.invested = inv
class _QC:
    def __init__(self): self._active = set(); self.portfolio = {}; self._indicators = {}


def _qc(specs):
    qc = _QC()
    for name, inv, a, b in specs:
        s = _Sym(name); qc._active.add(s); qc.portfolio[s] = _Hold(inv)
        qc._indicators[s] = {"d_ichi": _DIchi(a, b)}
    return qc


def _run(qc):
    CloudBottomStop(CloudBottomStop.Params(), logger=None).evaluate(PhaseContext(qc=qc, time=datetime(2025, 1, 2), data=None))
    return qc._initial_stops


def test_cloud_bottom_is_min_senkou():
    assert cloud_bottom(_DIchi(110.0, 95.0)) == 95.0


def test_stamps_invested_position():
    qc = _qc([("AAA", True, 110.0, 95.0)])
    assert {s.value: v for s, v in _run(qc).items()} == {"AAA": 95.0}


def test_skips_uninvested():
    qc = _qc([("BBB", False, 110.0, 95.0)])
    assert _run(qc) == {}


def test_idempotent_already_stopped():
    qc = _qc([("AAA", True, 110.0, 95.0)])
    _run(qc); r1 = dict(qc._initial_stops)
    _run(qc)  # second pass: AAA already stopped → unchanged
    assert qc._initial_stops == r1
