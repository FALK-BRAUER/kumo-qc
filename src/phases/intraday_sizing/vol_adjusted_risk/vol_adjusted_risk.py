"""Intraday-sizing phase: VolAdjustedRisk (#254 catalog, #386 scenario B).

Sizes entries at the intraday fire price using a fixed dollar-risk budget scaled by VIX. The stop
denominator comes from the trigger intent when present, otherwise a configurable fallback percent.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from engine.base import BasePhase, PhaseResult
from engine.context import PhaseContext


class VolAdjustedRisk(BasePhase):
    PHASE_KIND = "intraday_sizing"
    PHASE_RESOLUTION = "intraday"
    REQUIRES_UPSTREAM = ["entry_trigger"]
    PROVIDES_DOWNSTREAM = ["sized_orders"]

    @dataclass(slots=True)
    class Params:
        risk_pct: float = 0.01
        fallback_stop_pct: float = 0.08
        max_position_pct: float = 0.08
        vix_baseline: float = 20.0
        vix_slope: float = 0.02
        min_scale: float = 0.40
        enabled: bool = True

    def __init__(self, params: "VolAdjustedRisk.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        qc = ctx.qc
        tpv = float(qc.portfolio.total_portfolio_value)
        scale = self._vix_scale(qc)
        filled = []
        for intent in ctx.bar_state.sized_orders:
            price = float(intent.price)
            if price <= 0.0:
                continue
            stop = float(intent.stop) if intent.stop > 0.0 else price * (1.0 - self.p.fallback_stop_pct)
            per_share_risk = max(price - stop, 0.01)
            risk_budget = tpv * self.p.risk_pct * scale
            max_qty = int((tpv * self.p.max_position_pct) / price)
            qty = min(int(risk_budget / per_share_risk), max_qty)
            if qty <= 0:
                continue
            filled.append(replace(
                intent,
                qty=qty,
                stop=stop,
                risk_dollars=qty * per_share_risk,
                module=f"{intent.module}|intraday_sizing.vol_adjusted_risk",
            ))
        ctx.bar_state.sized_orders = filled
        return PhaseResult(
            decision=filled,
            blocked=False,
            reason=f"vol-adjusted risk sized {len(filled)} entries",
            facts={"filled": len(filled), "vix_scale": scale},
            metrics={},
        )

    def _vix_scale(self, qc: Any) -> float:
        vix = getattr(qc, "vix_level", None)
        if vix is None:
            return 1.0
        raw = 1.0 - max(0.0, float(vix) - self.p.vix_baseline) * self.p.vix_slope
        return max(self.p.min_scale, min(1.0, raw))

    @property
    def version_marker(self) -> str:
        return "vol_adjusted_risk_v1"
