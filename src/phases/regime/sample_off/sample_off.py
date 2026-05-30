"""Sample regime phase — DISABLED in the build-sample config.

Exists to prove the closure EXCLUDES disabled phases (must NOT appear in dist/).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine.base import BasePhase, PhaseResult
from engine.context import PhaseContext


class SampleOff(BasePhase):
    PHASE_KIND = "regime"
    REQUIRES_UPSTREAM: list[str] = []
    PROVIDES_DOWNSTREAM: list[str] = []

    @dataclass(slots=True)
    class Params:
        enabled: bool = False

    def __init__(self, params: "SampleOff.Params", logger: Any) -> None:
        super().__init__(params, logger)

    @property
    def version_marker(self) -> str:
        return "sample_off_v1"

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        return PhaseResult(decision=None, blocked=False, reason="off", facts={}, metrics={})
