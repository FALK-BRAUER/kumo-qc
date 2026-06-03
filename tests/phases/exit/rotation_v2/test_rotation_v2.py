"""#339 RotationV2 — recycle stalled-GREEN (PnL>0, below-Tenkan, above-Kijun); PROTECT trending
(above-Tenkan) + underwater (never book a loss) + broken (below-Kijun). Constructor (Params, logger=None)."""
from datetime import datetime

from engine.context import PhaseContext
from phases.exit.rotation_v2.rotation_v2 import RotationV2


class _Sym:
    def __init__(self, v):
        self.value = v

    def __hash__(self):
        return hash(self.value)

    def __eq__(self, o):
        return isinstance(o, _Sym) and o.value == self.value


class _Ichi:
    def __init__(self, tenkan, kijun):
        self.is_ready = True
        self.tenkan = type("V", (), {"current": type("C", (), {"value": tenkan})()})()
        self.kijun = type("V", (), {"current": type("C", (), {"value": kijun})()})()


class _Holding:
    def __init__(self, qty=100):
        self.invested = True
        self.quantity = qty


class _Sec:
    def __init__(self, close):
        self.close = close


class _PF(dict):
    def __init__(self, cash, total, holdings):
        super().__init__(holdings)
        self.cash = cash
        self.total_portfolio_value = total

    def items(self):
        return dict.items(self)


class _QC:
    def __init__(self, cash, holdings, meta, snap, ind, sec):
        self.portfolio = _PF(cash, 100000.0, holdings)
        self._position_meta = meta
        self._candidate_snapshot = snap
        self._indicators = ind
        self.securities = sec
        self.logged = []

    def log(self, m):
        self.logged.append(m)


def _run(qc, margin=1.0, min_hold=0):
    ctx = PhaseContext(qc=qc, time=datetime(2025, 6, 16), data=None)
    res = RotationV2(RotationV2.Params(margin=margin, min_hold_days=min_hold), logger=None).evaluate(ctx)
    return res, ctx.bar_state.exit_intents


def _scene(cash, lag_close, lag_entry, lag_tenkan, lag_kijun, lag_score=6, new_score=8):
    """LAG = the candidate-to-recycle; WIN = a protected trending winner; NEW = fresh signal."""
    lag, win, new = _Sym("LAG"), _Sym("WIN"), _Sym("NEW")
    qc = _QC(cash,
             {lag: _Holding(100), win: _Holding(100)},
             {lag: {"decision_score": lag_score, "entry_price": lag_entry, "entry_date": datetime(2025, 1, 2)},
              win: {"decision_score": 8, "entry_price": 50.0, "entry_date": datetime(2025, 1, 2)}},
             {new: {"score": new_score}},
             {lag: {"d_ichi": _Ichi(lag_tenkan, lag_kijun)}, win: {"d_ichi": _Ichi(250.0, 240.0)}},
             {lag: _Sec(lag_close), win: _Sec(300.0)})  # WIN close 300 >> tenkan 250 = trending, protected
    return qc


def test_evicts_stalled_green():
    # LAG: entry 80, close 95 (PnL +19%), tenkan 100 (below → stalled), kijun 90 (above → intact). EVICTABLE.
    res, intents = _run(_scene(100.0, lag_close=95.0, lag_entry=80.0, lag_tenkan=100.0, lag_kijun=90.0))
    assert res.facts["rotations"] == 1
    assert len(intents) == 1 and intents[0].ticker == "LAG" and intents[0].qty == -100


def test_protects_trending_above_tenkan():
    # LAG: close 105 >= tenkan 100 → trending → PROTECTED (the trail handles it), even though green + out-scored.
    res, intents = _run(_scene(100.0, lag_close=105.0, lag_entry=80.0, lag_tenkan=100.0, lag_kijun=90.0))
    assert res.facts["rotations"] == 0 and len(intents) == 0


def test_protects_underwater_never_books_loss():
    # LAG: close 75 < entry 80 (underwater) → PROTECTED (stops handle; rotation NEVER books a loss),
    # even though below tenkan + out-scored.
    res, intents = _run(_scene(100.0, lag_close=75.0, lag_entry=80.0, lag_tenkan=100.0, lag_kijun=70.0))
    assert res.facts["rotations"] == 0 and len(intents) == 0


def test_protects_broken_below_kijun():
    # LAG: green (close 95 > entry 80) + below tenkan 100 BUT close 95 <= kijun 96 → broken → PROTECTED (stops).
    res, intents = _run(_scene(100.0, lag_close=95.0, lag_entry=80.0, lag_tenkan=100.0, lag_kijun=96.0))
    assert res.facts["rotations"] == 0 and len(intents) == 0


def test_cash_available_no_rotation():
    res, intents = _run(_scene(20000.0, lag_close=95.0, lag_entry=80.0, lag_tenkan=100.0, lag_kijun=90.0))
    assert res.facts["rotations"] == 0


def test_min_hold_protects_fresh():
    # stalled-green but held < min_hold_days → protected (no churn on a fresh dip)
    res, intents = _run(_scene(100.0, lag_close=95.0, lag_entry=80.0, lag_tenkan=100.0, lag_kijun=90.0),
                        min_hold=10000)  # entry 2025-01-02, eval 2025-06-16 → ~165d; 10000 → protected
    assert res.facts["rotations"] == 0


def test_blocked_always_false():
    res, _ = _run(_scene(100.0, lag_close=95.0, lag_entry=80.0, lag_tenkan=100.0, lag_kijun=90.0))
    assert res.blocked is False


