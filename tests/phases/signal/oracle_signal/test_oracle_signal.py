"""Tests for the #322 OracleSignal PROD-PHASE BRIDGE.

Covers four things the task pins:
  1. NO-OP-SWAP PARITY — OracleSignal with the default BctPassthroughPredictor produces the SAME
     surviving winners (same set, same order) as BctScoreFull on a shared fixture. This proves
     the seam is behaviour-neutral until a learned predictor lands.
  2. PREDICTOR INTERFACE — a mock predictor fires per ITS decision (the phase trusts `fire`).
  3. FAIL-LOUD — a predictor returning a non-finite score raises PredictorError (never fires).
  4. PARAMS / FEATURE-CONTRACT SHAPE — Params defaults, space()/COMPLEXITY, and that predict()
     receives a fully-populated CandidateFeatures per the contract.

Mocks score_symbol_native + LEAN APIs (the same FakeQC pattern as test_bct_score_full).
"""
from __future__ import annotations

import math
from datetime import datetime
from unittest.mock import patch

import pytest

from engine.context import PhaseContext
from phases.signal.bct_score_full.bct_score_full import BctScoreFull
from phases.signal.oracle_signal.oracle_signal import (
    BctPassthroughPredictor,
    CandidateFeatures,
    OracleSignal,
    Predictor,
    PredictorError,
    PredictorOutput,
)


# --------------------------------------------------------------------------- fakes
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
        self._trailing_dv = {}
        self.portfolio = FakePortfolio()
        self.securities = {}
        self.transactions = FakeTransactions()


def make_symbol(name):
    return FakeSymbol(name)


def make_ctx(qc, candidates):
    ctx = PhaseContext(qc=qc, time=datetime(2025, 1, 2), data=None)
    ctx.bar_state.ranked_candidates = candidates
    return ctx


def _multi_symbol_qc(specs):
    """Build a FakeQC with several active+priced symbols (all passing the pre-filter).

    specs: list of (name, price, dollar_vol). cloud/sma fixed so the pre-filter passes.
    """
    qc = FakeQC()
    for name, price, dv in specs:
        sym = make_symbol(name)
        qc._active.add(sym)
        qc.securities[sym] = FakeSecurity(price)
        qc._indicators[sym] = {
            "sma200": FakeIndicator(100.0),
            "d_ichi": FakeDIchi(senkou_a=110.0, senkou_b=90.0),
        }
        qc._trailing_dv[name.lower()] = dv
    return qc


# --------------------------------------------------------------------------- 1. PARITY
def test_passthrough_parity_matches_bct_score_full():
    """OracleSignal(stub) and BctScoreFull emit the SAME winners in the SAME order.

    Shared fixture: AAPL=8, MSFT=7, GOOG=8, AMZN=5 (below min_score). Same dollar-vols.
    Both phases mock score_symbol_native identically. The surviving set + ranking must match.
    """
    specs = [
        ("AAPL", 200.0, 1_000_000.0),
        ("MSFT", 300.0, 500_000.0),
        ("GOOG", 250.0, 2_000_000.0),
        ("AMZN", 220.0, 9_000_000.0),  # high DV but score 5 → both phases drop it
    ]
    scores = {"AAPL": 8, "MSFT": 7, "GOOG": 8, "AMZN": 5}

    def mock_score(algo, sym, ind):
        return {"score": scores[sym.value], "rating": "+", "conditions": [True] * scores[sym.value] + [False] * (8 - scores[sym.value])}

    candidates = ["AAPL", "MSFT", "GOOG", "AMZN"]

    # BctScoreFull run
    qc_bct = _multi_symbol_qc(specs)
    ctx_bct = make_ctx(qc_bct, candidates)
    with patch("phases.signal.bct_score_full.bct_score_full.score_symbol_native", side_effect=mock_score):
        res_bct = BctScoreFull(BctScoreFull.Params(min_score=7), logger=None).evaluate(ctx_bct)

    # OracleSignal with the default passthrough stub
    qc_orc = _multi_symbol_qc(specs)
    ctx_orc = make_ctx(qc_orc, candidates)
    phase = OracleSignal(OracleSignal.Params(min_score=7), logger=None)
    assert isinstance(phase.p.predictor, BctPassthroughPredictor)
    with patch("phases.signal.oracle_signal.oracle_signal.score_symbol_native", side_effect=mock_score):
        res_orc = phase.evaluate(ctx_orc)

    bct_tickers = [o.ticker for o in ctx_bct.bar_state.sized_orders]
    orc_tickers = [o.ticker for o in ctx_orc.bar_state.sized_orders]

    assert orc_tickers == bct_tickers, f"parity broken: oracle={orc_tickers} bct={bct_tickers}"
    assert res_orc.facts["candidate_count"] == res_bct.facts["candidate_count"]
    assert res_orc.blocked is res_bct.blocked is False
    # AMZN (score 5) dropped despite the highest DV — proves the gate, not the DV, decided.
    assert "AMZN" not in orc_tickers


