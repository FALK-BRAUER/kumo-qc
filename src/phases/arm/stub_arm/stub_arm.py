"""Arm phase: StubArm — the M1 throwaway DAY-clock arm module. Writes the day-chain candidates into the
framework carry qc._armed (keyed by canonical_symbol_key): {key: {zone, armed_date}}. The ZONE VALUE is
strategy (this stub uses the decision close = enter near current price); the engine NEVER computes it —
it only persists/exposes/evicts the opaque blob. Real arm modules (M3/Step-2) compute pullback/breakout
zones + the invalidation rule. NO qty here: sizing happens INTRADAY at the fire price (#386 (b)).

Kind: arm · Clock: DAILY · Marker: stub_arm_v1.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any

from engine.base import BasePhase, PhaseResult
from engine.context import PhaseContext
from engine.symbol_key import canonical_symbol_key


class StubArm(BasePhase):
    PHASE_KIND = "arm"
    PHASE_RESOLUTION = "daily"
    REQUIRES_UPSTREAM: list[str] = []
    PROVIDES_DOWNSTREAM: list[str] = []   # writes qc._armed (the carry), not bar_state

    @dataclass(slots=True)
    class Params:
        enabled: bool = True

    def __init__(self, params: "StubArm.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        qc = ctx.qc
        armed = getattr(qc, "_armed", None)
        if armed is None:
            armed = {}; qc._armed = armed
        active_by_key = {canonical_symbol_key(s): s for s in getattr(qc, "_active", set())}
        date_str = ctx.time.strftime("%Y-%m-%d")
        added = 0
        for intent in ctx.bar_state.sized_orders:
            sym = active_by_key.get(canonical_symbol_key(intent.ticker))
            if sym is None:
                continue
            try:
                zone = float(qc.securities[sym].close)   # STUB zone = decision close (strategy choice)
            except (KeyError, AttributeError, TypeError, ValueError):
                continue
            # key by the LEAN symbol (matches entry_trigger's read + the engine evict-by-sym at _fire)
            if sym not in armed:                          # add new; keep already-armed (persist)
                added += 1
            armed[sym] = {"zone": zone, "armed_date": date_str}
        return PhaseResult(decision=[], blocked=False,
                           reason=f"stub arm: {added} new armed, {len(armed)} total carried",
                           facts={"added": added, "armed_total": len(armed)}, metrics={})

    @property
    def version_marker(self) -> str:
        return "stub_arm_v1"
