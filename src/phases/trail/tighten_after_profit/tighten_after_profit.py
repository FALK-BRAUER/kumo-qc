"""Trail phase: TightenAfterProfit (#254 catalog, #386 scenario B)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine.base import BasePhase, PhaseResult
from engine.context import PhaseContext


class TightenAfterProfit(BasePhase):
    PHASE_KIND = "trail"
    PHASE_RESOLUTION = "daily"
    REQUIRES_UPSTREAM: list[str] = []
    PROVIDES_DOWNSTREAM: list[str] = []

    @dataclass(slots=True)
    class Params:
        profit_trigger_pct: float = 0.10
        lock_profit_pct: float = 0.02
        enabled: bool = True

    def __init__(self, params: "TightenAfterProfit.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        qc = ctx.qc
        stops = getattr(qc, "_initial_stops", None)
        if stops is None:
            stops = {}
            qc._initial_stops = stops
        tightened = 0
        for sym, holding in list(qc.portfolio.items()):
            if not getattr(holding, "invested", False):
                continue
            meta = getattr(qc, "_position_meta", {}).get(sym, {})
            entry_price = float(meta.get("entry_price", 0.0) or 0.0)
            if entry_price <= 0.0:
                continue
            close = float(getattr(qc.securities[sym], "close", getattr(qc.securities[sym], "price", 0.0)))
            if close < entry_price * (1.0 + self.p.profit_trigger_pct):
                continue
            tightened_stop = entry_price * (1.0 + self.p.lock_profit_pct)
            old = float(stops.get(sym, 0.0) or 0.0)
            if tightened_stop > old:
                stops[sym] = tightened_stop
                tightened += 1
        return PhaseResult(
            decision=[],
            blocked=False,
            reason=f"tighten-after-profit: {tightened} stops raised",
            facts={"tightened": tightened},
            metrics={},
        )

    @property
    def version_marker(self) -> str:
        return "tighten_after_profit_v1"
