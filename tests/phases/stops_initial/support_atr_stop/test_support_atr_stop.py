"""SupportAtrStop: stamps max(kijun, kijun+atr*mult) for invested positions (the C swap)."""
from datetime import datetime
from engine.context import PhaseContext
from phases.stops_initial.support_atr_stop.support_atr_stop import SupportAtrStop


class _Cur:
    def __init__(self, v): self.current = type("C", (), {"value": v})()
    is_ready = True
class _DIchi:
    def __init__(self, kijun): self.kijun = _Cur(kijun); self.is_ready = True
class _ATR:
    def __init__(self, v): self.current = type("C", (), {"value": v})(); self.is_ready = True
class _Sym:
    def __init__(self, v): self.value = v
    def __hash__(self): return hash(self.value)
    def __eq__(self, o): return isinstance(o, _Sym) and o.value == self.value
class _Hold:
    def __init__(self, inv): self.invested = inv
class _QC:
    def __init__(self): self._active = set(); self.portfolio = {}; self._indicators = {}


def _run(name, inv, kijun, atr, mult=0.5):
    qc = _QC(); s = _Sym(name); qc._active.add(s); qc.portfolio[s] = _Hold(inv)
    qc._indicators[s] = {"d_ichi": _DIchi(kijun), "atr": _ATR(atr)}
    SupportAtrStop(SupportAtrStop.Params(atr_mult=mult), logger=None).evaluate(PhaseContext(qc=qc, time=datetime(2025, 1, 2), data=None))
    return {x.value: v for x, v in qc._initial_stops.items()}


def test_stamps_kijun_plus_atr_cushion():
    assert _run("AAA", True, 100.0, 4.0, 0.5) == {"AAA": 102.0}  # max(100, 100+2)


def test_skips_uninvested():
    assert _run("BBB", False, 100.0, 4.0) == {}


def test_differs_from_cloud_bottom_module():
    # SupportAtrStop level (kijun-based) != CloudBottomStop level (senkou-min) — the A-vs-C swap distinction
    assert _run("CCC", True, 100.0, 0.0, 0.5) == {"CCC": 100.0}  # no ATR → kijun floor
