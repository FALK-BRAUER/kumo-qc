"""Sample signal phase — build-closure test fixture (real phases land in #212).

Imports a shared helper to exercise TRANSITIVE closure (build must pull shared too).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine.base import BasePhase, PhaseResult
from engine.context import PhaseContext
from phases.shared.sample_helper import threshold_ok


class SampleBct(BasePhase):
    PHASE_KIND = "signal"
    REQUIRES_UPSTREAM = ["universe"]
    PROVIDES_DOWNSTREAM = ["sized_orders"]

    @dataclass(slots=True)
    class Params:
        min_score: int = 7
        enabled: bool = True

    def __init__(self, params: "SampleBct.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params

    @property
    def version_marker(self) -> str:
        return "sample_bct_v1"

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        ok = threshold_ok(float(self.p.min_score), 7.0)
        return PhaseResult(decision=ok, blocked=False, reason="sample", facts={}, metrics={})
