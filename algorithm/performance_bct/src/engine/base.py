from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any
from engine.context import PhaseContext


class CharterViolation(Exception):
    pass


class DependencyError(Exception):
    pass


class ConfigError(Exception):
    pass


class UniverseLoadError(Exception):
    pass


@dataclass
class PhaseResult:
    decision: Any
    blocked: bool
    reason: str
    facts: dict
    metrics: dict


class PhaseInterface(ABC):
    PHASE_KIND: str
    REQUIRES_UPSTREAM: list[str]
    PROVIDES_DOWNSTREAM: list[str]

    def __init__(self, params: dict, logger: Any):
        self._params = params
        self._logger = logger

    @abstractmethod
    def evaluate(self, ctx: PhaseContext) -> PhaseResult: ...

    @property
    @abstractmethod
    def version_marker(self) -> str: ...

    @property
    def enabled(self) -> bool:
        return self._params.get("enabled", True)

    def validate_config(self) -> None:
        pass
