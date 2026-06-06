"""Entry-selection phase (DAY filter): ResistanceProximityFilter (#254 catalog, #386 scenario A/C).

REJECT a candidate if its price is within buffer_pct of its 52-week high (chasing into resistance).
Param: buffer_pct (A=0.03, C=0.02). Prefer names 2-10% BELOW resistance. Runs on the DAILY clock as a
candidate FILTER (the two-clock co-clock guard exempts day-phase entry-filters; only the intraday
entry_trigger→intraday_sizing→FIRE sub-chain is co-clock-validated).

Reads the per-symbol 52wk high from qc._high_52w (runtime-maintained). FAIL-OPEN on a missing reference
(can't reject without a resistance level → keep). Filters bar_state.sized_orders in place.

Kind: entry_selection · Clock: DAILY · REQUIRES signal · PROVIDES sized_orders · Marker: resistance_proximity_filter_v1.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any

from engine.base import BasePhase, PhaseResult
from engine.context import PhaseContext
from engine.symbol_key import canonical_symbol_key


class ResistanceProximityFilter(BasePhase):
    PHASE_KIND = "entry_selection"
    PHASE_RESOLUTION = "daily"
    REQUIRES_UPSTREAM = ["signal"]
    PROVIDES_DOWNSTREAM = ["sized_orders"]

    @dataclass(slots=True)
    class Params:
        buffer_pct: float = 0.03  # reject within 3% of 52wk high (A); 2% (C)
        enabled: bool = True

    def __init__(self, params: "ResistanceProximityFilter.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        qc = ctx.qc
        active_by_key = {canonical_symbol_key(s): s for s in getattr(qc, "_active", set())}
        highs = getattr(qc, "_high_52w", {})
        kept = []
        rejected = 0
        for intent in ctx.bar_state.sized_orders:
            sym = active_by_key.get(canonical_symbol_key(intent.ticker))
            high52 = highs.get(sym) if sym is not None else None
            if high52 is None or float(high52) <= 0.0:
                kept.append(intent)  # no resistance reference → cannot reject (fail-open, keep)
                continue
            # reject if price is within buffer_pct BELOW (or above) the 52wk high
            if float(intent.price) >= float(high52) * (1.0 - self.p.buffer_pct):
                rejected += 1
                continue
            kept.append(intent)
        ctx.bar_state.sized_orders = kept
        return PhaseResult(decision=[], blocked=False,
                           reason=f"resistance-proximity: kept {len(kept)}, rejected {rejected} (within {self.p.buffer_pct:.0%} of 52wk high)",
                           facts={"kept": len(kept), "rejected": rejected}, metrics={})

    @property
    def version_marker(self) -> str:
        return "resistance_proximity_filter_v1"
