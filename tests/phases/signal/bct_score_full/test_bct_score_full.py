"""
Tests for bct_score_full signal phase.
Mocks score_symbol_native and LEAN APIs to test pre-filter, scoring gate,
parabolic block, and ranking logic independently.

v2-delta: constructor is BctScoreFull(BctScoreFull.Params(...), logger=None).
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
    phase = BctScoreFull(BctScoreFull.Params(min_score=7), logger=None)
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
    phase = BctScoreFull(BctScoreFull.Params(min_score=7), logger=None)
    ctx = make_ctx(qc, ["MSFT"])

    with patch("phases.signal.bct_score_full.bct_score_full.score_symbol_native") as mock_score:
        phase.evaluate(ctx)
        mock_score.assert_not_called()

    assert len(ctx.bar_state.sized_orders) == 0


def test_score_below_min_score_excluded():
    qc, sym = _setup_qc_with_symbol("GOOG", price=200.0, sma200=100.0)
    phase = BctScoreFull(BctScoreFull.Params(min_score=7), logger=None)
    ctx = make_ctx(qc, ["GOOG"])

    with patch("phases.signal.bct_score_full.bct_score_full.score_symbol_native") as mock_score:
        mock_score.return_value = {"score": 6, "rating": "++"}
        phase.evaluate(ctx)

    assert len(ctx.bar_state.sized_orders) == 0


def test_score_at_min_score_included():
    qc, sym = _setup_qc_with_symbol("META", price=200.0, sma200=100.0)
    phase = BctScoreFull(BctScoreFull.Params(min_score=7), logger=None)
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

    phase = BctScoreFull(BctScoreFull.Params(min_score=7), logger=None)
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
    phase = BctScoreFull(BctScoreFull.Params(), logger=None)
    ctx = make_ctx(qc, [])
    result = phase.evaluate(ctx)
    assert result.blocked is False


def test_already_invested_excluded():
    qc, sym = _setup_qc_with_symbol("TSLA", price=200.0, sma200=100.0)
    holding = FakeHolding()
    holding.invested = True
    qc.portfolio[sym] = holding
    phase = BctScoreFull(BctScoreFull.Params(min_score=7), logger=None)
    ctx = make_ctx(qc, ["TSLA"])

    with patch("phases.signal.bct_score_full.bct_score_full.score_symbol_native") as mock_score:
        mock_score.return_value = {"score": 8}
        phase.evaluate(ctx)
        mock_score.assert_not_called()

    assert len(ctx.bar_state.sized_orders) == 0


# ---------------------------------------------------------------------------
# DECLINE — parabolic block (#245): a candidate that scores >= min_score but whose
# maintained 13-day ROC exceeds parabolic_threshold (src ~:94) is EXCLUDED and counted
# in the `parabolic_blocked` fact. The default FakeIndicator dict omits roc13, so we add
# one with a value above the threshold to drive the block branch.
# ---------------------------------------------------------------------------
def test_parabolic_block_excludes_and_counts():
    qc, sym = _setup_qc_with_symbol("NVDA", price=200.0, sma200=100.0)
    # roc13 ready, value 0.40 > parabolic_threshold 0.25 → parabolic block.
    qc._indicators[sym]["roc13"] = FakeIndicator(0.40, ready=True)
    phase = BctScoreFull(BctScoreFull.Params(min_score=7, parabolic_threshold=0.25), logger=None)
    ctx = make_ctx(qc, ["NVDA"])

    with patch("phases.signal.bct_score_full.bct_score_full.score_symbol_native") as mock_score:
        mock_score.return_value = {"score": 8, "rating": "+++"}
        result = phase.evaluate(ctx)

    # Scored >= 7 but parabolic → not emitted, counted as a parabolic block.
    assert len(ctx.bar_state.sized_orders) == 0
    assert result.facts["candidate_count"] == 0
    assert result.facts["parabolic_blocked"] == 1


def test_parabolic_below_threshold_still_enters():
    # Same setup but roc13 below threshold → NOT blocked (the correct-include path).
    qc, sym = _setup_qc_with_symbol("AMD", price=200.0, sma200=100.0)
    qc._indicators[sym]["roc13"] = FakeIndicator(0.10, ready=True)  # 0.10 < 0.25
    phase = BctScoreFull(BctScoreFull.Params(min_score=7, parabolic_threshold=0.25), logger=None)
    ctx = make_ctx(qc, ["AMD"])

    with patch("phases.signal.bct_score_full.bct_score_full.score_symbol_native") as mock_score:
        mock_score.return_value = {"score": 8, "rating": "+++"}
        result = phase.evaluate(ctx)

    assert len(ctx.bar_state.sized_orders) == 1
    assert ctx.bar_state.sized_orders[0].ticker == "AMD"
    assert result.facts["parabolic_blocked"] == 0


def test_parabolic_boundary_equal_threshold_not_blocked():
    # `roc13 > parabolic_threshold` is strict-greater → at exactly the threshold, NOT blocked.
    qc, sym = _setup_qc_with_symbol("ORCL", price=200.0, sma200=100.0)
    qc._indicators[sym]["roc13"] = FakeIndicator(0.25, ready=True)  # == threshold
    phase = BctScoreFull(BctScoreFull.Params(min_score=7, parabolic_threshold=0.25), logger=None)
    ctx = make_ctx(qc, ["ORCL"])

    with patch("phases.signal.bct_score_full.bct_score_full.score_symbol_native") as mock_score:
        mock_score.return_value = {"score": 8, "rating": "+++"}
        result = phase.evaluate(ctx)

    assert len(ctx.bar_state.sized_orders) == 1
    assert result.facts["parabolic_blocked"] == 0


def test_parabolic_not_ready_does_not_block():
    # roc13 present but NOT ready → block check skipped (the not-ready edge).
    qc, sym = _setup_qc_with_symbol("INTC", price=200.0, sma200=100.0)
    qc._indicators[sym]["roc13"] = FakeIndicator(0.99, ready=False)  # huge but not ready
    phase = BctScoreFull(BctScoreFull.Params(min_score=7, parabolic_threshold=0.25), logger=None)
    ctx = make_ctx(qc, ["INTC"])

    with patch("phases.signal.bct_score_full.bct_score_full.score_symbol_native") as mock_score:
        mock_score.return_value = {"score": 8, "rating": "+++"}
        result = phase.evaluate(ctx)

    assert len(ctx.bar_state.sized_orders) == 1  # not ready → not blocked
    assert result.facts["parabolic_blocked"] == 0


# ---------------------------------------------------------------------------
# #332 warmup-cache CONSUMPTION branch (flag-ON = qc._warmup_cache present). flag-OFF (no attr) is
# covered by ALL the tests above (FakeQC has no _warmup_cache → live path, unchanged). These prove
# the cache branch fires, bypasses the live score_symbol_native, and applies pre-filter/parabolic.
# ---------------------------------------------------------------------------
def _pass_scalars(roc13=0.10):
    return {  # scores 8; pre-filter passes (price>ma200, price>d_cloud_top)
        "d_price": 100.0, "d_tenkan": 90.0, "d_cloud_top": 88.0, "ma200": 80.0,
        "w_tenkan": 70.0, "w_kijun": 60.0, "w_senkou_a": 55.0, "w_senkou_b": 50.0,
        "w_close_0": 65.0, "w_close_26": 40.0,
        "adx_now": 30.0, "plus_di": 25.0, "minus_di": 10.0, "adx_3back": 22.0, "roc13": roc13,
    }


def test_cache_branch_fires_and_bypasses_native():
    qc, sym = _setup_qc_with_symbol("AAPL", price=999.0)  # live price irrelevant — cache used
    qc._warmup_cache = {"AAPL": {datetime(2025, 1, 2).date(): _pass_scalars()}}
    phase = BctScoreFull(BctScoreFull.Params(min_score=7), logger=None)
    ctx = make_ctx(qc, ["AAPL"])  # ctx.time = 2025-01-02
    with patch("phases.signal.bct_score_full.bct_score_full.score_symbol_native") as mock_native:
        phase.evaluate(ctx)
        mock_native.assert_not_called()  # cache path bypasses the live scorer
    assert len(ctx.bar_state.sized_orders) == 1 and ctx.bar_state.sized_orders[0].ticker == "AAPL"


def test_cache_miss_skips_symbol():
    qc, sym = _setup_qc_with_symbol("MSFT")
    qc._warmup_cache = {"MSFT": {datetime(2024, 1, 1).date(): _pass_scalars()}}  # wrong date → miss
    phase = BctScoreFull(BctScoreFull.Params(min_score=7), logger=None)
    ctx = make_ctx(qc, ["MSFT"])  # ctx.time = 2025-01-02 → no row → skip
    phase.evaluate(ctx)
    assert len(ctx.bar_state.sized_orders) == 0


def test_cache_branch_parabolic_block_via_cached_roc13():
    qc, sym = _setup_qc_with_symbol("NVDA")
    qc._warmup_cache = {"NVDA": {datetime(2025, 1, 2).date(): _pass_scalars(roc13=0.40)}}  # >0.25
    phase = BctScoreFull(BctScoreFull.Params(min_score=7, parabolic_threshold=0.25), logger=None)
    ctx = make_ctx(qc, ["NVDA"])
    result = phase.evaluate(ctx)
    assert len(ctx.bar_state.sized_orders) == 0
    assert result.facts["parabolic_blocked"] == 1


def test_cache_branch_prefilter_below_ma200_skips():
    qc, sym = _setup_qc_with_symbol("GOOG")
    s = _pass_scalars(); s["d_price"] = 70.0  # 70 < ma200 80 → pre-filter cond8 → skip
    qc._warmup_cache = {"GOOG": {datetime(2025, 1, 2).date(): s}}
    phase = BctScoreFull(BctScoreFull.Params(min_score=7), logger=None)
    ctx = make_ctx(qc, ["GOOG"])
    phase.evaluate(ctx)
    assert len(ctx.bar_state.sized_orders) == 0


def test_indicators_none_skips_symbol():
    # EDGE: `ind is None` (src — getattr(qc, "_indicators", {}).get(symbol) is None) → symbol skipped,
    # score never computed, no order. Symbol is active + priced but has NO indicator entry.
    qc = FakeQC()
    sym = make_symbol("CRM")
    qc._active.add(sym)
    qc.securities[sym] = FakeSecurity(200.0)
    # deliberately NO qc._indicators[sym] entry → ind is None
    phase = BctScoreFull(BctScoreFull.Params(min_score=7), logger=None)
    ctx = make_ctx(qc, ["CRM"])

    with patch("phases.signal.bct_score_full.bct_score_full.score_symbol_native") as mock_score:
        mock_score.return_value = {"score": 8, "rating": "+++"}
        result = phase.evaluate(ctx)
        mock_score.assert_not_called()  # short-circuited before scoring

    assert len(ctx.bar_state.sized_orders) == 0
    assert result.facts["candidate_count"] == 0
