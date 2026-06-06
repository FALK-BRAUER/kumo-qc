"""Universe phase: SectorRotationUniverse (#254 catalog, #386 scenario B).

Universe = active names in the top-N sectors by sector relative strength. Reads qc._sector
(symbol -> sector) and qc._sector_rs (sector -> score). If the runtime has not wired sector data yet,
this phase keeps all active names but logs that the rotation reference was absent. That makes the B
blueprint runnable for the architecture proof without silently pretending sector data existed.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any

from engine.base import BasePhase, PhaseResult
from engine.context import PhaseContext
from engine.symbol_key import canonical_symbol_key


class SectorRotationUniverse(BasePhase):
    PHASE_KIND = "universe"
    REQUIRES_UPSTREAM: list[str] = []
    PROVIDES_DOWNSTREAM = ["ranked_candidates"]

    @dataclass(slots=True)
    class Params:
        top_sectors: int = 3
        enabled: bool = True

    def __init__(self, params: "SectorRotationUniverse.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        qc = ctx.qc
        sector_raw = getattr(qc, "_sector", {}) or {}
        sector_rs = getattr(qc, "_sector_rs", {}) or {}
        sector = {canonical_symbol_key(k): v for k, v in sector_raw.items()}
        active = sorted(str(getattr(s, "value", s)) for s in getattr(qc, "_active", set()))
        if not sector or not sector_rs:
            ctx.bar_state.ranked_candidates = active
            return PhaseResult(decision=active, blocked=False, reason="sector data absent → all active",
                               facts={"candidates": len(active), "rotated": False}, metrics={})
        ranked_sectors = sorted(sector_rs.items(), key=lambda kv: (-float(kv[1]), str(kv[0])))
        top = {s for s, _ in ranked_sectors[: self.p.top_sectors]}
        kept = [t for t in active if sector.get(canonical_symbol_key(t)) in top]
        ctx.bar_state.ranked_candidates = kept
        return PhaseResult(decision=kept, blocked=False,
                           reason=f"sector-rotation: {len(kept)} in top-{self.p.top_sectors} sectors {sorted(top)}",
                           facts={"candidates": len(kept), "top_sectors": sorted(top)}, metrics={})

    @property
    def version_marker(self) -> str:
        return "sector_rotation_universe_v1"
