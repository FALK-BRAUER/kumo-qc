"""#264 — the WARM-READINESS boundaries OUTSIDE the two maintained scorers (the #261 line-items).

The two maintained SCORE-EMITTERS (score_symbol_native, BctEntryConfirm._score_candidate) already
fail-loud correctly on every not-ready input — proven exhaustively in test_warm_at_score_time.py.
This file pins the TWO OTHER readiness boundaries the #264 audit surfaced. Per the #264 ticket
constraint: where the engine is silently-lenient (acts on a not-ready / not-warm indicator) but
the anti-mirage mandate wants fail-LOUD, the CORRECT behavior is asserted as xfail(strict=True)
and FLAGGED for #261 (#261 owns the engine fail-loud change; #264 is test-only and must NOT
pre-empt it). Where the lenient behavior is a judgment call (not a clear mirage), the ACTUAL
behavior is pinned as a passing regression test with a precise #261 flag in the docstring.

================= #261 LINE-ITEMS (precise file:line) =================

GAP 1 (FAIL-OPEN regime, xfail strict below):
  src/phases/regime/spy_200ma/spy_200ma.py:39-40
    `if spy_sma200 is None or not spy_sma200.is_ready or spy is None:
         return PhaseResult(decision="pass", blocked=False, reason="spy_sma200 not ready", ...)`
  A NOT-READY regime SMA returns blocked=False (PASS) -> entries fire UNGATED while the regime
  filter is cold. Today this is unreachable in production (WARMUP_DAYS=560 >> the 200d SMA, and
  on_data skips scoring during warmup), so it is latent — but it is a fail-OPEN: the safe anti-
  mirage behavior is to BLOCK (or skip-loud) entries until the regime gate is warm, never to
  silently wave them through on partial/empty state. #261 should decide: block-until-ready.

GAP 2 (SILENT-SKIP exit, regression-pinned below, NOT xfail):
  src/phases/exit/kijun_g3_exits/kijun_g3_exits.py:67-69
    `d_ichi = ind.get("d_ichi")
     if d_ichi is None or not d_ichi.is_ready: continue`
  An invested position whose d_ichi is NOT ready is SILENTLY skipped — its Kijun/cloud stop is
  never evaluated that bar, so a stop breach goes unactioned (the position rides unprotected).
  Unlike GAP 1 this is not a score-emission mirage and "can't compute a stop without the
  indicator" is defensible, so #264 pins the ACTUAL behavior (skip, no exit) rather than
  asserting a raise. #261 judgment call: should a held-but-cold position fail-loud (log+alert)
  rather than skip silently? Flagged, not pre-empted.

NOTE: a fresh post-warmup entrant cannot reach GAP 2 with a cold d_ichi in practice — #259's
_seed_daily warms d_ichi the day it is subscribed, and the engine only OPENS a position after
the SIGNAL scorer (which requires d_ichi.is_ready) qualified it. GAP 2 is a defense-in-depth
boundary, not an observed live path.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

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
def test_regime_not_ready_currently_passes_actual_behavior():
    # ACTUAL (pin the status quo): a not-ready spy_sma200 -> blocked=False (PASS). This is the
    # fail-OPEN. Pinned so the #261 fix is a DELIBERATE, reviewed change (this test flips then).
    qc = _RegimeQC(spy_price=300.0, ma200=400.0, ma_ready=False)  # price<ma200 would normally BLOCK
    res = SpySma200(SpySma200.Params(), logger=None).evaluate(_ctx(qc))
    assert res.blocked is False
    assert res.reason == "spy_sma200 not ready"


@pytest.mark.xfail(
    strict=True,
    reason="#261 line-item: spy_200ma.py:39-40 fail-OPENs (PASS) when the regime SMA is not "
    "ready, so entries fire UNGATED on a cold regime gate. Anti-mirage mandate wants "
    "block-until-ready (skip-loud), never silently wave entries through on partial state. "
    "#261 owns the engine fail-loud change; this asserts the TARGET behavior.",
)
def test_regime_not_ready_should_block_until_warm_TARGET():
    # TARGET (the anti-mirage behavior #261 should implement): a not-ready regime gate must NOT
    # pass entries through — it must BLOCK (or otherwise skip-loud) until warm. Strict-xfail:
    # this turns GREEN automatically the moment #261 makes the regime block-until-ready.
    qc = _RegimeQC(spy_price=300.0, ma200=400.0, ma_ready=False)
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
def test_exit_cold_d_ichi_silently_skips_actual_behavior():
    # ACTUAL (pin the status quo): an INVESTED position whose d_ichi is NOT ready is SKIPPED —
    # no exit intent emitted even though close (50) is far below where a Kijun stop would fire.
    # The stop is simply never evaluated this bar. Pinned as the #261 judgment-call boundary.
    qc = _ExitQC()
    sym = _Sym("FOO")
    qc.portfolio[sym] = _Holding(invested=True, quantity=100)
    qc.securities[sym] = _Sec(close=50.0)  # would breach any reasonable kijun
    qc._indicators[sym] = {"d_ichi": _Ichi(kijun=90.0, sa=85.0, sb=80.0, ready=False)}  # COLD
    ctx = _ctx(qc)
    res = KijunG3Exits(KijunG3Exits.Params(), logger=None).evaluate(ctx)
    # No exit emitted (silently skipped) — the #261 flag: should a held-but-cold position
    # fail-loud rather than ride unprotected? Pinned, NOT asserted-as-target (judgment call).
    assert ctx.bar_state.exit_intents == []
    assert res.facts["exit_count"] == 0
    assert res.blocked is False  # exits never block, even on the skip


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
