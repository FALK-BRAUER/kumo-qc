"""Typed direct-ref config — PATTERN EXAMPLE (not a real strategy).

Proves the v2 wiring type-checks under mypy --strict: each Slot binds a phase class
to an instance of that phase's nested `.Params` dataclass. Real strategies
(champion_asis, ...) land in #212 following this exact shape. Underscore-prefixed
so it is never mistaken for an active strategy.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine.base import BasePhase, PhaseResult
from engine.config import Slot, StrategyConfig
from engine.context import PhaseContext


class _ExampleUniverse(BasePhase):
    PHASE_KIND = "universe"
    REQUIRES_UPSTREAM: list[str] = []
    PROVIDES_DOWNSTREAM = ["ranked_candidates"]

    @dataclass(slots=True)
    class Params:
        min_dollar_volume: float = 5_000_000.0
        enabled: bool = True

    def __init__(self, params: "_ExampleUniverse.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params

    @property
    def version_marker(self) -> str:
        return "_example_universe_v1"

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        return PhaseResult(decision=None, blocked=False, reason="example", facts={}, metrics={})


class _ExampleSignal(BasePhase):
    PHASE_KIND = "signal"
    REQUIRES_UPSTREAM = ["universe"]
    PROVIDES_DOWNSTREAM = ["sized_orders"]

    @dataclass(slots=True)
    class Params:
        min_score: int = 7
        enabled: bool = True

    def __init__(self, params: "_ExampleSignal.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params

    @property
    def version_marker(self) -> str:
        return "_example_signal_v1"

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        return PhaseResult(decision=None, blocked=False, reason="example", facts={}, metrics={})


class _ExampleSizing(BasePhase):
    PHASE_KIND = "sizing"
    REQUIRES_UPSTREAM = ["signal"]
    PROVIDES_DOWNSTREAM = ["sized_orders"]

    @dataclass(slots=True)
    class Params:
        position_pct: float = 0.10
        enabled: bool = True

    def __init__(self, params: "_ExampleSizing.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params

    @property
    def version_marker(self) -> str:
        return "_example_sizing_v1"

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        return PhaseResult(decision=None, blocked=False, reason="example", facts={}, metrics={})


# The direct-ref config: impl=class, params=class.Params(...). mypy --strict checks each
# Params construction (field names + types) at THIS site.
EXAMPLE_CONFIG = StrategyConfig(
    name="_example",
    version="0.0.0",
    phases={
        "universe": Slot(impl=_ExampleUniverse, params=_ExampleUniverse.Params(min_dollar_volume=5_000_000.0)),
        "signal": Slot(impl=_ExampleSignal, params=_ExampleSignal.Params(min_score=7)),
        "sizing": Slot(impl=_ExampleSizing, params=_ExampleSizing.Params(position_pct=0.10)),
    },
)
