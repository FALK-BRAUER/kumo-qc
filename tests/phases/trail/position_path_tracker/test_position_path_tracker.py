from datetime import datetime

from engine.context import PhaseContext
from phases.trail.position_path_tracker.position_path_tracker import PositionPathTracker


class FakeHolding:
    def __init__(self, invested=True):
        self.invested = invested


class FakeSecurity:
    def __init__(self, close=103.0):
        self.close = close
        self.price = close


class FakeBar:
    def __init__(self, high=105.0, low=98.0, close=103.0):
        self.high = high
        self.low = low
        self.close = close


class FakeSlice(dict):
    def contains_key(self, symbol):
        return symbol in self


class FakeQC:
    def __init__(self, sym, close=103.0):
        self.portfolio = {sym: FakeHolding()}
        self.securities = {sym: FakeSecurity(close)}
        self._position_meta = {sym: {"entry_price": 100.0, "entry_date": datetime(2025, 1, 1)}}


def _sym(name="AAPL"):
    return type("Symbol", (), {"value": name})()


def test_tracks_mfe_and_mae_from_bar_high_low():
    sym = _sym()
    qc = FakeQC(sym)
    data = FakeSlice({sym: FakeBar(high=108.0, low=97.0, close=104.0)})
    ctx = PhaseContext(qc=qc, time=datetime(2025, 1, 6), data=data)

    result = PositionPathTracker(PositionPathTracker.Params(), logger=None).evaluate(ctx)

    path = qc._position_path[sym]
    assert result.facts == {"updated": 1, "tracked": 1}
    assert path["peak_price"] == 108.0
    assert path["trough_price"] == 97.0
    assert round(path["mfe_pct"], 4) == 0.08
    assert round(path["mae_pct"], 4) == -0.03
    assert path["days_held"] == 5


def test_tracker_provides_position_path_contract():
    assert PositionPathTracker.PROVIDES_DOWNSTREAM == ["position_path"]


def test_preserves_prior_peak_and_trough():
    sym = _sym("MSFT")
    qc = FakeQC(sym, close=103.0)
    qc._position_path = {sym: {"peak_price": 112.0, "trough_price": 94.0}}
    ctx = PhaseContext(qc=qc, time=datetime(2025, 1, 6), data=None)

    PositionPathTracker(PositionPathTracker.Params(), logger=None).evaluate(ctx)

    assert qc._position_path[sym]["peak_price"] == 112.0
    assert qc._position_path[sym]["trough_price"] == 94.0


def test_removes_closed_positions_from_path_state():
    sym = _sym("TSLA")
    qc = FakeQC(sym)
    qc.portfolio[sym] = FakeHolding(invested=False)
    qc._position_path = {sym: {"peak_price": 110.0}}
    ctx = PhaseContext(qc=qc, time=datetime(2025, 1, 6), data=None)

    result = PositionPathTracker(PositionPathTracker.Params(), logger=None).evaluate(ctx)

    assert result.facts == {"updated": 0, "tracked": 0}
    assert qc._position_path == {}
