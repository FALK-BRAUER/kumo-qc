"""#379-B PgProfitTake — the ASYMMETRIC prover-gate teeth: trim a NEVER-PROVED fader (free its cash),
EXEMPT every PROVED monster (≥+5% MFE → let it run, never cap it). Uses the SHARED prover state.
Constructor: (Params(variant=...), logger=None)."""
from datetime import datetime, timedelta

from engine.context import PhaseContext
from phases.profit.pg_profit_take.pg_profit_take import PgProfitTake

_NOW = datetime(2025, 3, 1)


class _Sym:
    def __init__(self, v): self.value = v
    def __hash__(self): return hash(self.value)
    def __eq__(self, o): return isinstance(o, _Sym) and o.value == self.value


class _Hold:
    def __init__(self, qty=100): self.invested = True; self.quantity = qty


class _Sec:
    def __init__(self, close, high=None): self.close = close; self.high = high if high is not None else close


class _Ichi:
    def __init__(self, tenkan=100.0, ready=True):
        self.is_ready = ready
        self.tenkan = type("V", (), {"current": type("C", (), {"value": tenkan})()})()


class _QC:
    def __init__(self):
        self.portfolio = {}; self.securities = {}; self._position_meta = {}; self._indicators = {}
        self._candidate_snapshot = {}; self.logged = []
    def log(self, m): self.logged.append(m)


def _add(qc, name, close, entry, qty=100, age_days=30, high=None, tenkan=100.0):
    s = _Sym(name)
    qc.portfolio[s] = _Hold(qty)
    qc.securities[s] = _Sec(close, high)
    qc._position_meta[s] = {"entry_price": entry, "entry_date": _NOW - timedelta(days=age_days)}
    qc._indicators[s] = {"d_ichi": _Ichi(tenkan)}
    return s


def _run(qc, variant="T1", **kw):
    p = PgProfitTake(PgProfitTake.Params(variant=variant, **kw), logger=None)
    ctx = PhaseContext(qc=qc, time=_NOW, data=None)
    p.evaluate(ctx)
    return ctx.bar_state.trim_intents


# ── T1 age-gated fader ──

def test_t1_trims_never_proved_aged_fader():
    # never proved (close 102 < entry×1.05=105), held 30d ≥ 20 → a fader → trim 50% (qty 100 → -50).
    qc = _QC(); s = _add(qc, "FADER", close=102.0, entry=100.0, qty=100, age_days=30)
    trims = _run(qc, "T1")
    assert len(trims) == 1 and trims[0].ticker == "FADER" and trims[0].qty == -50


def test_t1_PROVER_GATE_exempts_proved_monster():
    # THE TEETH (asymmetric): a PROVED monster (close 110 ≥ +5% MFE), even aged 30d, is EXEMPT — never
    # trimmed (trimming HOOD@+50% caps the run). A symmetric profit-take would clip it; the gate must not.
    qc = _QC(); s = _add(qc, "MONSTER", close=110.0, entry=100.0, qty=100, age_days=30)
    assert _run(qc, "T1") == [], "a PROVED monster must be EXEMPT from the profit-trim"


def test_t1_proves_on_intraday_high_exempt():
    # proved via the intraday HIGH (close 102 <105 but high 106 ≥105) → MFE proved → exempt (shared
    # prover MFE rule — a close-only prove would wrongly trim this runner).
    qc = _QC(); s = _add(qc, "RUNNER", close=102.0, entry=100.0, qty=100, age_days=30, high=106.0)
    assert _run(qc, "T1") == []


def test_t1_does_not_trim_young_fader():
    # never proved but only 10d old (< 20) → not yet a fader → no trim (give it time to prove).
    qc = _QC(); s = _add(qc, "YOUNG", close=102.0, entry=100.0, qty=100, age_days=10)
    assert _run(qc, "T1") == []


def test_t1_partial_trim_keeps_residual_never_full():
    # trim_pct 0.50 of qty 100 = 50 (partial, not full) — a full trim is an EXIT (#379 Part A refuses it).
    qc = _QC(); s = _add(qc, "FADER", close=102.0, entry=100.0, qty=100, age_days=30)
    trims = _run(qc, "T1", trim_pct=0.50)
    assert trims[0].qty == -50 and abs(trims[0].qty) < 100


# ── T2 stalled fader ──

def test_t2_trims_never_proved_below_tenkan():
    # never proved + below daily Tenkan (close 102 < tenkan 105) → stalled fader → trim. No age gate.
    qc = _QC(); s = _add(qc, "STALL", close=102.0, entry=100.0, qty=100, age_days=5, tenkan=105.0)
    assert len(_run(qc, "T2")) == 1


def test_t2_PROVER_GATE_exempts_proved_below_tenkan():
    # proved monster below Tenkan (an en-route dip) → EXEMPT (the dip is the let-run cost, not a trim signal).
    qc = _QC(); s = _add(qc, "MONSTER", close=110.0, entry=100.0, qty=100, age_days=5, tenkan=115.0)
    # close 110 ≥ entry×1.05 → proved; below tenkan 115 → would trim if not for the gate
    assert _run(qc, "T2") == []


# ── T3 candidate-driven (stalled never-proved + a fresh candidate needs the cash) ──

def test_t3_trims_never_proved_stalled_when_candidate_present():
    qc = _QC(); s = _add(qc, "STALL", close=102.0, entry=100.0, qty=100, age_days=5, tenkan=105.0)
    qc._candidate_snapshot = {_Sym("NEWNAME"): {"score": 8}}  # a fresh candidate needs the cash
    assert len(_run(qc, "T3")) == 1


def test_t3_no_trim_without_fresh_candidate():
    qc = _QC(); s = _add(qc, "STALL", close=102.0, entry=100.0, qty=100, age_days=5, tenkan=105.0)
    qc._candidate_snapshot = {}  # no fresh candidate → no cash needed → no trim
    assert _run(qc, "T3") == []


def test_t3_PROVER_GATE_exempts_proved_with_candidate():
    qc = _QC(); s = _add(qc, "MONSTER", close=110.0, entry=100.0, qty=100, age_days=5, tenkan=115.0)
    qc._candidate_snapshot = {_Sym("NEWNAME"): {"score": 8}}
    assert _run(qc, "T3") == [], "proved monster EXEMPT even with a fresh candidate wanting the cash"


# ── instrumentation + rounding ──

def test_redeploy_instrumentation_logs_freed_cash():
    # the decisive HQ metric: each trim logs PROFIT_TRIM_* with the freed-cash figure.
    qc = _QC(); s = _add(qc, "FADER", close=102.0, entry=100.0, qty=100, age_days=30)
    _run(qc, "T1")
    assert any("PROFIT_TRIM_T1" in m and "freed~$" in m for m in qc.logged)


def test_trim_rounding_skips_sub_one_share():
    # trim_pct 0.50 on qty 1 → int(0.5) = 0 → no intent (nothing to trim).
    qc = _QC(); s = _add(qc, "TINY", close=102.0, entry=100.0, qty=1, age_days=30)
    assert _run(qc, "T1", trim_pct=0.50) == []