def test_passthrough_parity_with_parabolic_block():
    """Parity holds through the parabolic block: a high-roc13 name is blocked by BOTH phases."""
    specs = [("NVDA", 200.0, 1.0), ("AMD", 200.0, 1.0)]

    def mock_score(algo, sym, ind):
        return {"score": 8, "rating": "+++", "conditions": [True] * 8}

    candidates = ["NVDA", "AMD"]

    def build(qc_factory_specs):
        qc = _multi_symbol_qc(qc_factory_specs)
        for sym in qc._active:
            if sym.value == "NVDA":
                qc._indicators[sym]["roc13"] = FakeIndicator(0.40, ready=True)  # blocked (>0.25)
            else:
                qc._indicators[sym]["roc13"] = FakeIndicator(0.10, ready=True)  # ok
        return qc

    qc_bct = build(specs)
    ctx_bct = make_ctx(qc_bct, candidates)
    with patch("phases.signal.bct_score_full.bct_score_full.score_symbol_native", side_effect=mock_score):
        res_bct = BctScoreFull(BctScoreFull.Params(min_score=7, parabolic_threshold=0.25), logger=None).evaluate(ctx_bct)

    qc_orc = build(specs)
    ctx_orc = make_ctx(qc_orc, candidates)
    with patch("phases.signal.oracle_signal.oracle_signal.score_symbol_native", side_effect=mock_score):
        res_orc = OracleSignal(OracleSignal.Params(min_score=7, parabolic_threshold=0.25), logger=None).evaluate(ctx_orc)

    assert [o.ticker for o in ctx_orc.bar_state.sized_orders] == [o.ticker for o in ctx_bct.bar_state.sized_orders] == ["AMD"]
    assert res_orc.facts["parabolic_blocked"] == res_bct.facts["parabolic_blocked"] == 1


def test_module_tag_is_oracle_signal():
    """Emitted OrderIntents carry the oracle_signal module tag (not bct_score_full)."""
    qc = _multi_symbol_qc([("AAPL", 200.0, 1.0)])
    ctx = make_ctx(qc, ["AAPL"])
    with patch("phases.signal.oracle_signal.oracle_signal.score_symbol_native",
               return_value={"score": 8, "conditions": [True] * 8}):
        OracleSignal(OracleSignal.Params(min_score=7), logger=None).evaluate(ctx)
    assert ctx.bar_state.sized_orders[0].module == "signal.oracle_signal"


