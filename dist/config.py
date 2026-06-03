from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, TypeVar

from base import BasePhase

P = TypeVar("P")


@dataclass(slots=True)
class Slot(Generic[P]):
    impl: type[BasePhase]
    params: P
    enabled: bool = True


@dataclass(slots=True)
class StrategyConfig:
    name: str
    version: str
    phases: dict[str, "Slot[object] | list[Slot[object]]"] = field(default_factory=dict)
    is_fixture: bool = False
    continuous_weekly: bool = False
