"""Entry-trigger phase: BuyStopTrigger (#254 catalog, #386 scenario B).

Per-bar intraday trigger. For each armed candidate, compute a buy-stop level from the armed zone and
fire when this 5-minute bar trades through that level. This keeps the trigger causal: current bar plus
previously armed state only.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine.base import BasePhase, PhaseResult
from engine.context import OrderIntent, PhaseContext


class BuyStopTrigger(BasePhase):
    PHASE_KIND = "entry_trigger"
    PHASE_RESOLUTION = "intraday"
    REQUIRES_UPSTREAM: list[str] = []
    PROVIDES_DOWNSTREAM = ["sized_orders"]

    @dataclass(slots=True)
    class Params:
        breakout_pct: float = 0.0
        enabled: bool = True

    def __init__(self, params: "BuyStopTrigger.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        qc = ctx.qc
        fired: list[str] = []
        for sym, rec in list((getattr(qc, "_armed", None) or {}).items()):
            if getattr(qc.portfolio[sym], "invested", False):
                continue
            zone = self._zone(rec)
            if zone is None or zone <= 0.0:
                continue
            buy_stop = float(rec.get("buy_stop", zone * (1.0 + self.p.breakout_pct)))
            sec = qc.securities[sym]
            bar_high = float(getattr(sec, "high", getattr(sec, "close", getattr(sec, "price", 0.0))))
            close = float(getattr(sec, "close", getattr(sec, "price", bar_high)))
            if bar_high < buy_stop:
                continue
            ctx.bar_state.sized_orders.append(OrderIntent(
                ticker=sym.value if hasattr(sym, "value") else str(sym),
                qty=0,
                price=close,
                stop=float(rec.get("stop", 0.0) or 0.0),
                module="entry_trigger.buy_stop",
                risk_dollars=0.0,
                order_type="market",
            ))
            fired.append(str(getattr(sym, "value", sym)))
        return PhaseResult(
            decision=fired,
            blocked=False,
            reason=f"buy-stop trigger: {len(fired)} armed names crossed stop",
            facts={"fired": len(fired), "armed": len(getattr(qc, "_armed", {}) or {})},
            metrics={},
        )

    @staticmethod
    def _zone(rec: dict[str, Any]) -> float | None:
        for key in ("entry_zone", "zone", "price"):
            value = rec.get(key)
            if value is not None:
                return float(value)
        return None

    @property
    def version_marker(self) -> str:
        return "buy_stop_trigger_v1"
