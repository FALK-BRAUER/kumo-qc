"""Entry-timing phase: CONFIRMED INTRADAY MARKET entry (#276b-1 / #270, GH#25).

Kind: entry_timing · Clock: INTRADAY · Marker: confirmed_market_entry_v1

The intraday counterpart to the baseline MarketOnOpenEntry. By the time entry_timing runs, the
intraday entry_selection stack (PreFlightStaleness → BctIntradayConfirm) has already GATED
`ctx.bar_state.sized_orders` down to the CONFIRMED candidates (the deferred/expired/stale ones were
dropped). This phase stamps each survivor with `order_type="market"` so FIRE_ENTRIES fires it as an
INTRADAY market order NOW (on the 5-min clock, at confirm) — NOT a next-open market-on-open (the
fixture/daily default). That is the whole point of the two-clock model: the daily decision picks
WHO; the intraday confirm picks WHEN, and fires intraday.

Pass-through, like the baseline: a phase NEVER touches LEAN (the engine's FIRE_ENTRIES is the single
order-placement seam; it dispatches on `intent.order_type` via _submit → qc.market_order for
"market"). This phase only rewrites the TYPE (+ stamps provenance); qty stays 0 until `sizing`
(PHASE_ORDER: entry_selection → entry_timing → sizing → FIRE_ENTRIES), and FIRE_ENTRIES's qty>0
guard blocks any stub that sizing didn't fill. No selection here — entry_selection already gated.

Changelog:
  v1  intraday confirmed-market entry mechanics (order_type=market on the confirmed survivors).
"""
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

    # No sweepable mechanic — "fire a market order at confirm" has no price/offset knob (the
    # confirm TIMING is BctIntradayConfirm's window/vol axes, not here). A non-market intraday
    # variant (intraday buy-stop/limit) would be a DIFFERENT impl (ADR D1), never a flag here.
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
        # The intents here are the CONFIRMED survivors (entry_selection already dropped the rest).
        # Stamp order_type="market" (fire intraday now) + provenance. qty untouched (sizing owns it).
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
