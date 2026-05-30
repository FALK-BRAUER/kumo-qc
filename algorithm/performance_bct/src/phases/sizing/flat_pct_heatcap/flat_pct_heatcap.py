"""
Sizing phase: flat POSITION_PCT=10% + committed_cash heat-cap loop.
Faithful carve of oracle _rebalance L591-609 (baseline-oracle-v0).
Reads sized_orders (ranked stubs from signal phase), fills qty,
stops adding when cash exhausted. Reads slot cap from vix_tier outputs.
DO NOT modify — breaks champion-asis-v1 parity (ARCH-C ±0.01 gate).
"""
from __future__ import annotations
from engine.base import PhaseInterface, PhaseResult
from engine.context import PhaseContext, OrderIntent


class FlatPctHeatcap(PhaseInterface):
    PHASE_KIND = "sizing"
    REQUIRES_UPSTREAM = ["signal", "regime"]
    PROVIDES_DOWNSTREAM = ["sized_orders"]

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        qc = ctx.qc
        date_str = ctx.time.strftime("%Y-%m-%d")
        position_pct = self._params.get("position_pct", 0.10)
        max_positions_default = self._params.get("max_positions", 9999)

        # Read slot cap from vix_ichimoku_tier output (if present)
        vix_tier_outputs = ctx.bar_state.phase_outputs.get("vix_tier", [])
        max_positions = vix_tier_outputs[-1]["max_positions"] if vix_tier_outputs else max_positions_default

        # Count open positions (excluding currently exiting)
        exiting = {
            o.symbol for o in qc.transactions.get_open_orders()
            if o.quantity < 0
        } if hasattr(qc.transactions, "get_open_orders") else set()

        open_count = sum(
            1 for sym, h in qc.portfolio.items()
            if h.invested and sym not in exiting
        )
        slots = max_positions - open_count
        if slots <= 0:
            ctx.bar_state.sized_orders = []  # clear stubs — nothing to size
            return PhaseResult(
                decision="no_slots",
                blocked=False,
                reason=f"no slots available (open={open_count}, max={max_positions})",
                facts={"open": open_count, "slots": 0},
                metrics={},
            )

        # Heat-cap loop — matches oracle L591-609 exactly
        committed_cash = 0.0
        available_cash = float(qc.portfolio.cash)
        filled: list[OrderIntent] = []
        skipped_cash = 0

        for intent in ctx.bar_state.sized_orders[:slots]:
            # Resolve symbol from ticker string
            price = 0.0
            try:
                active_by_value = {s.value: s for s in getattr(qc, "_active", set())}
                sym = active_by_value.get(intent.ticker)
                if sym is None:
                    continue
                price = float(qc.securities[sym].price)
            except Exception:
                continue

            if price <= 0:
                continue

            target_value = float(qc.portfolio.total_portfolio_value) * position_pct
            if available_cash - committed_cash < target_value:
                skipped_cash += 1
                break  # oracle uses break, not continue

            quantity = int(target_value / price)
            if quantity <= 0:
                continue

            committed_cash += target_value
            filled.append(OrderIntent(
                ticker=intent.ticker,
                qty=quantity,
                price=price,
                stop=0.0,
                module="sizing.flat_pct_heatcap",
                risk_dollars=target_value,
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
