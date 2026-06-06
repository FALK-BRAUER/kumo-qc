"""Stops-initial phase: CloudBottomStop (#254 catalog ★★, #386 scenario A).

The initial protective stop at the Ichimoku CLOUD BOTTOM (min Senkou A/B) — the G3 winner (the lone
positive of 20+ stop experiments): a Kijun-dip rides while above the cloud, exit only on a true
structural break below the cloud. Post-FIRE (stops_initial, idx 18): for each INVESTED position without
an initial stop yet, records the cloud-bottom level into qc._initial_stops[sym]. vs C's SupportAtrStop.

Kind: stops_initial · Clock: DAILY · Marker: cloud_bottom_stop_v1.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any

from engine.base import BasePhase, PhaseResult
from engine.context import PhaseContext


def cloud_bottom(d_ichi: Any) -> "float | None":
    """min(Senkou A, Senkou B) — the structural floor. None if the daily Ichimoku isn't ready."""
    if d_ichi is None or not getattr(d_ichi, "is_ready", False):
        return None
    try:
        a = float(d_ichi.senkou_a.current.value)
        b = float(d_ichi.senkou_b.current.value)
    except (AttributeError, TypeError, ValueError):
        return None
    return min(a, b)


class CloudBottomStop(BasePhase):
    PHASE_KIND = "stops_initial"
    PHASE_RESOLUTION = "daily"
    REQUIRES_UPSTREAM: list[str] = []
    PROVIDES_DOWNSTREAM: list[str] = []

    @dataclass(slots=True)
    class Params:
        enabled: bool = True

    def __init__(self, params: "CloudBottomStop.Params", logger: Any) -> None:
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
            cb = cloud_bottom(ind.get("d_ichi") if ind else None)
            if cb is None:
                continue
            stops[sym] = cb
            stamped += 1
        return PhaseResult(decision=[], blocked=False,
                           reason=f"cloud-bottom stops: {stamped} new, {len(stops)} held",
                           facts={"stamped": stamped, "held_stops": len(stops)}, metrics={})

    @property
    def version_marker(self) -> str:
        return "cloud_bottom_stop_v1"
