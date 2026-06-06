"""GainScaleOut — partial scale-out at gain milestones, on ALL positions (inverse of PgProfitTake's
monster-exempt fader-trim). Teeth: trims at milestone crossing, ONCE per milestone, NO monster-exempt,
partial-never-full, multi-milestone gap, state reset/GC. Constructor: (Params(...), logger=None)."""
from datetime import datetime, timedelta

from engine.context import PhaseContext
from phases.profit.gain_scale_out.gain_scale_out import GainScaleOut

_NOW = datetime(2025, 6, 1)


class _Sym:
    def __init__(self, v): self.value = v
    def __hash__(self): return hash(self.value)
    def __eq__(self, o): return isinstance(o, _Sym) and o.value == self.value


class _Hold:
    def __init__(self, qty=100): self.invested = True; self.quantity = qty


class _Sec:
    def __init__(self, close): self.close = close; self.high = close


class _QC:
    def __init__(self):
        self.portfolio = {}; self.securities = {}; self._position_meta = {}; self.logged = []
    def log(self, m): self.logged.append(m)


def _add(qc, name, close, entry, qty=100):
    s = _Sym(name)
    qc.portfolio[s] = _Hold(qty); qc.securities[s] = _Sec(close)
    qc._position_meta[s] = {"entry_price": entry, "entry_date": _NOW - timedelta(days=30)}
    return s


def _run(qc, **kw):
    p = GainScaleOut(GainScaleOut.Params(**kw), logger=None)
    ctx = PhaseContext(qc=qc, time=_NOW, data=None)
    p.evaluate(ctx)
    return ctx.bar_state.trim_intents


def test_trims_at_first_milestone():
    # +50% gain (close 150, entry 100) crosses the +50% milestone → trim 25% of 100 = 25.
    qc = _QC(); _add(qc, "WIN", close=150.0, entry=100.0, qty=100)
    trims = _run(qc, milestones=(0.50, 1.00, 1.50), trim_frac=0.25)
    assert len(trims) == 1 and trims[0].ticker == "WIN" and trims[0].qty == -25


def test_NOT_monster_exempt_the_whole_point():
    # a huge proved monster (+200%) IS trimmed — the INVERSE of PgProfitTake. The data says monsters
    # give back half their peak; scale-out banks a slice. (PgProfitTake would EXEMPT this; we must NOT.)
    qc = _QC(); _add(qc, "MONSTER", close=300.0, entry=100.0, qty=100)
    trims = _run(qc, milestones=(0.50, 1.00, 1.50), trim_frac=0.25)
    assert len(trims) == 1, "scale-out must trim monsters too (the inverse of the prover-exempt trim)"


def test_fires_once_per_milestone_not_every_bar():
    # cross +50% → trim once. SAME bar-state re-eval at the same gain → no second trim (milestone fired).
    qc = _QC(); s = _add(qc, "WIN", close=150.0, entry=100.0, qty=100)
    p = GainScaleOut(GainScaleOut.Params(milestones=(0.50, 1.00), trim_frac=0.25), logger=None)
    c1 = PhaseContext(qc=qc, time=_NOW, data=None); p.evaluate(c1)
    assert len(c1.bar_state.trim_intents) == 1
    c2 = PhaseContext(qc=qc, time=_NOW, data=None); p.evaluate(c2)   # still +50%, milestone already fired
    assert c2.bar_state.trim_intents == [], "must not re-trim a milestone already fired"


def test_gap_crosses_multiple_milestones_one_trim_each_marked():
    # a gap to +160% clears +50/+100/+150 at once → ONE trim this bar, all three marked (next bar no more).
    qc = _QC(); s = _add(qc, "GAP", close=260.0, entry=100.0, qty=100)
    p = GainScaleOut(GainScaleOut.Params(milestones=(0.50, 1.00, 1.50), trim_frac=0.25), logger=None)
    c1 = PhaseContext(qc=qc, time=_NOW, data=None); p.evaluate(c1)
    assert len(c1.bar_state.trim_intents) == 1                       # one trim event this bar
    assert qc._scaleout_state[s]["fired"] == {0.50, 1.00, 1.50}      # all crossed marked
    c2 = PhaseContext(qc=qc, time=_NOW, data=None); p.evaluate(c2)
    assert c2.bar_state.trim_intents == []                           # nothing left to fire


def test_partial_never_full():
    # trim_frac applied to current qty → a residual always remains (never a full exit; #379 Part A).
    qc = _QC(); _add(qc, "WIN", close=200.0, entry=100.0, qty=100)
    trims = _run(qc, milestones=(0.50,), trim_frac=0.33)
    assert trims[0].qty == -33 and abs(trims[0].qty) < 100


def test_below_first_milestone_no_trim():
    qc = _QC(); _add(qc, "FLAT", close=140.0, entry=100.0, qty=100)  # +40% < +50% → no trim
    assert _run(qc, milestones=(0.50,), trim_frac=0.25) == []


def test_subshare_trim_marks_milestone_no_busy_retry():
    # qty 3, trim_frac 0.25 → int(0.75)=0 → no intent, but milestone MARKED so it doesn't retry forever.
    qc = _QC(); s = _add(qc, "TINY", close=150.0, entry=100.0, qty=3)
    trims = _run(qc, milestones=(0.50,), trim_frac=0.25)
    assert trims == [] and 0.50 in qc._scaleout_state[s]["fired"]


def test_state_reset_on_reentry_and_gc_on_close():
    qc = _QC(); s = _add(qc, "WIN", close=150.0, entry=100.0, qty=100)
    _run(qc, milestones=(0.50,), trim_frac=0.25)
    assert 0.50 in qc._scaleout_state[s]["fired"]
    # re-entry (new entry_date) → schedule resets so the new position can scale out afresh
    qc._position_meta[s]["entry_date"] = _NOW
    _run(qc, milestones=(0.50,), trim_frac=0.25)
    assert qc._scaleout_state[s]["entry_date"] == _NOW
    # close → GC (no stale schedule leaking into a re-entry)
    qc.portfolio[s].invested = False
    _run(qc, milestones=(0.50,), trim_frac=0.25)
    assert s not in qc._scaleout_state


def test_freed_cash_logged_for_redeploy_instrumentation():
    qc = _QC(); _add(qc, "WIN", close=150.0, entry=100.0, qty=100)
    _run(qc, milestones=(0.50,), trim_frac=0.25)
    assert any("SCALE_OUT" in m and "freed~$" in m for m in qc.logged)
