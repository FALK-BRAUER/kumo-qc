"""Stops-initial phase: SupportAtrStop (#254 catalog, #386 scenario C — the A-vs-C swap).

Initial stop at max(Kijun, support + ATR*atr_mult) — a tighter, structure+volatility floor (vs A's
CloudBottomStop). The lone difference from A on the stops_initial slot, proving fine-grained
single-slot modularity. Records into qc._initial_stops[sym] for each invested position without a stop.

Kind: stops_initial · Clock: DAILY · Marker: support_atr_stop_v1.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Mapping

from engine.base import BasePhase, PhaseResult
from engine.context import PhaseContext


class SupportAtrStop(BasePhase):
    PHASE_KIND = "stops_initial"
    PHASE_RESOLUTION = "daily"
    REQUIRES_UPSTREAM: list[str] = []
    PROVIDES_DOWNSTREAM: list[str] = []

    @dataclass(slots=True)
    class Params:
        atr_mult: float = 0.5
        enabled: bool = True

    def __init__(self, params: "SupportAtrStop.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        qc = ctx.qc
        stops = getattr(qc, "_initial_stops", None)
        if stops is None:
            stops = {}
            qc._initial_stops = stops
        indicators = getattr(qc, "_indicators", {})
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
            ind = indicators.get(sym)
            level = self._support_atr(ind)
            if level is None:
                continue
            stops[sym] = level
            stamped += 1
        return PhaseResult(decision=[], blocked=False,
                           reason=f"support+ATR stops: {stamped} new, {len(stops)} held",
                           facts={"stamped": stamped, "held_stops": len(stops)}, metrics={})

    def _support_atr(self, ind: Mapping[str, Any] | None) -> float | None:
        if not ind:
            return None
        d_ichi = ind.get("d_ichi")
        atr = ind.get("atr")
        if d_ichi is None or not getattr(d_ichi, "is_ready", False):
            return None
        try:
            kijun = float(d_ichi.kijun.current.value)
            atr_v = float(atr.current.value) if atr is not None and getattr(atr, "is_ready", False) else 0.0
        except (AttributeError, TypeError, ValueError):
            return None
        # support proxy = kijun; stop = max(kijun, kijun + atr*mult) → kijun + the ATR cushion above it
        return max(kijun, kijun + atr_v * self.p.atr_mult)

    @property
    def version_marker(self) -> str:
        return "support_atr_stop_v1"
