from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class OrderIntent:
    ticker: str
    qty: int
    price: float
    stop: float
    module: str
    risk_dollars: float
    order_type: str = "market_on_open"
    protective_stop: float = 0.0


@dataclass(slots=True)
class BlockEvent:
    ticker: str
    kind: str
    reason: str
    module: str


@dataclass(slots=True)
class BarState:
    ranked_candidates: list[str] = field(default_factory=list)
    sized_orders: list[OrderIntent] = field(default_factory=list)
    add_intents: list[OrderIntent] = field(default_factory=list)
    exit_intents: list[OrderIntent] = field(default_factory=list)
    trim_intents: list[OrderIntent] = field(default_factory=list)
    blocks: list[BlockEvent] = field(default_factory=list)
    bar_blocked: bool = False
    phase_outputs: dict[str, list[Any]] = field(default_factory=dict)
    funnel: dict[str, set[Any]] = field(default_factory=dict)
    _seen: set[tuple[str, str]] = field(default_factory=set, repr=False)

    def apply(self, kind: str, result: Any, module: str = "") -> None:
        key = (kind, module)
        if key in self._seen:
            raise ValueError(f"double-write detected for phase ({kind!r}, {module!r})")
        self._seen.add(key)
        self.phase_outputs.setdefault(kind, []).append(result)

    def record_funnel(self, stage: str, symbol: Any) -> None:
        self.funnel.setdefault(stage, set()).add(symbol)


@dataclass(slots=True)
class PhaseContext:
    qc: Any
    time: datetime
    data: Any
    bar_state: BarState = field(default_factory=BarState)
    clock: str = "daily"

    def record_funnel(self, stage: str, symbol: Any) -> None:
        self.bar_state.record_funnel(stage, symbol)
