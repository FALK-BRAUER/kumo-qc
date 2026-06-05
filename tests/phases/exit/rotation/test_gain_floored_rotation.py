"""#345/#363 GainFlooredRotation — the gain-floored rotation tournament (R1/R2/R3). The TEETH: a
held name is evictable ONLY if in GAIN (close > entry_price); a consolidating-from-loss carrier is
NEVER evicted (the #341 floor-cutting failure mode the gain-floor prevents). Constructor:
(Params(variant=...), logger=None)."""
from datetime import datetime

from engine.context import PhaseContext
from phases.exit.rotation.gain_floored_rotation import GainFlooredRotation


class _Sym:
    def __init__(self, v): self.value = v
    def __hash__(self): return hash(self.value)
    def __eq__(self, o): return isinstance(o, _Sym) and o.value == self.value


class _Ichi:
    def __init__(self, tenkan=100.0, ready=True):
        self.is_ready = ready
        self.tenkan = type("V", (), {"current": type("C", (), {"value": tenkan})()})()


class _Holding:
    def __init__(self, qty=100): self.invested = True; self.quantity = qty


class _Sec:
    def __init__(self, close): self.close = close


class _Portfolio(dict):
    def __init__(self, cash, total, holdings):
        super().__init__(holdings); self.cash = cash; self.total_portfolio_value = total
    def items(self): return dict.items(self)


class _QC:
    def __init__(self, cash, total, holdings, meta, snap, ind, sec):
        self.portfolio = _Portfolio(cash, total, holdings)
        self._position_meta = meta; self._candidate_snapshot = snap
        self._indicators = ind; self.securities = sec; self.logged = []
    def log(self, m): self.logged.append(m)


def _run(qc, variant="R1", margin=1.0):
    ctx = PhaseContext(qc=qc, time=datetime(2025, 6, 16), data=None)
    res = GainFlooredRotation(GainFlooredRotation.Params(variant=variant, margin=margin), logger=None).evaluate(ctx)
    return res, ctx.bar_state.exit_intents, ctx.bar_state.add_intents


def _scene(cash=100.0, lag_close=90.0, lag_entry=80.0, lag_tenkan=100.0, lag_in_snap=False,
           lag_score=6, new_score=8):
    """LAG (the weakest, weakening) + WIN (strong, in gain). lag_entry sets LAG's gain/loss vs lag_close."""
    lag, win, new = _Sym("LAG"), _Sym("WIN"), _Sym("NEW")
    holdings = {lag: _Holding(100), win: _Holding(100)}
    meta = {lag: {"decision_score": lag_score, "entry_price": lag_entry},
            win: {"decision_score": 8, "entry_price": 100.0}}  # WIN close 200 > entry 100 = in gain
    # WIN (the strong held) stays in the snapshot = still a signal winner → NOT weakening (a held name
    # drops from snap only when its score decays). NEW is the fresh candidate.
    snap = {new: {"score": new_score}, win: {"score": 8}}
    if lag_in_snap:
        snap[lag] = {"score": lag_score}
    ind = {lag: {"d_ichi": _Ichi(tenkan=lag_tenkan)}, win: {"d_ichi": _Ichi(tenkan=50.0)}}
    sec = {lag: _Sec(lag_close), win: _Sec(200.0)}
    return _QC(cash, 100000.0, holdings, meta, snap, ind, sec)


# ── R1: evict-on-better-candidate (gain-floored) ──

def test_r1_rotates_gain_positive_weakening_outscored():
    # LAG in GAIN (close 90 > entry 80), weakening (90<tenkan 100), out-scored (NEW 8 > LAG 6) → EVICT.
    res, exits, _ = _run(_scene(), variant="R1")
    assert res.facts["rotations"] == 1 and len(exits) == 1 and exits[0].ticker == "LAG" and exits[0].qty == -100


def test_r1_GAINFLOOR_protects_loss_carrier():
    # THE TEETH: same scene but LAG in LOSS (close 90 < entry 100) — a consolidating-from-loss carrier.
    # Plain rotation would evict it (weakest, weakening, out-scored); gain-floored MUST NOT. WIN (the
    # only gain-positive held, score 8) is not out-scored by NEW(8) → 0 rotations. The #341 fix.
    res, exits, _ = _run(_scene(lag_close=90.0, lag_entry=100.0), variant="R1")
    assert res.facts["rotations"] == 0 and len(exits) == 0, "must NOT evict a consolidating-from-loss carrier"


def test_r1_no_rotation_cash_available():
    res, exits, _ = _run(_scene(cash=20000.0), variant="R1")  # 20k >= 10% of 100k
    assert res.facts["rotations"] == 0 and len(exits) == 0


def test_r1_no_rotation_edge_below_margin():
    res, exits, _ = _run(_scene(new_score=6), variant="R1")  # NEW 6 vs LAG 6 → edge 0 < 1
    assert res.facts["rotations"] == 0


# ── R2: lock-the-weakening-gain (no candidate gate) ──

def test_r2_locks_weakening_gain_no_candidate_needed():
    # LAG in GAIN (90>80) + weakening (not in snap → decayed) → evict to lock the gain. R2 needs no
    # new candidate (WIN stays — in snap + above tenkan = not weakening).
    res, exits, _ = _run(_scene(), variant="R2")
    assert res.facts["rotations"] == 1 and exits[0].ticker == "LAG"


def test_r2_GAINFLOOR_protects_weakening_loss_carrier():
    # TEETH: LAG is WEAKENING but in LOSS (close 90 < entry 100) — the round-tripping name plain-R2
    # would dump. Gain-floor protects it; WIN (the only gain-positive) is not weakening → 0 rotations.
    res, exits, _ = _run(_scene(lag_close=90.0, lag_entry=100.0), variant="R2")
    assert res.facts["rotations"] == 0 and len(exits) == 0


def test_r2_does_not_evict_non_weakening_gain():
    # a gain-positive held that's NOT weakening (above tenkan + in snapshot) → keep it (let it run).
    res, exits, _ = _run(_scene(lag_close=110.0, lag_tenkan=100.0, lag_in_snap=True), variant="R2")
    assert res.facts["rotations"] == 0


# ── R3: full-exit-redeploy-to-strongest ──

def test_r3_evicts_and_redeploys_into_strongest():
    # R3 = R1 evict + an ADD to the STRONGEST gain-positive held (WIN, score 8). The freed laggard
    # capital is redeployed into the best winner (controlled concentration).
    res, exits, adds = _run(_scene(), variant="R3")
    assert res.facts["rotations"] == 1 and exits[0].ticker == "LAG"
    assert len(adds) == 1 and adds[0].ticker == "WIN" and adds[0].qty >= 1


def test_r3_gainfloor_protects_loss_carrier_no_evict_no_redeploy():
    res, exits, adds = _run(_scene(lag_close=90.0, lag_entry=100.0), variant="R3")
    assert res.facts["rotations"] == 0 and len(exits) == 0 and len(adds) == 0


def test_blocked_always_false():
    res, _, _ = _run(_scene(), variant="R1")
    assert res.blocked is False
