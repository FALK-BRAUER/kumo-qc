from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class OrderIntent:
    ticker: str
    qty: int
    price: float
    stop: float
    module: str
    risk_dollars: float


@dataclass
class BlockEvent:
    ticker: str
    kind: str
    reason: str
    module: str


@dataclass
class BarState:
    ranked_candidates: list[str] = field(default_factory=list)
    sized_orders: list[OrderIntent] = field(default_factory=list)
    add_intents: list[OrderIntent] = field(default_factory=list)
    exit_intents: list[OrderIntent] = field(default_factory=list)
    trim_intents: list[OrderIntent] = field(default_factory=list)
    blocks: list[BlockEvent] = field(default_factory=list)
    phase_outputs: dict[str, list[Any]] = field(default_factory=dict)
    _seen: set = field(default_factory=set, repr=False)

    def apply(self, kind: str, result: Any, module: str = "") -> None:
        key = (kind, module)
        if key in self._seen:
            raise ValueError(f"double-write detected for phase ({kind!r}, {module!r})")
        self._seen.add(key)
        if kind not in self.phase_outputs:
            self.phase_outputs[kind] = []
        self.phase_outputs[kind].append(result)


@dataclass
class PhaseContext:
    qc: Any          # QCAlgorithm read-only refs (Portfolio, Securities, Time, Log)
    time: datetime
    data: Any        # LEAN Slice
    bar_state: BarState = field(default_factory=BarState)
