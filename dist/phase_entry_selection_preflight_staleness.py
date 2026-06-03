from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from base import BasePhase, PhaseResult
from symbol_key import canonical_symbol_key
from context import OrderIntent, PhaseContext
from shared_param_space import ComplexityDecl, ParamSpace


def preflight_valid(
    *,
    current_price: float,
    signal_price: float,
    daily_kijun: float,
    gap_up_tolerance_pct: float,
    below_kijun_invalidates: bool,
) -> tuple[bool, str]:
    if signal_price <= 0.0:
        return False, "degraded_signal_price"
    if below_kijun_invalidates and current_price < daily_kijun:
        return False, "below_daily_kijun"
    if current_price < signal_price:
        return False, "gap_down"
    if current_price > signal_price * (1.0 + gap_up_tolerance_pct):
        return False, "excessive_gap_up"
    return True, "ok"


class PreFlightStaleness(BasePhase):
    PHASE_KIND = "entry_selection"
    PHASE_RESOLUTION = "intraday"
    REQUIRES_UPSTREAM = ["signal"]
    PROVIDES_DOWNSTREAM = ["sized_orders"]

    COMPLEXITY = ComplexityDecl(
        free_params=1,
        note="gap_up_tolerance_pct — the asymmetric gap-up chase ceiling (below-Kijun is structural).",
    )

    @dataclass(slots=True)
    class Params:
        gap_up_tolerance_pct: float = 0.10
        below_kijun_invalidates: bool = True
        enabled: bool = True

        @classmethod
        def space(cls) -> ParamSpace:
            return ParamSpace(axes={"gap_up_tolerance_pct": (0.08, 0.10, 0.15)})

    def __init__(self, params: "PreFlightStaleness.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        qc = ctx.qc
        active_by_key = {canonical_symbol_key(s): s for s in getattr(qc, "_active", set())}
        intraday = getattr(qc, "_intraday", {})
        kept: list[OrderIntent] = []
        invalidated = 0
        reasons: dict[str, int] = {}
        for intent in ctx.bar_state.sized_orders:
            sym = active_by_key.get(canonical_symbol_key(intent.ticker))
            if sym is None:
                invalidated += 1
                continue
            snap = qc.snapshot_for_entry(sym)
            if snap is None:
                invalidated += 1
                continue
            st = intraday.get(sym)
            last_close = st.get("last_close") if st else None
            if last_close is None:
                invalidated += 1
                continue
            valid, reason = preflight_valid(
                current_price=float(last_close),
                signal_price=float(snap["signal_price"]),
                daily_kijun=float(snap["daily_kijun"]),
                gap_up_tolerance_pct=self.p.gap_up_tolerance_pct,
                below_kijun_invalidates=self.p.below_kijun_invalidates,
            )
            if valid:
                kept.append(intent)
                ctx.record_funnel("preflight_pass", sym)
            else:
                invalidated += 1
                reasons[reason] = reasons.get(reason, 0) + 1
        ctx.bar_state.sized_orders = kept
        return PhaseResult(
            decision=kept,
            blocked=False,
            reason=f"pre-flight: kept {len(kept)}, invalidated {invalidated} {reasons}",
            facts={"kept": len(kept), "invalidated": invalidated, **{f"reason_{k}": v for k, v in reasons.items()}},
            metrics={},
        )

    @property
    def version_marker(self) -> str:
        return "preflight_staleness_v1"
