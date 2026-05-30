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
    phase_outputs: dict[str, Any] = field(default_factory=dict)

    def apply(self, kind: str, result: Any) -> None:
        if kind in self.phase_outputs:
            raise ValueError(f"double-write detected for phase kind '{kind}'")
        self.phase_outputs[kind] = result


@dataclass
class PhaseContext:
    qc: Any          # QCAlgorithm read-only refs (Portfolio, Securities, Time, Log)
    time: datetime
    data: Any        # LEAN Slice
    bar_state: BarState = field(default_factory=BarState)