# ---- #364 tournament gates (gain_floor / adx_falling / no_new_high / evict_select=momentum) ----

class _Window:
    """RollingWindow mock: _Window([most_recent, ...]); count + [i] = i-th most recent."""
    def __init__(self, vals):
        self._v = list(vals)
        self.count = len(vals)

    def __getitem__(self, i):
        return self._v[i]


def _run_p(qc, params):
    ctx = PhaseContext(qc=qc, time=datetime(2025, 6, 16), data=None)
    res = RotationV2(params, logger=None).evaluate(ctx)
    return res, ctx.bar_state.exit_intents


def test_gain_floor_protects_below_threshold():
    # LAG green +18.75% (close95/entry80), stalled. gain_floor 10% → evictable; 25% → protected.
    qc = _scene(100.0, lag_close=95.0, lag_entry=80.0, lag_tenkan=100.0, lag_kijun=90.0)
    res, intents = _run_p(qc, RotationV2.Params(gain_floor_pct=0.10))
    assert res.facts["rotations"] == 1  # +18.75% >= 10% floor → banked
    qc2 = _scene(100.0, lag_close=95.0, lag_entry=80.0, lag_tenkan=100.0, lag_kijun=90.0)
    res2, _ = _run_p(qc2, RotationV2.Params(gain_floor_pct=0.25))
    assert res2.facts["rotations"] == 0  # +18.75% < 25% floor → protected (don't churn)


def test_adx_falling_gate():
    # stalled-green; adx_falling_gate ON. Falling (now<3back) → evictable; rising → protected.
    def scene(aw_vals):
        qc = _scene(100.0, lag_close=95.0, lag_entry=80.0, lag_tenkan=100.0, lag_kijun=90.0)
        qc._indicators[_Sym("LAG")]["adx_window"] = _Window(aw_vals)
        return qc
    res_fall, _ = _run_p(scene([20.0, 22.0, 24.0, 26.0]), RotationV2.Params(adx_falling_gate=True))
    assert res_fall.facts["rotations"] == 1   # now 20 < 3back 26 → decelerating → evict
    res_rise, _ = _run_p(scene([30.0, 26.0, 24.0, 22.0]), RotationV2.Params(adx_falling_gate=True))
    assert res_rise.facts["rotations"] == 0   # now 30 > 3back 22 → still rising → protected


def test_no_new_high_gate():
    # stalled-green; no_new_high_days=10. close below recent-10-high → evict; at/above → protected.
    def scene(highs):
        qc = _scene(100.0, lag_close=95.0, lag_entry=80.0, lag_tenkan=100.0, lag_kijun=90.0)
        qc._indicators[_Sym("LAG")]["high_window"] = _Window(highs)
        return qc
    res_no, _ = _run_p(scene([99.0] * 10), RotationV2.Params(no_new_high_days=10))
    assert res_no.facts["rotations"] == 1   # close 95 < recent high 99 → no new high → evict
    res_hi, _ = _run_p(scene([94.0] * 10), RotationV2.Params(no_new_high_days=10))
    assert res_hi.facts["rotations"] == 0   # close 95 >= recent high 94 → made a high → protected
    res_short, _ = _run_p(scene([99.0] * 5), RotationV2.Params(no_new_high_days=10))
    assert res_short.facts["rotations"] == 0  # window too short → can't assess → protected


def test_evict_select_momentum_picks_furthest_below_tenkan():
    # Two stalled-greens: A close98/tenkan100 (gap 2.0%), B close90/tenkan100 (gap 11.1% = weaker
    # momentum). score: A=4 (lower), B=6. evict_select=momentum → evict B (furthest below Tenkan),
    # NOT A (lowest score). The score-edge trigger: new=8 > B's 6 by >=1 ✓.
    a, b, new = _Sym("A"), _Sym("B"), _Sym("NEW")
    qc = _QC(100.0,
             {a: _Holding(100), b: _Holding(100)},
             {a: {"decision_score": 4, "entry_price": 80.0, "entry_date": datetime(2025, 1, 2)},
              b: {"decision_score": 6, "entry_price": 80.0, "entry_date": datetime(2025, 1, 2)}},
             {new: {"score": 8}},
             {a: {"d_ichi": _Ichi(100.0, 90.0)}, b: {"d_ichi": _Ichi(100.0, 85.0)}},
             {a: _Sec(98.0), b: _Sec(90.0)})
    res, intents = _run_p(qc, RotationV2.Params(evict_select="momentum"))
    assert res.facts["rotations"] == 1
    assert intents[0].ticker == "B"  # furthest below Tenkan, despite higher score than A
    # score-default would evict A (lowest score)
    qc2 = _QC(100.0,
              {a: _Holding(100), b: _Holding(100)},
              {a: {"decision_score": 4, "entry_price": 80.0, "entry_date": datetime(2025, 1, 2)},
               b: {"decision_score": 6, "entry_price": 80.0, "entry_date": datetime(2025, 1, 2)}},
              {new: {"score": 8}},
              {a: {"d_ichi": _Ichi(100.0, 90.0)}, b: {"d_ichi": _Ichi(100.0, 85.0)}},
              {a: _Sec(98.0), b: _Sec(90.0)})
    res2, intents2 = _run_p(qc2, RotationV2.Params(evict_select="score"))
    assert intents2[0].ticker == "A"  # lowest score
