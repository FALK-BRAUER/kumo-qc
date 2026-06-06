"""Regime phase: VixRegime (#254 catalog, #386 scenario B) - 2-tier VIX gate.

Blocks new longs when VIX is in the high risk-off tier. The scenario runner does not yet guarantee a
runtime VIX feed, so missing VIX defaults to an observable skip rather than a block. A deployable
strategy can flip missing_vix_blocks=True once runtime data is wired and tested.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any

from engine.base import BasePhase, PhaseResult
from engine.context import PhaseContext


class VixRegime(BasePhase):
    PHASE_KIND = "regime"
    REQUIRES_UPSTREAM: list[str] = []
    PROVIDES_DOWNSTREAM: list[str] = []

    @dataclass(slots=True)
    class Params:
        high_threshold: float = 28.0
        missing_vix_blocks: bool = False
        enabled: bool = True

    def __init__(self, params: "VixRegime.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        vix = self._vix_level(ctx.qc)
        if vix is None:
            return PhaseResult(decision="block" if self.p.missing_vix_blocks else "skip",
                               blocked=self.p.missing_vix_blocks,
                               reason="VIX not ready",
                               facts={"regime_ready": False}, metrics={})
        vix = float(vix)
        if vix >= self.p.high_threshold:
            return PhaseResult(decision="block", blocked=True,
                               reason=f"VIX {vix:.1f} >= {self.p.high_threshold} - risk-off",
                               facts={"vix": vix, "threshold": self.p.high_threshold}, metrics={})
        return PhaseResult(decision="pass", blocked=False, reason=f"VIX {vix:.1f} < {self.p.high_threshold}",
                           facts={"vix": vix}, metrics={})

    @staticmethod
    def _vix_level(qc: Any) -> float | None:
        direct = getattr(qc, "vix_level", None)
        if direct is not None:
            return float(direct)
        sym = getattr(qc, "vix", None)
        if sym is None:
            return None
        securities = getattr(qc, "securities", {})
        try:
            sec = securities[sym]
        except (KeyError, TypeError):
            return None
        value = getattr(sec, "price", getattr(sec, "close", None))
        return float(value) if value is not None else None

    @property
    def version_marker(self) -> str:
        return "vix_regime_v1"
