"""Sizing phase: scanner-rank-aware position sizing plus committed-cash heat-cap.

Kind: sizing
Marker: rank_aware_heatcap_v1

This is an opt-in LambdaMART scanner experiment. It preserves the `FlatPctHeatcap` cash heat-cap
contract, but scales each candidate's per-name target by the scanner rank frozen into the daily
candidate snapshot. The ranker remains a runtime gate/ranker; this phase only consumes the rank
context after the entry candidate has survived the existing intraday confirmation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from engine.base import BasePhase, PhaseResult
from engine.context import OrderIntent, PhaseContext
from engine.symbol_key import canonical_symbol_key
from phases.shared.param_space import ComplexityDecl, ParamSpace


def rank_multiplier(
    *,
    scanner_rank: int | None,
    top_rank_max: int,
    mid_rank_max: int,
    top_multiplier: float,
    mid_multiplier: float,
    tail_multiplier: float,
) -> tuple[float, str]:
    """Return (target multiplier, bucket) for a frozen scanner rank."""
    if scanner_rank is None or scanner_rank <= 0:
        return 0.0, "missing"
    if scanner_rank <= top_rank_max:
        return top_multiplier, "top"
    if scanner_rank <= mid_rank_max:
        return mid_multiplier, "mid"
    return tail_multiplier, "tail"


class RankAwareHeatcap(BasePhase):
    PHASE_KIND = "sizing"
    REQUIRES_UPSTREAM = ["signal", "scanner_ranker_features"]
    PROVIDES_DOWNSTREAM = ["sized_orders"]

    COMPLEXITY = ComplexityDecl(
        free_params=0,
        note="Canonical rank-bucket sizer; sweep grids count bucket knobs explicitly.",
    )

    @dataclass(slots=True)
    class Params:
        position_pct: float = 0.05
        top_rank_max: int = 10
        mid_rank_max: int = 20
        top_multiplier: float = 1.25
        mid_multiplier: float = 1.00
        tail_multiplier: float = 0.50
        resolution: str = "intraday"
        enabled: bool = True

        _HASH_EXCLUDE: ClassVar[frozenset[str]] = frozenset({"resolution"})

        @classmethod
        def space(cls) -> ParamSpace:
            return ParamSpace(axes={})

    def __init__(self, params: "RankAwareHeatcap.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params
        self.PHASE_RESOLUTION = params.resolution

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        qc = ctx.qc
        tpv = float(qc.portfolio.total_portfolio_value)
        committed_cash = 0.0
        available_cash = float(qc.portfolio.cash)
        active_by_key = {canonical_symbol_key(s): s for s in getattr(qc, "_active", set())}
        filled: list[OrderIntent] = []
        skipped_cash = 0
        declined_missing = 0
        declined_zero_target = 0
        bucket_counts: dict[str, int] = {}

        for intent in ctx.bar_state.sized_orders:
            sym = active_by_key.get(canonical_symbol_key(intent.ticker))
            if sym is None:
                continue
            snap = self._snapshot(qc, sym)
            scanner_rank = self._scanner_rank(snap)
            multiplier, bucket = rank_multiplier(
                scanner_rank=scanner_rank,
                top_rank_max=self.p.top_rank_max,
                mid_rank_max=self.p.mid_rank_max,
                top_multiplier=self.p.top_multiplier,
                mid_multiplier=self.p.mid_multiplier,
                tail_multiplier=self.p.tail_multiplier,
            )
            bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1
            if bucket == "missing":
                declined_missing += 1
                continue
            if multiplier <= 0.0:
                declined_zero_target += 1
                continue

            try:
                price = float(qc.securities[sym].price)
            except Exception:
                continue
            if price <= 0.0:
                continue

            target_value = tpv * self.p.position_pct * multiplier
            if available_cash - committed_cash < target_value:
                skipped_cash += 1
                break
            ctx.record_funnel("cash_ok", sym)

            quantity = int(target_value / price)
            if quantity <= 0:
                continue

            committed_cash += target_value
            ctx.record_funnel("sized", sym)
            filled.append(
                OrderIntent(
                    ticker=intent.ticker,
                    qty=quantity,
                    price=price,
                    stop=0.0,
                    module="sizing.rank_aware_heatcap",
                    risk_dollars=target_value,
                    order_type=intent.order_type,
                    protective_stop=intent.protective_stop,
                )
            )

        ctx.bar_state.sized_orders = filled
        return PhaseResult(
            decision=filled,
            blocked=False,
            reason=(
                f"{len(filled)} entries sized by scanner rank, {skipped_cash} cash-exhausted, "
                f"{declined_missing} missing-rank, {declined_zero_target} zero-target"
            ),
            facts={
                "filled": len(filled),
                "committed_cash": committed_cash,
                "skipped_cash": skipped_cash,
                "declined_missing": declined_missing,
                "declined_zero_target": declined_zero_target,
                **{f"bucket_{key}": value for key, value in bucket_counts.items()},
            },
            metrics={},
        )

    @staticmethod
    def _snapshot(qc: Any, sym: Any) -> dict[str, Any] | None:
        snapshot_for_entry = getattr(qc, "snapshot_for_entry", None)
        if callable(snapshot_for_entry):
            return snapshot_for_entry(sym)
        raw = getattr(qc, "_candidate_snapshot", {})
        if isinstance(raw, dict):
            return raw.get(sym)
        return None

    @staticmethod
    def _scanner_rank(snap: dict[str, Any] | None) -> int | None:
        if not snap:
            return None
        value = snap.get("scanner_rank")
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @property
    def version_marker(self) -> str:
        return "rank_aware_heatcap_v1"
