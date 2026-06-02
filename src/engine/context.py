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
    # #277: the engine sets this True when a regime/cash phase blocked the bar (entry-side
    # suppressed). lean_entry reads it so the daily REGIME GATE reaches the INTRADAY entry path —
    # a regime-blocked daily bar captures an EMPTY candidate snapshot → no intraday entries that
    # session (the regime gate was previously confined to the daily clock; the intraday gap+loud
    # entries ignored it → over-traded the bad regimes, the W1/W2 robustness loss).
    bar_blocked: bool = False
    # phase_outputs accumulates per kind (lists support multi-sub-phase kinds: regime, exit_*, diagnostics)
    phase_outputs: dict[str, list[Any]] = field(default_factory=dict)
    # #276b-1 FUNNEL instrumentation (the candidate-collapse localizer). An ADDITIVE, observe-only
    # channel: a gate phase records the SYMBOL SET that SURVIVED its stage THIS tick into
    # funnel[<stage>] (canonical Symbols). The runtime (lean_entry) reads these after the intraday
    # clock runs and folds them into per-day-deduped cumulative counters (set membership IS the
    # per-day dedup). NEVER read by the trading loop — it changes ZERO trading behavior; it only
    # localizes where the daily signal (~40 names/day) collapses to ~78 orders/FY (Falk's "78 is too
    # sparse" verdict). Intraday stage keys: preflight_pass, gap_eligible, confirm_fire,
    # injection_survives, sized, cash_ok. (The daily stages signal_winners/regime_pass + the fire
    # stage `orders` accumulate directly in the runtime/engine, not here.)
    funnel: dict[str, set[Any]] = field(default_factory=dict)
    _seen: set[tuple[str, str]] = field(default_factory=set, repr=False)

    def apply(self, kind: str, result: Any, module: str = "") -> None:
        """Record a phase result. Keyed by (kind, module) — raises only on a TRUE duplicate
        (same kind+module twice in one bar), never on legitimate list sub-phases."""
        key = (kind, module)
        if key in self._seen:
            raise ValueError(f"double-write detected for phase ({kind!r}, {module!r})")
        self._seen.add(key)
        self.phase_outputs.setdefault(kind, []).append(result)

    def record_funnel(self, stage: str, symbol: Any) -> None:
        """#276b-1 FUNNEL: record that `symbol` SURVIVED funnel `stage` this tick (additive, observe-
        only). The set is the per-tick survivor set the runtime folds into the cumulative per-day-
        deduped counter. Idempotent within a tick (set add). Changes NO trading behavior."""
        self.funnel.setdefault(stage, set()).add(symbol)


@dataclass(slots=True)
class PhaseContext:
    """LEAN read-only refs + a fresh BarState per bar. Phases never mutate LEAN directly."""
    qc: Any            # QCAlgorithm (Portfolio, Securities, Time, Log) — dynamic, untyped at boundary
    time: datetime
    data: Any          # LEAN Slice
    bar_state: BarState = field(default_factory=BarState)
    clock: str = "daily"  # #274/#275b: which clock this tick runs on — "daily" | "intraday"

    def record_funnel(self, stage: str, symbol: Any) -> None:
        """#276b-1 FUNNEL (delegates to bar_state) — record that `symbol` survived `stage` this tick.
        The phase-facing entry point (a phase holds ctx, not bar_state directly). Observe-only."""
        self.bar_state.record_funnel(stage, symbol)
