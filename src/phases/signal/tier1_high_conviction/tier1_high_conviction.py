"""Signal phase: Tier1HighConviction (#254 catalog, #386 scenario A/C).

Restricts the universe's ranked_candidates to George's ++/Tier-1 high-conviction name set, writing the
survivors as OrderIntent stubs (qty=0; intraday_sizing sets qty at fire). vs BctScoreFull which scores
ALL names — this pins the pool to the conviction set. tier1_set is a param (the real ~23-name George
set is config-supplied; the default is a large-cap placeholder so the scenario composes + fires).

Kind: signal · REQUIRES universe · PROVIDES sized_orders · Marker: tier1_high_conviction_v1.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

from engine.base import BasePhase, PhaseResult
from engine.context import OrderIntent, PhaseContext
from engine.symbol_key import canonical_symbol_key

_DEFAULT_TIER1 = (
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "AVGO", "TSLA", "JPM", "V",
    "UNH", "XOM", "MA", "COST", "HD", "PG", "LLY", "MRK", "ABBV", "CRM", "AMD", "NFLX", "ORCL",
)


class Tier1HighConviction(BasePhase):
    PHASE_KIND = "signal"
    REQUIRES_UPSTREAM = ["universe"]
    PROVIDES_DOWNSTREAM = ["sized_orders"]

    @dataclass(slots=True)
    class Params:
        tier1_set: tuple[str, ...] = _DEFAULT_TIER1
        enabled: bool = True

    def __init__(self, params: "Tier1HighConviction.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params
        self._tier1 = {t.lower() for t in params.tier1_set}

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        qc = ctx.qc
        active_by_key = {canonical_symbol_key(s): s for s in getattr(qc, "_active", set())}
        kept = [t for t in ctx.bar_state.ranked_candidates if str(t).lower() in self._tier1]
        stubs: list[OrderIntent] = []
        for t in kept:
            sym = active_by_key.get(canonical_symbol_key(t))
            if sym is None:
                continue
            try:
                price = float(qc.securities[sym].price)
            except (KeyError, AttributeError, TypeError, ValueError):
                continue
            stubs.append(OrderIntent(ticker=str(t), qty=0, price=price, stop=0.0,
                                     module="signal.tier1_high_conviction", risk_dollars=0.0))
        ctx.bar_state.sized_orders = stubs
        return PhaseResult(decision=kept, blocked=False,
                           reason=f"tier1: {len(stubs)} stubs of {len(ctx.bar_state.ranked_candidates)} candidates",
                           facts={"kept": len(kept), "stubs": len(stubs)}, metrics={})

    @property
    def version_marker(self) -> str:
        return "tier1_high_conviction_v1"