# --------------------------------------------------------------------------- 2. INTERFACE
def test_mock_predictor_fires_per_its_decision():
    """The phase emits a candidate iff the predictor's PredictorOutput.fire is True — even when
    the BCT score would say otherwise. Proves the phase trusts the predictor, not min_score."""

    class FlipPredictor:
        """Fires LOW-score names, declines HIGH-score names — the inverse of BctScoreFull."""

        def predict(self, features: CandidateFeatures) -> PredictorOutput:
            return PredictorOutput(score=float(features.bct_score), fire=features.bct_score < 7)

    assert isinstance(FlipPredictor(), Predictor)  # structural conformance

    specs = [("LOWS", 200.0, 1.0), ("HIGH", 200.0, 1.0)]
    scores = {"LOWS": 6, "HIGH": 8}

    def mock_score(algo, sym, ind):
        return {"score": scores[sym.value], "conditions": [True] * scores[sym.value] + [False] * (8 - scores[sym.value])}

    qc = _multi_symbol_qc(specs)
    ctx = make_ctx(qc, ["LOWS", "HIGH"])
    # min_score=6 so the pre-filter/scoring keeps both; the predictor decides who fires.
    phase = OracleSignal(OracleSignal.Params(predictor=FlipPredictor(), min_score=6), logger=None)
    with patch("phases.signal.oracle_signal.oracle_signal.score_symbol_native", side_effect=mock_score):
        res = phase.evaluate(ctx)

    tickers = [o.ticker for o in ctx.bar_state.sized_orders]
    assert tickers == ["LOWS"]  # only the low-score name fired
    assert res.facts["predictor_declined"] == 1
    assert res.facts["predictor"] == "FlipPredictor"


def test_predictor_receives_full_feature_contract():
    """predict() is handed a fully-populated CandidateFeatures per the FEATURE CONTRACT:
    ticker, price, the 8 conditions, bct_score, roc13, dollar_vol, rank, regime_ok."""
    captured = {}

    class CapturingPredictor:
        def predict(self, features: CandidateFeatures) -> PredictorOutput:
            captured["f"] = features
            return PredictorOutput(score=float(features.bct_score), fire=True)

    qc = _multi_symbol_qc([("AAPL", 187.5, 4_200_000.0)])
    qc._regime_ok = True
    for sym in qc._active:
        qc._indicators[sym]["roc13"] = FakeIndicator(0.12, ready=True)
    ctx = make_ctx(qc, ["AAPL"])

    conds = [True, True, False, True, True, True, True, True]  # sum == 7
    with patch("phases.signal.oracle_signal.oracle_signal.score_symbol_native",
               return_value={"score": 7, "conditions": conds}):
        OracleSignal(OracleSignal.Params(predictor=CapturingPredictor(), min_score=7), logger=None).evaluate(ctx)

    f = captured["f"]
    assert f.ticker == "AAPL"
    assert f.price == 187.5
    assert f.conditions == tuple(conds)
    assert f.bct_score == 7
    assert f.roc13 == pytest.approx(0.12)
    assert f.dollar_vol == pytest.approx(4_200_000.0)
    assert f.rank == 0
    assert f.regime_ok is True


def test_predictor_score_drives_ranking_over_bct_score():
    """Survivors are ranked by the PREDICTOR's score (DESC), not the BCT score — a learned model
    can re-order names the BCT sum would tie."""

    class CustomScorePredictor:
        # All BCT scores are 8, but the predictor scores by a custom map → it owns the order.
        _custom = {"AAA": 1.0, "BBB": 9.0, "CCC": 5.0}

        def predict(self, features: CandidateFeatures) -> PredictorOutput:
            return PredictorOutput(score=self._custom[features.ticker], fire=True)

    specs = [("AAA", 200.0, 1.0), ("BBB", 200.0, 1.0), ("CCC", 200.0, 1.0)]
    qc = _multi_symbol_qc(specs)
    ctx = make_ctx(qc, ["AAA", "BBB", "CCC"])
    with patch("phases.signal.oracle_signal.oracle_signal.score_symbol_native",
               return_value={"score": 8, "conditions": [True] * 8}):
        OracleSignal(OracleSignal.Params(predictor=CustomScorePredictor(), min_score=7), logger=None).evaluate(ctx)

    assert [o.ticker for o in ctx.bar_state.sized_orders] == ["BBB", "CCC", "AAA"]  # 9 > 5 > 1


