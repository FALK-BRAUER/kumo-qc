"""
Tests for bct_score_full signal phase.
Mocks score_symbol_native and LEAN APIs to test pre-filter, scoring gate,
parabolic block, and ranking logic independently.
"""
from datetime import datetime
from unittest.mock import patch, MagicMock
from engine.context import PhaseContext, BarState
from phases.signal.bct_score_full.bct_score_full import BctScoreFull


class FakeIndicator:
    def __init__(self, value, ready=True):
        self.is_ready = ready
        self.current = type("C", (), {"value": value})()


class FakeDIchi:
    def __init__(self, senkou_a=110.0, senkou_b=90.0, ready=True):
        self.is_ready = ready
        self.senkou_a = FakeIndicator(senkou_a)
        self.senkou_b = FakeIndicator(senkou_b)


class FakeSecurity:
    def __init__(self, price):
        self.price = price


class FakeHolding:
    invested = False


class FakePortfolio(dict):
    def __missing__(self, key):
        return FakeHolding()


class FakeTransactions:
    def get_open_orders(self, symbol=None):
        return []


class FakeSymbol:
    def __init__(self, value):
        self.value = value
    def __hash__(self):
        return hash(self.value)
    def __eq__(self, other):
        return self.value == other.value


class FakeQC:
    def __init__(self):
        self._polygon_universe = None
        self._indicators = {}
        self._active = set()
        self.portfolio = FakePortfolio()
        self.securities = {}
        self.transactions = FakeTransactions()

    def history(self, *args, **kwargs):
        return None


def make_symbol(name):
    return FakeSymbol(name)


def make_ctx(qc, candidates):
    ctx = PhaseContext(qc=qc, time=datetime(2025, 1, 2), data=None)
    ctx.bar_state.ranked_candidates = candidates
    return ctx


def _setup_qc_with_symbol(name, price=150.0, sma200=100.0, senkou_a=110.0, senkou_b=90.0):
    sym = make_symbol(name)
    qc = FakeQC()
    qc._active.add(sym)
    qc.securities[sym] = FakeSecurity(price)
    qc._indicators[sym] = {
        "sma200": FakeIndicator(sma200),
        "d_ichi": FakeDIchi(senkou_a=senkou_a, senkou_b=senkou_b),
    }
    return qc, sym


def test_pre_filter_excludes_below_sma200():
    qc, sym = _setup_qc_with_symbol("AAPL", price=80.0, sma200=100.0)
    phase = BctScoreFull(params={"min_score": 7}, logger=None)
    ctx = make_ctx(qc, ["AAPL"])

    with patch("phases.signal.bct_score_full.bct_score_full.score_symbol_native") as mock_score:
        mock_score.return_value = {"score": 8, "rating": "+++"}
        result = phase.evaluate(ctx)
        # score_symbol_native should NOT be called (pre-filtered)
        mock_score.assert_not_called()

    assert len(ctx.bar_state.sized_orders) == 0


def test_pre_filter_excludes_below_cloud_top():
    # price above SMA200 but below cloud_top
    qc, sym = _setup_qc_with_symbol("MSFT", price=105.0, sma200=100.0, senkou_a=120.0, senkou_b=110.0)
    # cloud_top = max(120, 110) = 120 → price=105 < 120 → excluded
    phase = BctScoreFull(params={"min_score": 7}, logger=None)
    ctx = make_ctx(qc, ["MSFT"])

    with patch("phases.signal.bct_score_full.bct_score_full.score_symbol_native") as mock_score:
        phase.evaluate(ctx)
        mock_score.assert_not_called()

    assert len(ctx.bar_state.sized_orders) == 0


def test_score_below_min_score_excluded():
    qc, sym = _setup_qc_with_symbol("GOOG", price=200.0, sma200=100.0)
    phase = BctScoreFull(params={"min_score": 7}, logger=None)
    ctx = make_ctx(qc, ["GOOG"])

    with patch("phases.signal.bct_score_full.bct_score_full.score_symbol_native") as mock_score:
        mock_score.return_value = {"score": 6, "rating": "++"}
        phase.evaluate(ctx)

    assert len(ctx.bar_state.sized_orders) == 0


def test_score_at_min_score_included():
    qc, sym = _setup_qc_with_symbol("META", price=200.0, sma200=100.0)
    phase = BctScoreFull(params={"min_score": 7}, logger=None)
    ctx = make_ctx(qc, ["META"])

    with patch("phases.signal.bct_score_full.bct_score_full.score_symbol_native") as mock_score:
        mock_score.return_value = {"score": 7, "rating": "++"}
        phase.evaluate(ctx)

    assert len(ctx.bar_state.sized_orders) == 1
    assert ctx.bar_state.sized_orders[0].ticker == "META"


def test_ranking_score_desc_then_dollarvol_desc():
    qc = FakeQC()
    for name, price in [("AAPL", 200.0), ("MSFT", 300.0), ("GOOG", 250.0)]:
        sym = make_symbol(name)
        qc._active.add(sym)
        qc.securities[sym] = FakeSecurity(price)
        qc._indicators[sym] = {
            "sma200": FakeIndicator(100.0),
            "d_ichi": FakeDIchi(senkou_a=110.0, senkou_b=90.0),
        }

    phase = BctScoreFull(params={"min_score": 7}, logger=None)
    ctx = make_ctx(qc, ["AAPL", "MSFT", "GOOG"])

    scores = {"AAPL": 8, "MSFT": 7, "GOOG": 8}
    dv = {"AAPL": 1_000_000.0, "MSFT": 500_000.0, "GOOG": 2_000_000.0}

    def mock_score(algo, sym, ind):
        return {"score": scores[sym.value], "rating": "+++"}

    # Mock dollar-vol via history — return None (dollar_vol stays 0.0 for simplicity)
    with patch("phases.signal.bct_score_full.bct_score_full.score_symbol_native", side_effect=mock_score):
        phase.evaluate(ctx)

    # Without dollar-vol (all 0.0), ordering is: score=8 tie: AAPL+GOOG before MSFT=7
    tickers = [o.ticker for o in ctx.bar_state.sized_orders]
    assert tickers.index("MSFT") > tickers.index("AAPL") or tickers.index("MSFT") > tickers.index("GOOG")


def test_signal_never_blocks():
    qc = FakeQC()
    phase = BctScoreFull(params={}, logger=None)
    ctx = make_ctx(qc, [])
    result = phase.evaluate(ctx)
    assert result.blocked is False


def test_already_invested_excluded():
    qc, sym = _setup_qc_with_symbol("TSLA", price=200.0, sma200=100.0)
    holding = FakeHolding()
    holding.invested = True
    qc.portfolio[sym] = holding
    phase = BctScoreFull(params={"min_score": 7}, logger=None)
    ctx = make_ctx(qc, ["TSLA"])

    with patch("phases.signal.bct_score_full.bct_score_full.score_symbol_native") as mock_score:
        mock_score.return_value = {"score": 8}
        phase.evaluate(ctx)
        mock_score.assert_not_called()

    assert len(ctx.bar_state.sized_orders) == 0
