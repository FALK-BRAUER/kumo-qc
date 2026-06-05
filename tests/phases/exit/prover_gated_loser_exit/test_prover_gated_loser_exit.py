"""#339-RUN1 ProverGatedLoserExit — the PROVER-GATE teeth: a position that PROVED (ever >= +5% above
entry) is EXEMPT from the loser-cut even in drawdown (potential monster → let it run); a NEVER-PROVED
loser is cut earlier. E1 fixed-% / E2 weekly-Kijun / E3 weekly-cloud-top. Constructor:
(Params(variant=...), logger=None)."""
from datetime import datetime

from engine.context import PhaseContext
from phases.exit.prover_gated_loser_exit.prover_gated_loser_exit import ProverGatedLoserExit

_ENTRY = datetime(2025, 1, 2)


class _Sym:
    def __init__(self, v): self.value = v
    def __hash__(self): return hash(self.value)
    def __eq__(self, o): return isinstance(o, _Sym) and o.value == self.value


class _WIchi:
    def __init__(self, kijun=100.0, sa=100.0, sb=100.0, ready=True):
        self.is_ready = ready
        mk = lambda x: type("V", (), {"current": type("C", (), {"value": x})()})()
        self.kijun, self.senkou_a, self.senkou_b = mk(kijun), mk(sa), mk(sb)


class _Hold:
    def __init__(self, qty=100): self.invested = True; self.quantity = qty


class _Sec:
    def __init__(self, close, high=None): self.close = close; self.high = high if high is not None else close


class _QC:
    def __init__(self):
        self.portfolio = {}; self.securities = {}; self._indicators = {}
        self._position_meta = {}; self.logged = []
    def log(self, m): self.logged.append(m)


def _sym(n="LOSER"): return _Sym(n)


def _setup(close, entry, w=None):
    qc = _QC(); s = _sym()
    qc.portfolio[s] = _Hold(100)
    qc.securities[s] = _Sec(close)
    qc._indicators[s] = {"w_ichi": w or _WIchi()}
    qc._position_meta[s] = {"entry_price": entry, "entry_date": _ENTRY}
    return qc, s


def _phase(variant="E1"):
    return ProverGatedLoserExit(ProverGatedLoserExit.Params(variant=variant), logger=None)


def _run(p, qc):
    ctx = PhaseContext(qc=qc, time=datetime(2025, 3, 1), data=None)
    p.evaluate(ctx)
    return ctx.bar_state.exit_intents


# ── E1 fixed-% ──

def test_e1_cuts_never_proved_loser_below_stop():
    # never proved (close 90 < entry×1.05) AND close 90 <= entry 100 × 0.92? no — 90 > 92. Push to -10%.
    p = _phase("E1"); qc, s = _setup(close=89.0, entry=100.0)  # -11%, never proved
    exits = _run(p, qc)
    assert len(exits) == 1 and exits[0].ticker == "LOSER" and exits[0].qty == -100


def test_e1_PROVER_GATE_exempts_proved_position_in_drawdown():
    # THE TEETH: the position PROVED earlier (first bar close 110 = +10% > +5%) → proved=True. Now it's
    # in DRAWDOWN (close 85 = -15%) — a plain hard-stop would cut it (the #374 runner-clip). Prover-gate
    # EXEMPTS it (potential monster) → NO cut.
    p = _phase("E1"); qc, s = _setup(close=110.0, entry=100.0)
    _run(p, qc)                                   # bar 1: +10% → proves
    qc.securities[s] = _Sec(85.0)                 # bar 2: -15% drawdown
    exits = _run(p, qc)
    assert exits == [], "a PROVED position in drawdown must be EXEMPT (potential monster, not clipped)"


def test_e1_does_not_cut_never_proved_small_loss_above_stop():
    # never proved but only -3% (above the -8% stop) → no cut yet.
    p = _phase("E1"); qc, s = _setup(close=97.0, entry=100.0)
    assert _run(p, qc) == []


def test_e1_does_not_cut_a_winner():
    # in profit (+8%, proves) → exempt → no cut.
    p = _phase("E1"); qc, s = _setup(close=108.0, entry=100.0)
    assert _run(p, qc) == []


# ── E2 weekly-Kijun ──

