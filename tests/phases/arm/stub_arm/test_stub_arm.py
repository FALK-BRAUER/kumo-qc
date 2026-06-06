"""StubArm (M1 Stage-1) — reproduces lean_entry._capture_candidate_snapshot: writes the daily SIGNAL
winners (bar_state.sized_orders) into qc._armed {sym: {zone, daily_kijun, armed_date}}, FRESH each day
(not persist), GATED to nothing when bar_state.bar_blocked (#277), zone == securities[sym].price,
skips a winner that is unsubscribed or has a cold daily Ichimoku. Engine never computes the zone.
Constructor: (Params(), logger=None)."""
from datetime import datetime
from engine.context import PhaseContext, OrderIntent
from phases.arm.stub_arm.stub_arm import StubArm


class _Sym:
    def __init__(self, v): self.value = v
    def __hash__(self): return hash(self.value)
    def __eq__(self, o): return isinstance(o, _Sym) and o.value == self.value


class _Cur:
    def __init__(self, v): self.value = v


class _Kijun:
    def __init__(self, v): self.current = _Cur(v)


class _DIchi:
    def __init__(self, kijun, ready=True): self.kijun = _Kijun(kijun); self.is_ready = ready


class _Sec:
    def __init__(self, price): self.price = price


class _QC:
    def __init__(self): self.securities = {}; self._active = set(); self._armed = {}; self._indicators = {}


def _cand(qc, name, price, kijun=None, ready=True):
    s = _Sym(name)
    qc._active.add(s)
    qc.securities[s] = _Sec(price)
    qc._indicators[s] = {"d_ichi": _DIchi(price - 5.0 if kijun is None else kijun, ready)}
    return s


def _run(qc, tickers, blocked=False, day="2025-01-02"):
    p = StubArm(StubArm.Params(), logger=None)
    ctx = PhaseContext(qc=qc, time=datetime.strptime(day, "%Y-%m-%d"), data=None)
    ctx.bar_state.bar_blocked = blocked
    ctx.bar_state.sized_orders = [
        OrderIntent(ticker=t, qty=0, price=0.0, stop=0.0, module="s", risk_dollars=0.0) for t in tickers
    ]
    p.evaluate(ctx)


def test_arms_winner_with_zone_and_kijun():
    qc = _QC(); s = _cand(qc, "AAA", price=100.0, kijun=92.0)
    _run(qc, ["AAA"])
    assert s in qc._armed
    assert qc._armed[s]["zone"] == 100.0          # == snapshot signal_price (.price)
    assert qc._armed[s]["daily_kijun"] == 92.0
    assert qc._armed[s]["armed_date"] == "2025-01-02"


def test_fresh_rebuild_drops_stale_name():
    # Stage-1 parity: FRESH each day (matches _candidate_snapshot rebuild), NOT persist.
    qc = _QC(); a = _cand(qc, "AAA", 100.0); _run(qc, ["AAA"], day="2025-01-02")
    b = _cand(qc, "BBB", 50.0); _run(qc, ["BBB"], day="2025-01-03")
    assert b in qc._armed and a not in qc._armed   # AAA dropped from today's winners → gone


def test_regime_blocked_arms_nothing():
    qc = _QC(); _cand(qc, "AAA", 100.0)
    _run(qc, ["AAA"], blocked=True)
    assert qc._armed == {}                          # #277 regime gate → winners=[] → 0 armed


def test_skips_cold_dichi():
    qc = _QC(); _cand(qc, "AAA", 100.0, ready=False)
    _run(qc, ["AAA"])
    assert qc._armed == {}                          # cold daily thesis → never arm half-formed


def test_skips_unsubscribed_winner():
    qc = _QC()                                      # AAA is a winner but never subscribed (_active/securities)
    _run(qc, ["AAA"])
    assert qc._armed == {}


def test_no_candidates_no_write():
    qc = _QC(); _run(qc, [])
    assert qc._armed == {}
