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
