"""Sizing phase: flat POSITION_PCT + committed_cash heat-cap.

Kind: sizing
Marker: flat_pct_heatcap_v1
Tested params: position_pct=0.10 (champion default)
Charter: single code path, NO count/slot caps — exposure governed by the cash heat-cap
only (and gross_exposure_cap when it lands). Ranks come from the signal phase; fills
each candidate at position_pct of portfolio value until cash is exhausted.

Logic carried from the oracle sizing loop, with the slot machinery REMOVED per the
no-fixed-slots charter (the old max_positions/vix_tier slot cap was a 9999 no-op — its
removal is behavior-identical: cash was always the binding constraint).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine.base import BasePhase, PhaseResult
from engine.context import OrderIntent, PhaseContext


class FlatPctHeatcap(BasePhase):
    PHASE_KIND = "sizing"
    REQUIRES_UPSTREAM = ["signal"]
    PROVIDES_DOWNSTREAM = ["sized_orders"]

    @dataclass(slots=True)
    class Params:
        position_pct: float = 0.10
        enabled: bool = True

    def __init__(self, params: "FlatPctHeatcap.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        qc = ctx.qc
        position_pct = self.p.position_pct

        # Heat-cap (cash) only — no slot count. Fill ranked candidates until cash exhausted.
        committed_cash = 0.0
        available_cash = float(qc.portfolio.cash)
        active_by_value = {s.value: s for s in getattr(qc, "_active", set())}
        filled: list[OrderIntent] = []
        skipped_cash = 0

        for intent in ctx.bar_state.sized_orders:
            sym = active_by_value.get(intent.ticker)
            if sym is None:
                continue
            try:
                price = float(qc.securities[sym].price)
            except Exception:
                continue
            if price <= 0:
                continue

            target_value = float(qc.portfolio.total_portfolio_value) * position_pct
            if available_cash - committed_cash < target_value:
                skipped_cash += 1
                break  # cash exhausted (oracle breaks, not continues)

            quantity = int(target_value / price)
            if quantity <= 0:
                continue

            committed_cash += target_value
            filled.append(OrderIntent(
                ticker=intent.ticker,
                qty=quantity,
                price=price,
                stop=0.0,
                module="sizing.flat_pct_heatcap",
                risk_dollars=target_value,
            ))

        ctx.bar_state.sized_orders = filled
        return PhaseResult(
            decision=filled,
            blocked=False,
            reason=f"{len(filled)} entries sized, {skipped_cash} cash-exhausted",
            facts={"filled": len(filled), "committed_cash": committed_cash, "skipped_cash": skipped_cash},
            metrics={},
        )

    @property
    def version_marker(self) -> str:
        return "flat_pct_heatcap_v1"
