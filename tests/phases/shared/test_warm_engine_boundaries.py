"""#264/#261 — the WARM-READINESS boundaries OUTSIDE the two maintained scorers.

The two maintained SCORE-EMITTERS (score_symbol_native, BctEntryConfirm._score_candidate) already
fail-loud correctly on every not-ready input — proven exhaustively in test_warm_at_score_time.py.
This file pins the TWO OTHER readiness boundaries the #264 audit surfaced. #264 was test-only and
asserted the TARGET fail-loud behavior (one strict-xfail, one ACTUAL-behavior pin); #261 LANDED
the engine fail-loud changes, so these tests are now FLIPPED to assert the implemented behavior.

================= #261 LINE-ITEMS (precise file:line) =================

GAP 1 → #261-7 (FAIL-OPEN regime → BLOCK-until-ready, implemented):
  src/phases/regime/spy_200ma/spy_200ma.py:39-40
  A NOT-READY regime SMA used to return blocked=False (PASS) → entries fired UNGATED while the
  regime filter was cold (fail-OPEN). #261-7 makes a not-ready gate BLOCK (blocked=True) until
  warm — never silently wave entries through on partial state. Latent on the champion path
  (WARMUP_DAYS=560 ≫ the 200d SMA), a dormant defense-in-depth net.

GAP 2 → #261-8 (SILENT-SKIP exit → RAISE, implemented):
  src/phases/exit/kijun_g3_exits/kijun_g3_exits.py:67-69
  An invested position whose d_ichi was NOT ready was SILENTLY skipped — its Kijun/cloud stop
  was never evaluated that bar, so a breach went unactioned (the position rode unprotected).
  HQ ruling: RAISE (DegradedDataError) with the symbol. The engine only OPENS a position after
  the SIGNAL scorer (which requires d_ichi.is_ready, #264) qualified it, and #259's _seed_daily
  warms d_ichi the day a name is subscribed — so an invested name SHOULD have a warm d_ichi; a
  cold one is a genuine break, not a benign warmup edge. Defense-in-depth, not an observed path.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from engine.base import DegradedDataError
from engine.context import PhaseContext
from phases.exit.kijun_g3_exits.kijun_g3_exits import KijunG3Exits
from phases.regime.spy_200ma.spy_200ma import SpySma200


# ======================================================================================
# Fakes
# ======================================================================================
class _Cur:
    def __init__(self, v: float) -> None:
        self.value = v


class _Ind:
    def __init__(self, v: float, ready: bool = True) -> None:
        self.current = _Cur(v)
        self.is_ready = ready


class _Ichi:
    def __init__(self, kijun: float, sa: float, sb: float, ready: bool = True) -> None:
        self.kijun = _Ind(kijun)
        self.senkou_a = _Ind(sa)
        self.senkou_b = _Ind(sb)
        self.is_ready = ready


class _Sym:
    def __init__(self, value: str) -> None:
        self.value = value

    def __hash__(self) -> int:
        return hash(self.value)

    def __eq__(self, o: object) -> bool:
        return isinstance(o, _Sym) and o.value == self.value


class _Sec:
    def __init__(self, price: float = 0.0, close: float = 0.0) -> None:
        self.price = price
        self.close = close


class _Holding:
    def __init__(self, invested: bool, quantity: int) -> None:
        self.invested = invested
        self.quantity = quantity


class _Portfolio:
    def __init__(self) -> None:
        self._h: dict[Any, _Holding] = {}

    def __setitem__(self, k: Any, v: _Holding) -> None:
        self._h[k] = v

    def items(self) -> Any:
        return list(self._h.items())


class _Transactions:
    def get_open_orders(self, symbol: Any = None) -> list[Any]:
        return []


class _RegimeQC:
    def __init__(self, spy_price: float, ma200: float, *, ma_ready: bool) -> None:
        self.spy = _Sym("SPY")
        self.spy_sma200 = _Ind(ma200, ready=ma_ready)
        self.securities = {self.spy: _Sec(price=spy_price)}


class _ExitQC:
    def __init__(self) -> None:
        self.portfolio = _Portfolio()
        self.securities: dict[Any, _Sec] = {}
        self.transactions = _Transactions()
        self._indicators: dict[Any, dict[str, Any]] = {}
        self._position_meta: dict[Any, Any] = {}


def _ctx(qc: Any) -> PhaseContext:
    return PhaseContext(qc=qc, time=datetime(2025, 6, 2), data=None)


# ======================================================================================
# GAP 1 — spy_200ma regime fail-OPEN when the SMA is not ready (#261 line-item)
# ======================================================================================
def test_regime_not_ready_now_blocks_until_warm():
    # #261-7 (FLIPPED from the fail-OPEN pin): a not-ready spy_sma200 now BLOCKS (blocked=True),
    # never silently passes entries through on partial/cold regime state. This is the anti-mirage
    # block-until-ready fix; the reason carries the #261-7 context.
    qc = _RegimeQC(spy_price=300.0, ma200=400.0, ma_ready=False)
    res = SpySma200(SpySma200.Params(), logger=None).evaluate(_ctx(qc))
    assert res.blocked is True
    assert res.decision == "block"
    assert "#261-7" in res.reason
    assert res.facts["regime_ready"] is False


def test_regime_missing_sma_attr_blocks():
    # #261-7: a totally MISSING regime SMA (attr absent) also blocks — fail-closed, not fail-open.
    qc = _RegimeQC(spy_price=300.0, ma200=400.0, ma_ready=False)
    qc.spy_sma200 = None  # type: ignore[assignment]
    res = SpySma200(SpySma200.Params(), logger=None).evaluate(_ctx(qc))
    assert res.blocked is True


def test_regime_ready_below_ma_blocks_control():
    # CONTROL: once warm + SPY<MA200, the regime DOES block (proves the gate works when ready).
    qc = _RegimeQC(spy_price=300.0, ma200=400.0, ma_ready=True)
    res = SpySma200(SpySma200.Params(), logger=None).evaluate(_ctx(qc))
    assert res.blocked is True


def test_regime_ready_above_ma_passes_control():
    qc = _RegimeQC(spy_price=500.0, ma200=400.0, ma_ready=True)
    res = SpySma200(SpySma200.Params(), logger=None).evaluate(_ctx(qc))
    assert res.blocked is False


# ======================================================================================
# GAP 2 — kijun_g3_exits SILENTLY skips an invested position with a cold d_ichi (#261 line-item)
# ======================================================================================
def test_exit_cold_d_ichi_raises_loud():
    # #261-8 (FLIPPED from the silent-skip pin): an INVESTED position whose d_ichi is NOT ready
    # now FAILS LOUD (DegradedDataError) instead of silently skipping the stop eval. A cold stop
    # on an invested position = unevaluated risk (the position rides unprotected) — HQ ruling is
    # RAISE, with the symbol + readiness context.
    qc = _ExitQC()
    sym = _Sym("FOO")
    qc.portfolio[sym] = _Holding(invested=True, quantity=100)
    qc.securities[sym] = _Sec(close=50.0)  # would breach any reasonable kijun
    qc._indicators[sym] = {"d_ichi": _Ichi(kijun=90.0, sa=85.0, sb=80.0, ready=False)}  # COLD
    ctx = _ctx(qc)
    with pytest.raises(DegradedDataError) as ei:
        KijunG3Exits(KijunG3Exits.Params(), logger=None).evaluate(ctx)
    msg = str(ei.value)
    assert "cold/missing daily Ichimoku" in msg
    assert "FOO" in msg  # the symbol context
    assert "#261-8" in msg


def test_exit_missing_d_ichi_raises_loud():
    # #261-8: an invested position whose indicator bundle has NO d_ichi at all also raises (the
    # missing-indicator break), not a silent skip.
    qc = _ExitQC()
    sym = _Sym("BAR")
    qc.portfolio[sym] = _Holding(invested=True, quantity=100)
    qc.securities[sym] = _Sec(close=50.0)
    qc._indicators[sym] = {"d_ichi": None}  # missing
    ctx = _ctx(qc)
    with pytest.raises(DegradedDataError) as ei:
        KijunG3Exits(KijunG3Exits.Params(), logger=None).evaluate(ctx)
    assert "d_ichi_present=False" in str(ei.value)


def test_exit_not_invested_cold_d_ichi_does_not_raise():
    # HAPPY-PATH BOUNDARY (#261-8): the guard fires ONLY on an INVESTED position. A non-invested
    # holding with a cold d_ichi is skipped by the `not holding.invested` continue BEFORE the
    # guard — no raise (the guard is not over-eager on flat positions).
    qc = _ExitQC()
    sym = _Sym("FLAT")
    qc.portfolio[sym] = _Holding(invested=False, quantity=0)
    qc.securities[sym] = _Sec(close=50.0)
    qc._indicators[sym] = {"d_ichi": _Ichi(kijun=90.0, sa=85.0, sb=80.0, ready=False)}
    ctx = _ctx(qc)
    res = KijunG3Exits(KijunG3Exits.Params(), logger=None).evaluate(ctx)
    assert ctx.bar_state.exit_intents == []
    assert res.facts["exit_count"] == 0


def test_exit_ready_d_ichi_below_kijun_fires_control():
    # CONTROL: a READY d_ichi with close < kijun DOES emit the exit (the stop works when warm).
    qc = _ExitQC()
    sym = _Sym("FOO")
    qc.portfolio[sym] = _Holding(invested=True, quantity=100)
    qc.securities[sym] = _Sec(close=50.0)
    qc._indicators[sym] = {"d_ichi": _Ichi(kijun=90.0, sa=85.0, sb=80.0, ready=True)}
    ctx = _ctx(qc)
    KijunG3Exits(KijunG3Exits.Params(), logger=None).evaluate(ctx)
    assert [(e.ticker, e.qty) for e in ctx.bar_state.exit_intents] == [("FOO", -100)]
