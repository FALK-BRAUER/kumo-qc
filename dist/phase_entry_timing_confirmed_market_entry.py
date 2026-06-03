from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from base import BasePhase, PhaseResult
from context import PhaseContext
from shared_param_space import ComplexityDecl, ParamSpace


class ConfirmedMarketEntry(BasePhase):
    PHASE_KIND = "entry_timing"
    PHASE_RESOLUTION = "intraday"
    REQUIRES_UPSTREAM = ["signal"]
    PROVIDES_DOWNSTREAM = ["sized_orders"]

    COMPLEXITY = ComplexityDecl(free_params=0, note="confirmed intraday market entry; no swept axes.")

    @dataclass(slots=True)
    class Params:
        enabled: bool = True

        @classmethod
        def space(cls) -> ParamSpace:
            return ParamSpace(axes={})

    def __init__(self, params: "ConfirmedMarketEntry.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        stamped = [
            replace(intent, order_type="market",
                    module=f"{intent.module}|entry_timing.confirmed_market_entry")
            for intent in ctx.bar_state.sized_orders
        ]
        ctx.bar_state.sized_orders = stamped
        return PhaseResult(
            decision=stamped,
            blocked=False,
            reason=f"confirmed-market entry: {len(stamped)} confirmed intent(s) → order_type=market",
            facts={"market_intents": len(stamped)},
            metrics={},
        )

    @property
    def version_marker(self) -> str:
        return "confirmed_market_entry_v1"
