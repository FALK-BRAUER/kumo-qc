from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from base import BasePhase, PhaseResult
from symbol_key import canonical_symbol_key
from context import OrderIntent, PhaseContext
from shared_param_space import ComplexityDecl, ParamSpace


class FlatPctHeatcap(BasePhase):
    PHASE_KIND = "sizing"
    REQUIRES_UPSTREAM = ["signal"]
    PROVIDES_DOWNSTREAM = ["sized_orders"]

    COMPLEXITY = ComplexityDecl(
        free_params=0,
        note="position_pct is fixed-canonical (0.10); no sweepable axes.",
    )

    @dataclass(slots=True)
    class Params:
        position_pct: float = 0.10
        resolution: str = "daily"
        enabled: bool = True

        _HASH_EXCLUDE: ClassVar[frozenset[str]] = frozenset({"resolution"})

        @classmethod
        def space(cls) -> ParamSpace:
            return ParamSpace(axes={})

    def __init__(self, params: "FlatPctHeatcap.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params
        self.PHASE_RESOLUTION = params.resolution

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        qc = ctx.qc
        position_pct = self.p.position_pct

        committed_cash = 0.0
        available_cash = float(qc.portfolio.cash)
        active_by_key = {canonical_symbol_key(s): s for s in getattr(qc, "_active", set())}
        filled: list[OrderIntent] = []
        skipped_cash = 0

        for intent in ctx.bar_state.sized_orders:
            sym = active_by_key.get(canonical_symbol_key(intent.ticker))
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
                break
            ctx.record_funnel("cash_ok", sym)

            quantity = int(target_value / price)
            if quantity <= 0:
                continue

            committed_cash += target_value
            ctx.record_funnel("sized", sym)
            filled.append(OrderIntent(
                ticker=intent.ticker,
                qty=quantity,
                price=price,
                stop=0.0,
                module="sizing.flat_pct_heatcap",
                risk_dollars=target_value,
                order_type=intent.order_type,
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
