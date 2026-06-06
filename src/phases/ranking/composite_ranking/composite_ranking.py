"""Ranking phase: CompositeRanking (#254 catalog, #386 scenario B).

Ranks signal survivors by a multi-factor score instead of the A/C dollar-volume-only ordering.
Runtime may provide qc._composite_score as a direct symbol->score map. Without it, the phase computes a
deterministic fallback score from qc._signal_features, qc._momentum_20d, qc._trailing_dv, and qc._volatility.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import log10
from typing import Any

from engine.base import BasePhase, PhaseResult
from engine.context import OrderIntent, PhaseContext
from engine.symbol_key import canonical_symbol_key


def _canon_map(raw: dict[Any, Any]) -> dict[str, Any]:
    return {canonical_symbol_key(k): v for k, v in (raw or {}).items()}


class CompositeRanking(BasePhase):
    PHASE_KIND = "ranking"
    REQUIRES_UPSTREAM = ["signal"]
    PROVIDES_DOWNSTREAM = ["sized_orders"]

    @dataclass(slots=True)
    class Params:
        score_weight: float = 1.0
        momentum_weight: float = 2.0
        dollar_volume_weight: float = 0.10
        volatility_penalty: float = 1.0
        enabled: bool = True

    def __init__(self, params: "CompositeRanking.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        scored = [(self._score(ctx.qc, intent), intent) for intent in ctx.bar_state.sized_orders]
        scored.sort(key=lambda pair: (-pair[0], canonical_symbol_key(pair[1].ticker)))
        ctx.bar_state.sized_orders = [intent for _score, intent in scored]
        return PhaseResult(
            decision=[],
            blocked=False,
            reason=f"composite ranked {len(scored)} candidates",
            facts={"ranked": len(scored), "top_score": scored[0][0] if scored else None},
            metrics={},
        )

    def _score(self, qc: Any, intent: OrderIntent) -> float:
        key = canonical_symbol_key(intent.ticker)
        override = _canon_map(getattr(qc, "_composite_score", {})).get(key)
        if override is not None:
            return float(override)

        momentum = float(_canon_map(getattr(qc, "_momentum_20d", {})).get(key, 0.0))
        volatility = float(_canon_map(getattr(qc, "_volatility", {})).get(key, 0.0))
        trailing_dv = float(_canon_map(getattr(qc, "_trailing_dv", {})).get(key, 0.0))
        signal_score = self._signal_score(qc, key)
        return (
            self.p.score_weight * signal_score
            + self.p.momentum_weight * momentum
            + self.p.dollar_volume_weight * log10(max(trailing_dv, 0.0) + 1.0)
            - self.p.volatility_penalty * volatility
        )

    @staticmethod
    def _signal_score(qc: Any, key: str) -> float:
        active_by_key = {canonical_symbol_key(s): s for s in getattr(qc, "_active", set())}
        sym = active_by_key.get(key)
        feats = getattr(qc, "_signal_features", {})
        row = feats.get(sym) if sym is not None else None
        if isinstance(row, dict):
            return float(row.get("score", 0.0))
        return 0.0

    @property
    def version_marker(self) -> str:
        return "composite_ranking_v1"
