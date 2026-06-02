"""Sizing phase: flat POSITION_PCT + committed_cash heat-cap.

Kind: sizing
Marker: flat_pct_heatcap_v1
Tested params: position_pct=0.10 (champion default)
Charter: single code path, NO count/slot caps — exposure governed by the cash heat-cap
only (and gross_exposure_cap when it lands). Ranks come from the signal phase; fills
each candidate at position_pct of portfolio value until cash is exhausted.

Logic carried from the oracle sizing loop, with the slot machinery REMOVED per the
no-fixed-slots charter (the old max_positions/vix_tier slot cap was a 9999 no-op — its
removal is behavior-identical: cash was always the binding constraint).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from engine.base import BasePhase, PhaseResult
from engine.context import OrderIntent, PhaseContext
from phases.shared.param_space import ComplexityDecl, ParamSpace


class FlatPctHeatcap(BasePhase):
    PHASE_KIND = "sizing"
    REQUIRES_UPSTREAM = ["signal"]
    PROVIDES_DOWNSTREAM = ["sized_orders"]

    # ADR D5: champion sizer has no swept axes (single canonical position_pct).
    COMPLEXITY = ComplexityDecl(
        free_params=0,
        note="position_pct is fixed-canonical (0.10); no sweepable axes.",
    )

    @dataclass(slots=True)
    class Params:
        position_pct: float = 0.10
        # #276b-1: STRUCTURAL clock selector (NOT a swept axis). The entry-execution chain
        # (entry_selection→…→sizing→…→FIRE_ENTRIES) must share ONE clock; an intraday champion
        # (champion_intraday) sizes the CONFIRMED entry on the intraday clock → resolution="intraday".
        # A daily config/fixture keeps "daily". The engine entry-chain-clock guard fails loud if a
        # chain phase's clock mismatches FIRE_ENTRIES — so this must match the entry clock.
        resolution: str = "daily"
        enabled: bool = True

        # #276b-1: `resolution` is STRUCTURAL (clock-routing), NOT a behavioral axis — it is
        # phase-determined (intraday entry phases → intraday chain, enforced by the chain-clock
        # guard) so it is redundant for the config's behavioral identity. Excluded from the
        # config_hash (and from space()) → champion-asis stays at its e573e84b1ce1 baseline when the
        # shared sizer gains this knob; a real param (position_pct) change still moves the hash.
        _HASH_EXCLUDE: ClassVar[frozenset[str]] = frozenset({"resolution"})

        @classmethod
        def space(cls) -> ParamSpace:
            """Sweepable axes: none (champion sizer is fixed-canonical; resolution is structural)."""
            return ParamSpace(axes={})

    def __init__(self, params: "FlatPctHeatcap.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params
        # per-instance clock (config picks it; default daily) — the #276b-1 entry-chain clock fix.
        self.PHASE_RESOLUTION = params.resolution

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        qc = ctx.qc
        position_pct = self.p.position_pct

        # Heat-cap (cash) only — no slot count. Fill ranked candidates until cash exhausted.
        committed_cash = 0.0
        available_cash = float(qc.portfolio.cash)
        active_by_value = {s.value: s for s in getattr(qc, "_active", set())}
        filled: list[OrderIntent] = []
        skipped_cash = 0

        for intent in ctx.bar_state.sized_orders:
            sym = active_by_value.get(intent.ticker)
            if sym is None:
                continue
            try:
                price = float(qc.securities[sym].price)
            except Exception:
                continue
            if price <= 0:
                continue

            target_value = float(qc.portfolio.total_portfolio_value) * position_pct
            if available_cash - committed_cash < target_value:
                skipped_cash += 1
                break  # cash exhausted (oracle breaks, not continues)
            # #276b-1 funnel stage 8 (cash_ok): the candidate cleared the cash/heat-cap (a fundable
            # target). Recorded BEFORE the qty>0 cut so cash_ok ⊇ sized — the two stages stay
            # distinguishable (cash-fundable vs actually-sized). Observe-only.
            ctx.record_funnel("cash_ok", sym)

            quantity = int(target_value / price)
            if quantity <= 0:
                continue

            committed_cash += target_value
            ctx.record_funnel("sized", sym)  # #276b-1 funnel stage 7: qty>0 → an order to fire
            filled.append(OrderIntent(
                ticker=intent.ticker,
                qty=quantity,
                price=price,
                stop=0.0,
                module="sizing.flat_pct_heatcap",
                risk_dollars=target_value,
                # PRESERVE the order_type set upstream by entry_timing (#276b-1: ConfirmedMarketEntry
                # sets "market" for the intraday fire). Rebuilding the intent without carrying it
                # reset it to the "market_on_open" default → champion_intraday fired next-open MOO
                # instead of intraday-on-confirm (defeats the model). Carry it forward.
                order_type=intent.order_type,
            ))

        ctx.bar_state.sized_orders = filled
        return PhaseResult(
            decision=filled,
            blocked=False,
            reason=f"{len(filled)} entries sized, {skipped_cash} cash-exhausted",
            facts={"filled": len(filled), "committed_cash": committed_cash, "skipped_cash": skipped_cash},
            metrics={},
        )

    @property
    def version_marker(self) -> str:
        return "flat_pct_heatcap_v1"
