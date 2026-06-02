"""#339 RUN R — Rotation: free a cash-locked slot by full-exiting the weakest WEAKENING held
position when a fresh candidate out-scores it by margin. Never rotates a trending winner.
Constructor: (Params(...), logger=None)."""
from datetime import datetime

from engine.context import PhaseContext
from phases.exit.rotation.rotation import Rotation


class _Sym:
    def __init__(self, v):
        self.value = v

    def __hash__(self):
        return hash(self.value)

    def __eq__(self, o):
        return isinstance(o, _Sym) and o.value == self.value


class _Ichi:
    def __init__(self, tenkan=100.0, ready=True):
        self.is_ready = ready
        self.tenkan = type("V", (), {"current": type("C", (), {"value": tenkan})()})()


class _Holding:
    def __init__(self, qty=100):
        self.invested = True
        self.quantity = qty


class _Sec:
    def __init__(self, close):
        self.close = close


class _Portfolio(dict):
    def __init__(self, cash, total, holdings):
        super().__init__(holdings)
        self.cash = cash
        self.total_portfolio_value = total

    def items(self):
        return dict.items(self)


class _QC:
    def __init__(self, cash, total, holdings, meta, snap, ind, sec):
        self.portfolio = _Portfolio(cash, total, holdings)
        self._position_meta = meta
        self._candidate_snapshot = snap
        self._indicators = ind
        self.securities = sec
        self.logged = []

    def log(self, m):
        self.logged.append(m)


def _run(qc, margin=1.0):
    ctx = PhaseContext(qc=qc, time=datetime(2025, 6, 16), data=None)
    res = Rotation(Rotation.Params(margin=margin), logger=None).evaluate(ctx)
    return res, ctx.bar_state.exit_intents


# held: LAG (score 6, below tenkan = weakening) + WIN (score 8). new candidate NEW score 8.
def _scene(cash, lag_close=90.0, lag_tenkan=100.0, lag_in_snap=False, lag_score=6, new_score=8):
    lag, win, new = _Sym("LAG"), _Sym("WIN"), _Sym("NEW")
    holdings = {lag: _Holding(100), win: _Holding(100)}
    meta = {lag: {"decision_score": lag_score}, win: {"decision_score": 8}}
    snap = {new: {"score": new_score}}
    if lag_in_snap:
        snap[lag] = {"score": lag_score}
    ind = {lag: {"d_ichi": _Ichi(tenkan=lag_tenkan)}, win: {"d_ichi": _Ichi(tenkan=50.0)}}
    sec = {lag: _Sec(lag_close), win: _Sec(200.0)}
    return _QC(cash, 100000.0, holdings, meta, snap, ind, sec)


def test_cash_available_no_rotation():
    # cash 20k >= 10% of 100k → fundable → no rotation
    res, intents = _run(_scene(cash=20000.0))
    assert res.facts["rotations"] == 0 and len(intents) == 0


def test_rotates_weakest_weakening_when_outscored():
    # cash 100 (exhausted); NEW(8) > LAG(6)+1.0; LAG below tenkan (90<100) → ROTATE out LAG
    res, intents = _run(_scene(cash=100.0))
    assert res.facts["rotations"] == 1
    assert len(intents) == 1 and intents[0].ticker == "LAG" and intents[0].qty == -100


def test_no_rotation_when_not_outscored_by_margin():
    # NEW(7) vs LAG(6): 7 > 6+1.0 is False → no rotation
    res, intents = _run(_scene(cash=100.0, new_score=7))
    assert res.facts["rotations"] == 0 and len(intents) == 0


def test_never_rotates_trending_winner():
    # LAG out-scored AND cash-exhausted, BUT LAG is ABOVE tenkan (110>100) and still in snapshot →
    # not weakening → do NOT rotate (never dump a trending name).
    res, intents = _run(_scene(cash=100.0, lag_close=110.0, lag_tenkan=100.0, lag_in_snap=True))
    assert res.facts["rotations"] == 0 and len(intents) == 0


def test_weakening_via_snapshot_dropout():
    # LAG ABOVE tenkan (110>100) but DROPPED OUT of today's winners (not in snap) = decayed → weakening
    res, intents = _run(_scene(cash=100.0, lag_close=110.0, lag_tenkan=100.0, lag_in_snap=False))
    assert res.facts["rotations"] == 1 and intents[0].ticker == "LAG"


def test_no_new_candidates_no_rotation():
    qc = _scene(cash=100.0)
    qc._candidate_snapshot = {}  # no fresh candidates
    res, intents = _run(qc)
    assert res.facts["rotations"] == 0 and len(intents) == 0


def test_blocked_always_false():
    res, _ = _run(_scene(cash=100.0))
    assert res.blocked is False
