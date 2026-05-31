"""METHODOLOGY GOLDEN-MASTER for the score-aware sizer (the §4 SIZING-TIER curve).

The methodology anchor for `ScoreTierHeatcap`: the X/4 entry-confirm score maps to the
methodology sizing tiers EXACTLY:

    4/4 -> FULL   (1.00 x position_pct of portfolio value)
    3/4 -> 75%    (0.75 x position_pct)
    2/4 -> 50%    (0.50 x position_pct)
    <2  -> NO ENTRY (tier 0.0)

GOLDEN-MASTER DISCIPLINE (charter: RAW-own-merits): assert the tier->multiplier mapping == the
methodology curve on the canonical defaults. NOT champion-number matching. If this file fails,
the sizer DIVERGED from the methodology sizing tiers — STOP + FLAG for HQ.

The mapping is locked at TWO levels:
  1. `_tier(score)` — the pure score->multiplier function (the curve).
  2. The end-to-end target_value = position_pct * tier * PV (the curve actually drives size).
"""
from __future__ import annotations

import pytest

from phases.sizing.score_tier_heatcap.score_tier_heatcap import ScoreTierHeatcap


def _phase(**kw):
    return ScoreTierHeatcap(ScoreTierHeatcap.Params(**kw), logger=None)


# ---- Level 1: the pure tier curve == the methodology (canonical defaults) ----

@pytest.mark.parametrize(
    "score, expected_multiplier",
    [
        (4, 1.00),
        (3, 0.75),
        (2, 0.50),
        (1, 0.00),
        (0, 0.00),
        (5, 1.00),   # clamp: score above 4 (should never happen) -> full tier, never > full
    ],
)
def test_tier_multiplier(score, expected_multiplier):
    assert _phase()._tier(score) == expected_multiplier


# ---- Level 2: the curve drives the per-name TARGET (position_pct * tier * PV) ----

@pytest.mark.parametrize(
    "score, expected_target",
    [
        (4, 100_000.0),  # 1.00 * 0.10 * 1_000_000
        (3, 75_000.0),   # 0.75 * 0.10 * 1_000_000
        (2, 50_000.0),   # 0.50 * 0.10 * 1_000_000
    ],
)
def test_target_value_follows_tier(score, expected_target):
    from datetime import datetime

    from engine.context import OrderIntent, PhaseContext

    class _Sym:
        def __init__(self, v): self.value = v
        def __hash__(self): return hash(self.value)
        def __eq__(self, o): return self.value == o.value

    class _Sec:
        price = 100.0

    class _PF:
        cash = 10_000_000.0
        total_portfolio_value = 1_000_000.0

    class _QC:
        def __init__(self):
            self.portfolio = _PF()
            sym = _Sym("AAPL")
            self._active = {sym}
            self.securities = {sym: _Sec()}
            self._entry_confirm = {"AAPL": score}

    qc = _QC()
    ctx = PhaseContext(qc=qc, time=datetime(2025, 1, 2), data=None)
    ctx.bar_state.sized_orders = [
        OrderIntent(ticker="AAPL", qty=0, price=0.0, stop=0.0, module="stub", risk_dollars=0.0)
    ]
    _phase(position_pct=0.10).evaluate(ctx)
    assert ctx.bar_state.sized_orders[0].risk_dollars == expected_target


def test_below_floor_yields_no_target():
    from datetime import datetime

    from engine.context import OrderIntent, PhaseContext

    class _Sym:
        def __init__(self, v): self.value = v
        def __hash__(self): return hash(self.value)
        def __eq__(self, o): return self.value == o.value

    class _Sec:
        price = 100.0

    class _PF:
        cash = 10_000_000.0
        total_portfolio_value = 1_000_000.0

    class _QC:
        def __init__(self):
            self.portfolio = _PF()
            sym = _Sym("AAPL")
            self._active = {sym}
            self.securities = {sym: _Sec()}
            self._entry_confirm = {"AAPL": 1}

    qc = _QC()
    ctx = PhaseContext(qc=qc, time=datetime(2025, 1, 2), data=None)
    ctx.bar_state.sized_orders = [
        OrderIntent(ticker="AAPL", qty=0, price=0.0, stop=0.0, module="stub", risk_dollars=0.0)
    ]
    _phase(position_pct=0.10).evaluate(ctx)
    assert ctx.bar_state.sized_orders == []
