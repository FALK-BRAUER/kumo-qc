"""Slot-instantiable stub phases for engine tests."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from engine.base import BasePhase, PhaseResult
from engine.config import Slot
from engine.context import PhaseContext


class StubPhase(BasePhase):
    """Slot-instantiable stub. Kind/blocked/requires carried in Params."""

    @dataclass(slots=True)
    class Params:
        kind: str = "signal"
        blocked: bool = False
        requires: tuple[str, ...] = ()
        enabled: bool = True
        resolution: str = "daily"  # #274: "daily" | "intraday" — the clock this stub runs on

    def __init__(self, params: "StubPhase.Params", logger: Any = None) -> None:
        super().__init__(params, logger)
        self.PHASE_KIND = params.kind
        self.PHASE_RESOLUTION = params.resolution
        self.REQUIRES_UPSTREAM = list(params.requires)
        self.PROVIDES_DOWNSTREAM = []
        self._blocked = params.blocked
        self.called = False

    @property
    def version_marker(self) -> str:
        return f"stub_{self.PHASE_KIND}_v1"

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        self.called = True
        return PhaseResult(decision=None, blocked=self._blocked, reason="stub", facts={}, metrics={})


def slot(kind: str, blocked: bool = False, requires: tuple[str, ...] = (), enabled: bool = True,
         resolution: str = "daily") -> Slot[StubPhase.Params]:
    return Slot(impl=StubPhase, params=StubPhase.Params(
        kind=kind, blocked=blocked, requires=requires, enabled=enabled, resolution=resolution), enabled=enabled)
