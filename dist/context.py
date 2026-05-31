"""Per-bar execution context and state.

v2: BarState/PhaseContext/intents are `dataclass(slots=True)` (hot per-bar objects).
Ports the v1 arch-a context (parity-proven @ 3705cd3); v2-delta = slots + typing.
"""
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


@dataclass(slots=True)
class BlockEvent:
    ticker: str
    kind: str
    reason: str
    module: str


@dataclass(slots=True)
class BarState:
    """Fresh per bar. Phases write here via the engine; engine fires from the typed lists."""
    # The universe phase emits ranked_candidates (the live-selected floored+ranked+capped
    # order ∩ active; floors+rank computed at the selection gate, lean_entry, under Y). A
    # future real per-bar filter phase (the `filter` KNOWN_KIND seam) would re-add an
    # `eligible` field here — a one-liner if/when needed (YAGNI: not carried today).
    ranked_candidates: list[str] = field(default_factory=list)
    sized_orders: list[OrderIntent] = field(default_factory=list)
    add_intents: list[OrderIntent] = field(default_factory=list)
    exit_intents: list[OrderIntent] = field(default_factory=list)
    trim_intents: list[OrderIntent] = field(default_factory=list)
    blocks: list[BlockEvent] = field(default_factory=list)
    # phase_outputs accumulates per kind (lists support multi-sub-phase kinds: regime, exit_*, diagnostics)
    phase_outputs: dict[str, list[Any]] = field(default_factory=dict)
    _seen: set[tuple[str, str]] = field(default_factory=set, repr=False)

    def apply(self, kind: str, result: Any, module: str = "") -> None:
        """Record a phase result. Keyed by (kind, module) — raises only on a TRUE duplicate
        (same kind+module twice in one bar), never on legitimate list sub-phases."""
        key = (kind, module)
        if key in self._seen:
            raise ValueError(f"double-write detected for phase ({kind!r}, {module!r})")
        self._seen.add(key)
        self.phase_outputs.setdefault(kind, []).append(result)


@dataclass(slots=True)
class PhaseContext:
    """LEAN read-only refs + a fresh BarState per bar. Phases never mutate LEAN directly."""
    qc: Any            # QCAlgorithm (Portfolio, Securities, Time, Log) — dynamic, untyped at boundary
    time: datetime
    data: Any          # LEAN Slice
    bar_state: BarState = field(default_factory=BarState)