# --------------------------------------------------------------------------- 3. FAIL-LOUD
@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_score_raises(bad):
    """A predictor returning a non-finite score crashes (PredictorError) — never fires on garbage."""

    class GarbagePredictor:
        def predict(self, features: CandidateFeatures) -> PredictorOutput:
            return PredictorOutput(score=bad, fire=True)

    qc = _multi_symbol_qc([("AAPL", 200.0, 1.0)])
    ctx = make_ctx(qc, ["AAPL"])
    phase = OracleSignal(OracleSignal.Params(predictor=GarbagePredictor(), min_score=7), logger=None)
    with patch("phases.signal.oracle_signal.oracle_signal.score_symbol_native",
               return_value={"score": 8, "conditions": [True] * 8}):
        with pytest.raises(PredictorError, match="AAPL"):
            phase.evaluate(ctx)


def test_non_numeric_score_raises():
    """A non-numeric score (e.g. a string) is also a degraded model → PredictorError."""

    class StringScorePredictor:
        def predict(self, features: CandidateFeatures) -> PredictorOutput:
            return PredictorOutput(score="high", fire=True)  # type: ignore[arg-type]

    qc = _multi_symbol_qc([("AAPL", 200.0, 1.0)])
    ctx = make_ctx(qc, ["AAPL"])
    phase = OracleSignal(OracleSignal.Params(predictor=StringScorePredictor(), min_score=7), logger=None)
    with patch("phases.signal.oracle_signal.oracle_signal.score_symbol_native",
               return_value={"score": 8, "conditions": [True] * 8}):
        with pytest.raises(PredictorError):
            phase.evaluate(ctx)


# --------------------------------------------------------------------------- 4. SHAPE / CONTRACT
def test_params_defaults_and_predictor_default():
    p = OracleSignal.Params()
    assert isinstance(p.predictor, BctPassthroughPredictor)
    assert p.predictor.min_score == 7
    assert p.min_score == 7
    assert p.parabolic_threshold == 0.25
    assert p.enabled is True


def test_space_and_complexity_in_lockstep():
    space = OracleSignal.Params.space()
    assert set(space.axes) == {"min_score", "parabolic_threshold"}
    assert space.grid_size == 12
    # ComplexityDecl.validate enforces free_params == swept-axis count (no hidden knobs).
    OracleSignal.COMPLEXITY.validate(space)
    assert OracleSignal.COMPLEXITY.free_params == 2


def test_phase_contract_metadata():
    assert OracleSignal.PHASE_KIND == "signal"
    assert OracleSignal.PHASE_RESOLUTION == "daily"
    assert OracleSignal.REQUIRES_UPSTREAM == ["universe"]
    assert OracleSignal.PROVIDES_DOWNSTREAM == ["sized_orders"]
    assert OracleSignal(OracleSignal.Params(), logger=None).version_marker == "oracle_signal_v1"


def test_passthrough_predictor_output_shape():
    """The stub maps bct_score → (score, fire-at-min_score) per the PredictorOutput contract."""
    pred = BctPassthroughPredictor(min_score=7)
    feat_fire = CandidateFeatures(ticker="X", price=10.0, conditions=(True,) * 7 + (False,), bct_score=7)
    feat_no = CandidateFeatures(ticker="Y", price=10.0, conditions=(True,) * 6 + (False,) * 2, bct_score=6)
    out_fire = pred.predict(feat_fire)
    out_no = pred.predict(feat_no)
    assert out_fire.score == 7.0 and out_fire.fire is True
    assert out_no.score == 6.0 and out_no.fire is False
    assert math.isfinite(out_fire.score)


def test_signal_never_blocks_empty_candidates():
    qc = FakeQC()
    res = OracleSignal(OracleSignal.Params(), logger=None).evaluate(make_ctx(qc, []))
    assert res.blocked is False
    assert res.facts["candidate_count"] == 0
