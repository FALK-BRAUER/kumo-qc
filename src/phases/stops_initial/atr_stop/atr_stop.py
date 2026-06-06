"""Stops-initial phase: AtrStop (#254 catalog, #386 scenario B)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine.base import BasePhase, PhaseResult
from engine.context import PhaseContext
from engine.symbol_key import canonical_symbol_key


class AtrStop(BasePhase):
    PHASE_KIND = "stops_initial"
    PHASE_RESOLUTION = "daily"
    REQUIRES_UPSTREAM: list[str] = []
    PROVIDES_DOWNSTREAM: list[str] = []

    @dataclass(slots=True)
    class Params:
        atr_mult: float = 2.5
        fallback_stop_pct: float = 0.10
        enabled: bool = True

    def __init__(self, params: "AtrStop.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        qc = ctx.qc
        stops = getattr(qc, "_initial_stops", None)
        if stops is None:
            stops = {}
            qc._initial_stops = stops
        stamped = 0
        for sym in list(getattr(qc, "_active", set())):
            if sym in stops:
                continue
            try:
                holding = qc.portfolio[sym]
            except (KeyError, TypeError):
                continue
            if not getattr(holding, "invested", False):
                continue
            price = float(getattr(qc.securities[sym], "price", getattr(qc.securities[sym], "close", 0.0)))
            if price <= 0.0:
                continue
            atr = self._atr(qc, sym)
            stop = price - self.p.atr_mult * atr if atr is not None else price * (1.0 - self.p.fallback_stop_pct)
            stops[sym] = max(stop, 0.01)
            stamped += 1
        return PhaseResult(
            decision=[],
            blocked=False,
            reason=f"ATR stops: {stamped} new, {len(stops)} held",
            facts={"stamped": stamped, "held_stops": len(stops)},
            metrics={},
        )

    @staticmethod
    def _atr(qc: Any, sym: Any) -> float | None:
        ind = getattr(qc, "_indicators", {}).get(sym, {})
        atr = ind.get("atr") if isinstance(ind, dict) else None
        if atr is not None and getattr(atr, "is_ready", False):
            return float(atr.current.value)
        atr_map = {canonical_symbol_key(k): v for k, v in getattr(qc, "_atr", {}).items()}
        value = atr_map.get(canonical_symbol_key(sym))
        return float(value) if value is not None else None

    @property
    def version_marker(self) -> str:
        return "atr_stop_v1"
