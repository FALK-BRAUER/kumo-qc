"""Ranking phase: ScoreDvRanking (#254 catalog, #386 scenario A/C).

Orders the signal winners (bar_state.sized_orders) by trailing DOLLAR-VOLUME descending — the
score-then-DV priority for the capital-constrained fill (the signal already filtered by score; this
ranks the survivors so the cap/sizing takes the highest-liquidity names first). vs B's CompositeRanking
(multi-factor). Reads qc._trailing_dv (ticker.lower → $-vol). RANK-PRESERVING + deterministic.

Kind: ranking · REQUIRES signal · PROVIDES sized_orders · Marker: score_dv_ranking_v1.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any

from engine.base import BasePhase, PhaseResult
from engine.context import PhaseContext


class ScoreDvRanking(BasePhase):
    PHASE_KIND = "ranking"
    REQUIRES_UPSTREAM = ["signal"]
    PROVIDES_DOWNSTREAM = ["sized_orders"]

    @dataclass(slots=True)
    class Params:
        enabled: bool = True

    def __init__(self, params: "ScoreDvRanking.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        dv = getattr(ctx.qc, "_trailing_dv", {})
        ordered = sorted(
            ctx.bar_state.sized_orders,
            key=lambda i: float(dv.get(str(i.ticker).lower(), 0.0)),
            reverse=True,
        )
        ctx.bar_state.sized_orders = ordered
        return PhaseResult(decision=[], blocked=False,
                           reason=f"score-dv ranked {len(ordered)} by trailing $-vol desc",
                           facts={"ranked": len(ordered)}, metrics={})

    @property
    def version_marker(self) -> str:
        return "score_dv_ranking_v1"
