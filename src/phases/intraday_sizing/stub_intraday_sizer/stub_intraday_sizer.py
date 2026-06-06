"""Intraday-sizing phase: StubIntradaySizer — the M1 throwaway INTRADAY sizer. Sizes the entry_trigger's
fired stubs AT THE FIRE BAR (the actual intraday entry price, #386 (b): day-arm carries no qty; risk
sizing needs the fire price). STUB = small flat position_pct of portfolio at the fire close, clamped to
remaining gross headroom (the cap governs which armed candidates fill as the book fills, first-come on
the intraday tick). Real sizers (FlatPctHeatcap/VolAdjustedRisk) become intraday-clock in Step 2.

Kind: intraday_sizing · Clock: INTRADAY · Marker: stub_intraday_sizer_v1.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any

from engine.base import BasePhase, PhaseResult
from engine.context import PhaseContext


class StubIntradaySizer(BasePhase):
    PHASE_KIND = "intraday_sizing"
    PHASE_RESOLUTION = "intraday"
    REQUIRES_UPSTREAM = ["entry_trigger"]  # the KIND that emits the intraday sized_orders stubs (a kind, not a field)
    PROVIDES_DOWNSTREAM = ["sized_orders"]

    @dataclass(slots=True)
    class Params:
        position_pct: float = 0.05     # small flat % of portfolio per fire (stub)
        max_gross_pct: float = 1.0     # gross-cap headroom clamp (trivial stub gate)
        enabled: bool = True

    def __init__(self, params: "StubIntradaySizer.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        qc = ctx.qc
        tpv = float(qc.portfolio.total_portfolio_value)
        invested = float(getattr(qc.portfolio, "total_holdings_value", 0.0) or 0.0)
        gross_room = max(0.0, self.p.max_gross_pct * tpv - invested)   # remaining gross headroom AT FIRE
        filled = []
        for intent in ctx.bar_state.sized_orders:
            price = float(intent.price) if intent.price else 0.0
            if price <= 0:
                continue
            target = min(tpv * self.p.position_pct, gross_room)        # flat, clamped to headroom
            qty = int(target / price)
            if qty <= 0:
                continue
            gross_room -= qty * price                                  # consume headroom (first-come)
            from dataclasses import replace
            filled.append(replace(intent, qty=qty, risk_dollars=qty * price,
                                   module=f"{intent.module}|intraday_sizing.stub"))
        ctx.bar_state.sized_orders = filled
        return PhaseResult(decision=filled, blocked=False,
                           reason=f"stub intraday-size: {len(filled)} sized at fire price",
                           facts={"filled": len(filled)}, metrics={})

    @property
    def version_marker(self) -> str:
        return "stub_intraday_sizer_v1"
