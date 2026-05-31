"""Entry-timing phase: the BASELINE order mechanics — market-on-open (the §4 Gate-5 default
made EXPLICIT). The reference entry_timing impl phase-2 variants copy.

Kind: entry_timing
Marker: market_on_open_entry_v1
Tested params: enabled=True (no strategy axes — the baseline)
Sweep space (space()): EMPTY — market-on-open has no sweepable mechanic (it is THE baseline;
  any tunable price offset belongs to a different impl, e.g. BuyStopEntry's stop offset).
Complexity (COMPLEXITY): 0 free params.

METHODOLOGY (the bible §4 Gate 5 — order mechanics, fintrack repo; GH#253). Gate 5 defines the
order TYPE + PRICE per day-type (gap-up -> limit @ Kijun; flat -> buy-stop +0.75%; breakout ->
buy-stop above resistance; trend -> buy-stop +0.75%; T-bounce -> GTC limit @ Tenkan). This
BASELINE impl is the simplest of those — a plain market-on-open order for every confirmed+sized
candidate — i.e. TODAY'S implicit engine behavior (FIRE_ENTRIES already fires MOO) made an
EXPLICIT, named phase. The day-type order-type/price table is phase-2 entry_timing VARIANTS
(BuyStopEntry #149, LimitPullbackEntry); do NOT cram the table here (GH#253 phase-1 scope guard).

WHY this is a pass-through, not an order emitter: the engine's FIRE_ENTRIES sentinel is the
SINGLE order-placement seam (it calls qc.market_on_open_order on each sized_orders intent with
qty>0). A phase NEVER touches LEAN directly (PhaseContext is read-only refs). So the baseline
entry_timing's job is to AFFIRM the intents are market-on-open-ready and stamp provenance; the
fire is the engine's MOO call, which IS market-on-open — single code path, no divergence. A
non-MOO variant (BuyStop/Limit) would instead rewrite intent.price/stop (and a future engine
seam would honour the order type); the baseline leaves them as-is.

ORDERING NOTE (PHASE_ORDER): entry_selection -> entry_timing -> sizing. This phase therefore
runs on the qty=0 signal stubs BEFORE sizing assigns quantity; the baseline-MOO affirmation +
facts are the contribution here (the actual qty + final fire happen downstream at sizing /
FIRE_ENTRIES). A non-baseline timing variant that rewrites intent.price would do so here, and
sizing reads that price — so the seam is correctly placed for the phase-2 variants to use.

Charter: single code path, no count caps / time exits / fixed slots. The baseline emits an
order for EVERY confirmed+sized candidate (no selection here — entry_selection already gated).

Changelog:
  v1  baseline market-on-open entry mechanics (explicit pass-through over FIRE_ENTRIES MOO).
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from base import BasePhase, PhaseResult
from context import PhaseContext
from shared_param_space import ComplexityDecl, ParamSpace


class MarketOnOpenEntry(BasePhase):
    PHASE_KIND = "entry_timing"
    REQUIRES_UPSTREAM = ["signal"]
    PROVIDES_DOWNSTREAM = ["sized_orders"]

    # The baseline exposes NO sweepable mechanic (market-on-open has no price/offset knob).
    COMPLEXITY = ComplexityDecl(free_params=0, note="baseline market-on-open; no swept axes.")

    @dataclass(slots=True)
    class Params:
        enabled: bool = True

        @classmethod
        def space(cls) -> ParamSpace:
            """The baseline has no sweepable axes (grid size 1). A price-offset or stop mechanic
            belongs to a DIFFERENT entry_timing impl (BuyStopEntry/LimitPullbackEntry), per
            ADR D1 (different algorithm = new class), never a flag-branch of the baseline."""
            return ParamSpace(axes={})

    def __init__(self, params: "MarketOnOpenEntry.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        date_str = ctx.time.strftime("%Y-%m-%d")
        intents = ctx.bar_state.sized_orders

        # Stamp the order-mechanics provenance (module) so the executed order traces to this
        # baseline timing impl. Market-on-open carries no price rewrite (the open IS the fill
        # reference); a non-MOO variant would rewrite price/stop here instead.
        stamped = [
            replace(intent, module=f"{intent.module}|entry_timing.market_on_open_entry")
            for intent in intents
        ]
        ctx.bar_state.sized_orders = stamped

        return PhaseResult(
            decision=stamped,
            blocked=False,
            reason=f"{len(stamped)} market-on-open entries staged [{date_str}]",
            facts={"staged": len(stamped), "order_type": "market_on_open"},
            metrics={},
        )

    @property
    def version_marker(self) -> str:
        return "market_on_open_entry_v1"
