from datetime import datetime

from engine.context import PhaseContext
from phases.trail.position_path_tracker.position_path_tracker import PositionPathTracker


class FakeHolding:
    def __init__(self, invested=True):
        self.invested = invested


class FakeUpperHolding:
    def __init__(self, invested=True):
        self.Invested = invested


class FakeSecurity:
    def __init__(self, close=103.0):
        self.close = close
        self.price = close


class FakeBar:
    def __init__(self, open=101.0, high=105.0, low=98.0, close=103.0):
        self.open = open
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
    assert result.facts == {"tracked": 1}
    assert path["peak_price"] == 108.0
    assert path["trough_price"] == 97.0
    assert round(path["mfe_pct"], 4) == 0.08
    assert round(path["mae_pct"], 4) == -0.03
    assert path["days_held"] == 5


def test_tracker_provides_position_path_contract():
    assert PositionPathTracker.PROVIDES_DOWNSTREAM == ["position_path"]
    assert PositionPathTracker.PHASE_RESOLUTION == "intraday"


def test_tracks_uppercase_invested_holding_contract():
    sym = _sym("UPPER")
    qc = FakeQC(sym)
    qc.portfolio[sym] = FakeUpperHolding()
    data = FakeSlice({sym: FakeBar(high=106.0, low=99.0, close=105.0)})
    ctx = PhaseContext(qc=qc, time=datetime(2025, 1, 6), data=data)

    result = PositionPathTracker(PositionPathTracker.Params(), logger=None).evaluate(ctx)

    assert result.facts == {"tracked": 1}
    assert qc._position_path[sym]["last_price"] == 105.0


def test_preserves_prior_peak_and_trough():
    sym = _sym("MSFT")
    qc = FakeQC(sym, close=103.0)
    qc._position_path = {sym: {"peak_price": 112.0, "trough_price": 94.0}}
    ctx = PhaseContext(qc=qc, time=datetime(2025, 1, 6), data=None)

    PositionPathTracker(PositionPathTracker.Params(), logger=None).evaluate(ctx)

    assert qc._position_path[sym]["peak_price"] == 112.0
    assert qc._position_path[sym]["trough_price"] == 94.0
    assert qc._position_path[sym]["bars_held"] == 1


def test_removes_closed_positions_from_path_state():
    sym = _sym("TSLA")
    qc = FakeQC(sym)
    qc.portfolio[sym] = FakeHolding(invested=False)
    qc._position_path = {sym: {"peak_price": 110.0}}
    ctx = PhaseContext(qc=qc, time=datetime(2025, 1, 6), data=None)

    result = PositionPathTracker(PositionPathTracker.Params(), logger=None).evaluate(ctx)

    assert result.facts == {"tracked": 0}
    assert qc._position_path == {}


def test_tracks_current_return_giveback_and_session_path():
    sym = _sym("META")
    qc = FakeQC(sym)
    qc._position_path = {
        sym: {
            "peak_price": 110.0,
            "trough_price": 96.0,
            "bars_held": 4,
            "session_date": datetime(2025, 1, 6).date(),
            "session_open": 102.0,
            "session_high": 109.0,
            "session_low": 99.0,
            "session_bars": 3,
        }
    }
    data = FakeSlice({sym: FakeBar(open=104.0, high=111.0, low=103.0, close=106.0)})
    ctx = PhaseContext(qc=qc, time=datetime(2025, 1, 6, 10, 35), data=data)

    PositionPathTracker(PositionPathTracker.Params(), logger=None).evaluate(ctx)

    path = qc._position_path[sym]
    assert path["last_open"] == 104.0
    assert path["last_high"] == 111.0
    assert path["last_low"] == 103.0
    assert path["last_price"] == 106.0
    assert path["bars_held"] == 5
    assert round(path["current_return_pct"], 4) == 0.06
    assert round(path["mfe_pct"], 4) == 0.11
    assert round(path["mae_pct"], 4) == -0.04
    assert round(path["giveback_pct"], 4) == 0.05
    assert path["session_open"] == 102.0
    assert path["session_high"] == 111.0
    assert path["session_low"] == 99.0
    assert path["session_bars"] == 4
    assert round(path["session_mfe_pct"], 4) == 0.11
    assert round(path["session_mae_pct"], 4) == -0.01
    assert round(path["session_giveback_pct"], 4) == 0.05


def test_resets_session_path_on_new_day():
    sym = _sym("SHOP")
    qc = FakeQC(sym)
    qc._position_path = {
        sym: {
            "peak_price": 109.0,
            "trough_price": 97.0,
            "bars_held": 7,
            "session_date": datetime(2025, 1, 6).date(),
            "session_open": 101.0,
            "session_high": 109.0,
            "session_low": 97.0,
            "session_bars": 7,
        }
    }
    data = FakeSlice({sym: FakeBar(open=104.0, high=106.0, low=102.0, close=105.0)})
    ctx = PhaseContext(qc=qc, time=datetime(2025, 1, 7, 9, 35), data=data)

    PositionPathTracker(PositionPathTracker.Params(), logger=None).evaluate(ctx)

    path = qc._position_path[sym]
    assert path["bars_held"] == 8
    assert path["session_date"] == datetime(2025, 1, 7).date()
    assert path["session_open"] == 104.0
    assert path["session_high"] == 106.0
    assert path["session_low"] == 102.0
    assert path["session_bars"] == 1
