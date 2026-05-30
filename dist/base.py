"""Phase interface (Protocol) + result type + engine exceptions.

v2-delta vs v1 arch-a: PhaseInterface is a `typing.Protocol` (@runtime_checkable),
not an ABC. The engine + config depend on the Protocol (structural typing). Phases
MAY subclass `BasePhase` for shared helpers but are not required to.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from context import PhaseContext


class CharterViolation(Exception):
    """Raised at engine init when config violates a charter invariant."""


class UniverseLoadError(Exception):
    """Raised when the universe is empty/unresolved — fail loud, never trade-everything."""


class DependencyError(Exception):
    """Raised at init when a phase's REQUIRES_UPSTREAM is unmet or mis-ordered."""


class ConfigError(Exception):
    """Raised at init when a required phase kind is missing/disabled."""


@dataclass(slots=True)
class PhaseResult:
    decision: Any
    blocked: bool
    reason: str
    facts: dict[str, Any]
    metrics: dict[str, Any]


@runtime_checkable
class PhaseInterface(Protocol):
    """Structural contract every phase satisfies. Engine + config type against this."""

    # Class-level metadata (declared on each phase class).
    PHASE_KIND: str
    REQUIRES_UPSTREAM: list[str]
    PROVIDES_DOWNSTREAM: list[str]

    @property
    def enabled(self) -> bool: ...

    @property
    def version_marker(self) -> str: ...

    def evaluate(self, ctx: PhaseContext) -> PhaseResult: ...


class BasePhase:
    """Optional shared base for phases: stores params/logger, default `enabled`.

    Concrete phases define a nested `Params` dataclass and pass an instance here.
    Subclassing is optional — the engine depends on the Protocol, not this class.
    """

    PHASE_KIND: str = ""
    REQUIRES_UPSTREAM: list[str] = []
    PROVIDES_DOWNSTREAM: list[str] = []

    def __init__(self, params: Any, logger: Any) -> None:
        self._params = params
        self._logger = logger

    @property
    def enabled(self) -> bool:
        return bool(getattr(self._params, "enabled", True))

    @property
    def version_marker(self) -> str:
        raise NotImplementedError

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        raise NotImplementedError