def test_e2_cuts_never_proved_below_weekly_kijun():
    # never proved (close 96 < +5%) AND close 96 < weekly Kijun 100 → cut.
    p = _phase("E2"); qc, s = _setup(close=96.0, entry=100.0, w=_WIchi(kijun=100.0))
    assert len(_run(p, qc)) == 1


def test_e2_PROVER_GATE_exempts_proved_below_kijun():
    # proved earlier (+10%), now below weekly Kijun → EXEMPT (teeth).
    p = _phase("E2"); qc, s = _setup(close=110.0, entry=100.0, w=_WIchi(kijun=105.0))
    _run(p, qc)                                   # proves at +10%
    qc.securities[s] = _Sec(102.0)                # below Kijun 105 but proved
    assert _run(p, qc) == []


def test_e2_no_cut_above_weekly_kijun():
    p = _phase("E2"); qc, s = _setup(close=101.0, entry=100.0, w=_WIchi(kijun=100.0))  # above Kijun
    assert _run(p, qc) == []


def test_e2_cold_weekly_no_cut():
    p = _phase("E2"); qc, s = _setup(close=96.0, entry=100.0, w=_WIchi(kijun=100.0, ready=False))
    assert _run(p, qc) == []


# ── E3 weekly-cloud-top (earlier than the champion's cloud-bottom) ──

def test_e3_cuts_never_proved_below_weekly_cloud_top():
    # cloud top = max(sa 95, sb 102) = 102; close 100 < 102 → cut (never proved). Note: champion's
    # cloud-BOTTOM = min = 95; close 100 > 95 would NOT cut → E3 cuts EARLIER. That's the point.
    p = _phase("E3"); qc, s = _setup(close=100.0, entry=100.0, w=_WIchi(sa=95.0, sb=102.0))
    assert len(_run(p, qc)) == 1


def test_e3_PROVER_GATE_exempts_proved_below_cloud_top():
    p = _phase("E3"); qc, s = _setup(close=110.0, entry=100.0, w=_WIchi(sa=95.0, sb=108.0))
    _run(p, qc)                                   # proves +10%
    qc.securities[s] = _Sec(104.0)                # below cloud-top 108 but proved
    assert _run(p, qc) == []


def test_proves_on_intraday_high_not_just_close():
    # review #339-RUN1: a fast monster ran +6% INTRADAY (high 106) but closed below +5% (close 102) →
    # must still PROVE (max favorable excursion) → exempt in a later drawdown. A close-only prove would
    # false-cut it (the failure mode the gate prevents).
    p = _phase("E1"); qc, s = _setup(close=102.0, entry=100.0)
    qc.securities[s] = _Sec(102.0, high=106.0)
    _run(p, qc)                                    # proves via the intraday high
    qc.securities[s] = _Sec(85.0)                  # -15% drawdown
    assert _run(p, qc) == [], "an intraday-proved (+5% on high) position must be EXEMPT in drawdown"


def test_proved_flag_survives_cold_indicator_bar():
    # review #339-RUN1: a transient cold-indicator bar (still invested) must NOT erase the proved flag
    # (else a previously-proved monster gets re-treated as never-proved → false-cut on recovery).
    p = _phase("E1"); qc, s = _setup(close=110.0, entry=100.0)
    _run(p, qc)                                    # proves +10%
    assert qc._prover_state[s]["proved"] is True   # shared prover state (was p._proved before the migration)
    qc._indicators.pop(s)                          # cold bar: indicator missing (still invested)
    _run(p, qc)
    assert s in qc._prover_state and qc._prover_state[s]["proved"] is True, "cold bar must not erase the proved flag"
    qc._indicators[s] = {"w_ichi": _WIchi()}; qc.securities[s] = _Sec(85.0)  # recover + drawdown
    assert _run(p, qc) == [], "still exempt — the proved flag survived the cold bar"


def test_blocked_false_and_gc_on_close():
    p = _phase("E1"); qc, s = _setup(close=89.0, entry=100.0)
    res_intents = _run(p, qc)
    assert len(res_intents) == 1
    # position closes → state GC'd (no stale proved flag leaking into a re-entry)
    qc.portfolio[s].invested = False
    _run(p, qc)
    assert s not in qc._prover_state   # shared prover state GC'd on close
