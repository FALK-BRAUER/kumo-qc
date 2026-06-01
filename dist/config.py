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
    # kind -> a single Slot or a list of Slots (regime/exit_*/diagnostics are list-kinds)
    phases: dict[str, "Slot[object] | list[Slot[object]]"] = field(default_factory=dict)
    # #270/#272 fail-loud phase-stack gate: a CHAMPION must wire an entry-confirm phase
    # (entry_selection | entry_timing) AND an exit phase (exit_*) — there is no implicit
    # market-on-open default. A config WITHOUT them must explicitly opt in as a FIXTURE
    # (regression/parity scaffolding) or the engine raises DegradedConfigError at init.
    # is_fixture=True is the ONLY way to run an incomplete (blind-entry) stack — never silent.
    is_fixture: bool = False
