"""Entry-trigger phase: StubEntryTrigger — the M1 THROWAWAY per-bar trigger that proves the two-clock
engine plumbing (day-chain ARMS → qc._armed carry → intraday tick FIRES per-bar). NOT a real strategy:
the real triggers (Gap-Momentum, BuyStop, Pullback-Resumption) are M3/Step-2 modules.

Kind: entry_trigger · Clock: INTRADAY (5-min) · Marker: stub_entry_trigger_v1.

CONTRACT (the new intraday entry mechanism, replacing the open-30m window + MOO-default):
  - Reads the framework carry `qc._armed` (a pure state-bus: {sym: {zone, armed_date, ...}}, written by
    the day-chain arming, persisted across days, evicted by the engine on fire/invalidate). This phase
    only READS it + DECIDES per-bar — the arm/invalidate VALUES live in day modules (Scenario-B reuses
    qc._armed unchanged with its own modules → framework, not strategy).
  - PROXIMITY-GATE: evaluate a candidate ONLY when the 5-min close is within `near_pct` of its zone
    (watch ON near the zone). Spreads fires across the day (each name reaches its zone at its own time)
    — the M1 smoke's "fire across the day, not open+EOD".
  - LOOK-AHEAD-SAFE: decides on THIS bar's close + the (already-known) armed zone only — no future/bar-
    close peek. Causal by construction.
  - STUB rule: armed AND near-zone → FIRE (emit a market entry intent for the sizing phase). A real
    trigger would add the if-then (gap-momentum / breakout-through / pullback-bounce); the stub fires on
    proximity alone so M1 exercises the full intraday arm→trigger→size→FIRE_ENTRIES path.
  - Emits a qty=0 market stub to ctx.bar_state.sized_orders (intraday_sizing fills qty; FIRE_ENTRIES
    fires). NO market_on_open — the deleted 2nd-slot default is gone.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine.base import BasePhase, PhaseResult
from engine.context import OrderIntent, PhaseContext


class StubEntryTrigger(BasePhase):
    PHASE_KIND = "entry_trigger"
    PHASE_RESOLUTION = "intraday"
    REQUIRES_UPSTREAM: list[str] = []
    PROVIDES_DOWNSTREAM = ["sized_orders"]

    @dataclass(slots=True)
    class Params:
        near_pct: float = 0.01     # proximity gate: |close - zone|/zone <= near_pct → watch ON
        enabled: bool = True

    def __init__(self, params: "StubEntryTrigger.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        qc = ctx.qc
        armed = getattr(qc, "_armed", None) or {}
        fired: list[str] = []
        for sym, rec in list(armed.items()):
            if getattr(qc.portfolio[sym], "invested", False):
                continue  # already held — not an entry candidate
            zone = rec.get("zone")
            try:
                close = float(qc.securities[sym].close)
            except (KeyError, AttributeError, TypeError, ValueError):
                continue
            if zone is None or zone <= 0:
                continue
            # PROXIMITY-GATE (look-ahead-safe: this bar's close vs the known zone)
            if abs(close - float(zone)) / float(zone) > self.p.near_pct:
                continue
            # STUB FIRE: emit a market entry stub (sizing fills qty, FIRE_ENTRIES fires intraday NOW)
            ctx.bar_state.sized_orders.append(OrderIntent(
                ticker=sym.value if hasattr(sym, "value") else str(sym),
                qty=0, price=close, stop=0.0, module="entry_trigger.stub_trigger",
                risk_dollars=0.0, order_type="market",
            ))
            fired.append(str(sym))
        return PhaseResult(
            decision=fired, blocked=False,
            reason=f"stub entry_trigger: {len(fired)} armed-near-zone fired (intraday)",
            facts={"fired": len(fired), "armed": len(armed)}, metrics={},
        )

    @property
    def version_marker(self) -> str:
        return "stub_entry_trigger_v1"
