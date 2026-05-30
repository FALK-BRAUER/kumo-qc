"""
Integration test: champion-asis-v1 engine chain end-to-end with FakeQC.
Proves the full PHASE_ORDER pipeline runs without error and produces
sensible outputs (exits on stop violations, entries on BCT signals, etc.).

NOT a parity BT (no LEAN docker). The real ±0.01 parity proof requires
lean-bt.sh — see Task 8 in ARCH-C plan.
"""
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
from engine.context import PhaseContext
from engine.engine import StrategyEngine, PHASE_ORDER
from engine.base import PhaseResult
from main_champion_asis import build_engine, STRATEGY_CONFIG


class FakeSymbol:
    def __init__(self, value):
        self.value = value
    def __hash__(self): return hash(self.value)
    def __eq__(self, other): return self.value == other.value


class FakeIndicator:
    def __init__(self, value, ready=True):
        self.is_ready = ready
        self.current = type("C", (), {"value": value})()


class FakeDIchi:
    def __init__(self, kijun=100.0, senkou_a=110.0, senkou_b=90.0, ready=True):
        self.is_ready = ready
        self.kijun = FakeIndicator(kijun)
        self.senkou_a = FakeIndicator(senkou_a)
        self.senkou_b = FakeIndicator(senkou_b)


class FakeWIchi:
    def __init__(self, kijun=100.0, ready=True):
        self.is_ready = ready
        self.kijun = FakeIndicator(kijun)


class FakeHolding:
    def __init__(self, invested=False, quantity=0):
        self.invested = invested
        self.quantity = quantity


class FakePortfolio(dict):
    def __init__(self, cash=100_000.0, total=100_000.0):
        super().__init__()
        self.cash = cash
        self.total_portfolio_value = total

    def __missing__(self, key):
        return FakeHolding()


class FakeTransactions:
    def get_open_orders(self, symbol=None):
        return []


class FakeSecurity:
    def __init__(self, price):
        self.price = price
        self.close = price


class FakeSecurities(dict):
    def contains_key(self, key):
        return key in self


class FakeQC:
    def __init__(self):
        self.logged = []
        self.orders = []
        self._active = set()
        self._indicators = {}
        self._polygon_universe = None
        self._position_meta = {}
        self.portfolio = FakePortfolio(cash=100_000.0, total=100_000.0)
        self.securities = FakeSecurities()
        self.transactions = FakeTransactions()
        self.spy_sma200 = FakeIndicator(400.0)  # SPY 200MA
        self.spy = FakeSymbol("SPY")
        self.vix = FakeSymbol("VIX")
        self.vix_ichi = FakeDIchi(kijun=20.0, senkou_a=25.0, senkou_b=18.0)
        self.regime_gate_enabled = True
        self.securities[self.spy] = FakeSecurity(500.0)  # SPY above MA200 → no block
        self.securities[self.vix] = FakeSecurity(18.0)   # VIX below cloud → tier 1

    def Log(self, msg):
        self.logged.append(msg)

    def log(self, msg):
        self.logged.append(msg)

    def market_on_open_order(self, symbol, qty):
        self.orders.append((symbol, qty))

    def history(self, symbol, bars, resolution):
        return None


def _add_candidate(qc, name, price=200.0, sma200=100.0, kijun=100.0):
    sym = FakeSymbol(name)
    qc._active.add(sym)
    qc.securities[sym] = FakeSecurity(price)
    qc._indicators[sym] = {
        "d_ichi": FakeDIchi(kijun=kijun, senkou_a=120.0, senkou_b=80.0),
        "w_ichi": FakeWIchi(kijun=kijun),
        "sma200": FakeIndicator(sma200),
    }
    return sym


def test_engine_chain_runs_without_error():
    qc = FakeQC()
    _add_candidate(qc, "AAPL", price=200.0)
    engine = build_engine(qc)
    ctx = PhaseContext(qc=qc, time=datetime(2025, 1, 2), data=None)

    with patch("phases.signal.bct_score_full.bct_score_full.score_symbol_native") as mock_score:
        mock_score.return_value = {"score": 8, "rating": "+++"}
        engine.on_data_with_ctx(ctx)

    # Engine ran — STRATEGY_INIT was logged
    assert any("STRATEGY_INIT" in str(m) for m in qc.logged)


def test_engine_exits_on_stop_violation():
    qc = FakeQC()
    aapl = _add_candidate(qc, "AAPL", price=80.0, kijun=100.0)  # close < kijun → exit
    qc.portfolio[aapl] = FakeHolding(invested=True, quantity=100)
    qc.securities[aapl] = FakeSecurity(80.0)  # close=80 < kijun=100

    engine = build_engine(qc)
    ctx = PhaseContext(qc=qc, time=datetime(2025, 1, 2), data=None)

    with patch("phases.signal.bct_score_full.bct_score_full.score_symbol_native"):
        engine.on_data_with_ctx(ctx)

    # Should have submitted a sell order
    sell_orders = [(sym, qty) for sym, qty in qc.orders if qty < 0]
    assert len(sell_orders) >= 1


def test_engine_skips_entries_on_spy_regime_block():
    qc = FakeQC()
    qc.securities[qc.spy] = FakeSecurity(350.0)  # SPY=350 < MA200=400 → block
    _add_candidate(qc, "AAPL", price=200.0)

    engine = build_engine(qc)
    ctx = PhaseContext(qc=qc, time=datetime(2025, 1, 2), data=None)

    with patch("phases.signal.bct_score_full.bct_score_full.score_symbol_native") as mock:
        mock.return_value = {"score": 8}
        engine.on_data_with_ctx(ctx)

    buy_orders = [(sym, qty) for sym, qty in qc.orders if qty > 0]
    assert len(buy_orders) == 0


def test_engine_fires_entries_when_regime_passes():
    qc = FakeQC()
    _add_candidate(qc, "AAPL", price=200.0)

    engine = build_engine(qc)
    ctx = PhaseContext(qc=qc, time=datetime(2025, 1, 2), data=None)
    # Set up polygon universe for today
    ctx.qc._polygon_universe = {"2025-01-02": ["AAPL"]}

    with patch("phases.signal.bct_score_full.bct_score_full.score_symbol_native") as mock:
        mock.return_value = {"score": 8, "rating": "+++"}
        engine.on_data_with_ctx(ctx)

    buy_orders = [(sym, qty) for sym, qty in qc.orders if qty > 0]
    assert len(buy_orders) == 1
    # position_pct=0.10, total=100k, target=10k, price=200 → qty=int(10000/200)=50
    assert buy_orders[0][1] == 50
