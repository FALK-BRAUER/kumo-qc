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
    # #276a fire-seam: the order TYPE the FIRE_* sentinel dispatches on. Default "market_on_open"
    # = today's behaviour (the fixture/back-compat) → existing configs UNCHANGED. The intraday
    # entry_timing phase sets "market" (fire now intraday on confirm); exits set "stop_market".
    order_type: str = "market_on_open"
    # #290 GTC protective stop: a non-zero level places a resting broker-side stop_market (GTC)
    # alongside the entry on FIRE_ENTRIES — the catastrophic floor UNDER the runtime exit. 0.0 =
    # no protective stop (the fixture/back-compat). Set by the sizer/entry_timing for a champion.
    protective_stop: float = 0.0


@dataclass(slots=True)
class BlockEvent:
    ticker: str
    kind: str
    reason: str
    module: str


@dataclass(slots=True)
class BarState:
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
        key = (kind, module)
        if key in self._seen:
            raise ValueError(f"double-write detected for phase ({kind!r}, {module!r})")
        self._seen.add(key)
        self.phase_outputs.setdefault(kind, []).append(result)


@dataclass(slots=True)
class PhaseContext:
    qc: Any            # QCAlgorithm (Portfolio, Securities, Time, Log) — dynamic, untyped at boundary
    time: datetime
    data: Any          # LEAN Slice
    bar_state: BarState = field(default_factory=BarState)
    clock: str = "daily"  # #274/#275b: which clock this tick runs on — "daily" | "intraday"
