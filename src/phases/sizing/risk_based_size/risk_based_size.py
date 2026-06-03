"""Sizing phase: RISK-BASED position size (#339 RUN S2).

Kind: sizing · Marker: risk_based_size_v1

Size each entry by a FIXED DOLLAR RISK to the protective stop (the cloud bottom), capped at a max %
of equity. Risking $R with a stop at cloud_bottom → per-share risk = (entry − cloud_bottom); shares
= R / (entry − cloud_bottom); position_value = shares × entry = R / stop_frac where stop_frac =
(entry − cloud_bottom)/entry. Capped at position_cap × equity. So a TIGHT stop (entry near its cloud)
→ bigger position (up to the cap); a WIDE stop → smaller. This RISK-NORMALIZES the book: choppy
wide-stop names get less capital, tight-structure names get more — fitting more names + sizing by
conviction-risk rather than flat notional. The cloud_bottom is the #339 decision-day snapshot floor
(same level CloudProtectiveStop stamps + CloudAdherenceTrail trails).

Cash heat-cap loop identical to FlatPctHeatcap (fill ranked candidates until cash exhausted; cash is
the binding constraint, no slot count). Degenerate stop (cloud_bottom >= entry → stop_frac <= 0, the
protective_stop phase will DECLINE it downstream) → fall back to the cap so sizing never divides by
zero/negative. No snapshot (H1) → skip; stale snapshot → snapshot_for_entry raises (H2, propagate).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from engine.base import BasePhase, PhaseResult
from engine.context import OrderIntent, PhaseContext
from engine.symbol_key import canonical_symbol_key
from phases.shared.param_space import ComplexityDecl, ParamSpace


class RiskBasedSize(BasePhase):
    PHASE_KIND = "sizing"
    REQUIRES_UPSTREAM = ["signal"]
    PROVIDES_DOWNSTREAM = ["sized_orders"]

    COMPLEXITY = ComplexityDecl(free_params=0, note="risk_dollars/position_cap fixed-canonical; no swept axes.")

    @dataclass(slots=True)
    class Params:
        risk_dollars: float = 500.0   # $ risked to the cloud-bottom stop per position
        position_cap: float = 0.10    # max position as a fraction of equity (tight-stop ceiling)
        resolution: str = "daily"     # structural clock selector (see FlatPctHeatcap)
        enabled: bool = True

        _HASH_EXCLUDE: ClassVar[frozenset[str]] = frozenset({"resolution"})

        @classmethod
        def space(cls) -> ParamSpace:
            return ParamSpace(axes={})

    def __init__(self, params: "RiskBasedSize.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params
        self.PHASE_RESOLUTION = params.resolution

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        qc = ctx.qc
        risk = self.p.risk_dollars
        cap = self.p.position_cap
        equity = float(qc.portfolio.total_portfolio_value)
        committed_cash = 0.0
        available_cash = float(qc.portfolio.cash)
        active_by_key = {canonical_symbol_key(s): s for s in getattr(qc, "_active", set())}
        filled: list[OrderIntent] = []
        skipped_cash = 0

        cap_value = equity * cap
        for intent in ctx.bar_state.sized_orders:
            sym = active_by_key.get(canonical_symbol_key(intent.ticker))
            if sym is None:
                continue
            try:
                price = float(qc.securities[sym].price)
            except Exception:  # noqa: BLE001
                continue
            if price <= 0:
                continue

            # risk-based target: R / stop_frac, capped. stop = the decision-day cloud bottom.
            snap = qc.snapshot_for_entry(sym)  # H1 None → skip; H2 stale → raises (propagate)
            if snap is None:
                continue
            cb = snap.get("daily_cloud_bottom")
            if cb is None:
                continue  # no cloud-bottom stamped → can't risk-size → skip (never silently undersize)
            cloud_bottom = float(cb)
            stop_dist = price - cloud_bottom
            if stop_dist > 0:
                risk_value = risk * price / stop_dist            # = R / stop_frac
                target_value = min(risk_value, cap_value)
            else:
                target_value = cap_value  # degenerate (stop>=entry) → cap; protective_stop declines it later

            if available_cash - committed_cash < target_value:
                skipped_cash += 1
                break  # cash exhausted
            ctx.record_funnel("cash_ok", sym)

            quantity = int(target_value / price)
            if quantity <= 0:
                continue
            committed_cash += target_value
            ctx.record_funnel("sized", sym)
            filled.append(OrderIntent(
                ticker=intent.ticker, qty=quantity, price=price, stop=0.0,
                module="sizing.risk_based_size", risk_dollars=risk, order_type=intent.order_type,
            ))

        ctx.bar_state.sized_orders = filled
        return PhaseResult(
            decision=filled,
            blocked=False,
            reason=f"{len(filled)} entries risk-sized, {skipped_cash} cash-exhausted",
            facts={"filled": len(filled), "committed_cash": committed_cash, "skipped_cash": skipped_cash},
            metrics={},
        )

    @property
    def version_marker(self) -> str:
        return "risk_based_size_v1"
