"""Entry-selection phase: RiskRewardFilter (#254 catalog, #386 scenario B).

Rejects candidates with reward/risk below min_rr. Missing target/stop references fail open so the
architecture proof can run before support/resistance data is fully wired.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine.base import BasePhase, PhaseResult
from engine.context import OrderIntent, PhaseContext
from engine.symbol_key import canonical_symbol_key


def _lookup(raw: dict[Any, Any], ticker: Any) -> Any:
    cmap = {canonical_symbol_key(k): v for k, v in (raw or {}).items()}
    return cmap.get(canonical_symbol_key(ticker))


class RiskRewardFilter(BasePhase):
    PHASE_KIND = "entry_selection"
    PHASE_RESOLUTION = "daily"
    REQUIRES_UPSTREAM = ["signal"]
    PROVIDES_DOWNSTREAM = ["sized_orders"]

    @dataclass(slots=True)
    class Params:
        min_rr: float = 2.0
        enabled: bool = True

    def __init__(self, params: "RiskRewardFilter.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        kept: list[OrderIntent] = []
        rejected = 0
        missing = 0
        for intent in ctx.bar_state.sized_orders:
            target = self._target(ctx.qc, intent)
            stop = self._stop(ctx.qc, intent)
            if target is None or stop is None:
                missing += 1
                kept.append(intent)
                continue
            price = float(intent.price)
            risk = price - float(stop)
            reward = float(target) - price
            if risk <= 0.0 or reward <= 0.0 or reward / risk < self.p.min_rr:
                rejected += 1
                continue
            kept.append(intent)
        ctx.bar_state.sized_orders = kept
        return PhaseResult(
            decision=[],
            blocked=False,
            reason=f"risk/reward: kept {len(kept)}, rejected {rejected}, missing-ref {missing}",
            facts={"kept": len(kept), "rejected": rejected, "missing_ref": missing},
            metrics={},
        )

    @staticmethod
    def _target(qc: Any, intent: OrderIntent) -> float | None:
        for attr in ("_entry_targets", "_target_prices", "_rr_targets", "_high_52w"):
            value = _lookup(getattr(qc, attr, {}), intent.ticker)
            if value is not None:
                return float(value)
        return None

    @staticmethod
    def _stop(qc: Any, intent: OrderIntent) -> float | None:
        if intent.stop > 0.0:
            return float(intent.stop)
        for attr in ("_entry_stops", "_stop_prices", "_rr_stops", "_support"):
            value = _lookup(getattr(qc, attr, {}), intent.ticker)
            if value is not None:
                return float(value)
        return None

    @property
    def version_marker(self) -> str:
        return "risk_reward_filter_v1"
