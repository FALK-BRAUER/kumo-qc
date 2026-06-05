"""StubMarketEntry — test-scaffolding entry seam for the engine-lifecycle harnesses.

#386 deleted the implicit market_on_open fire default. The e2e/acceptance harnesses drive
champion_asis (a retired fixture with the #228 entry-seam UNFILLED: universe→signal→regime→sizing→
FIRE, no entry phase), which used to fire through that deleted default. Post-#386 the invariant is
NO fire without an EXPLICIT entry decision — so these harnesses now wire a real (stub) entry seam.

StubMarketEntry stamps order_type="market" on each sized_orders survivor (FlatPctHeatcap preserves
order_type when it fills qty), so FIRE_ENTRIES fires a market order via qc.market_order. It is the
minimal explicit entry seam: it makes the lifecycle harnesses test entry→fill→exit→close under the
NEW model, without the deleted implicit default. Test-only (never codegen'd to cloud).

`with_entry_seam(config)` returns the config with this entry_timing slot inserted — the one-line
adapter the harnesses use to keep driving champion_asis through an explicit entry.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, replace
from typing import Any

from engine.base import BasePhase, PhaseResult
from engine.config import Slot, StrategyConfig
from engine.context import PhaseContext


class StubMarketEntry(BasePhase):
    PHASE_KIND = "entry_timing"
    PHASE_RESOLUTION = "daily"
    # No declared upstream: entry_timing runs BEFORE sizing in PHASE_ORDER and operates on the shared
    # bar_state.sized_orders field (the signal winners), exactly like ConfirmedMarketEntry. An empty
    # list = stamp nothing (no crash). Declaring sized_orders as REQUIRED would wrongly demand an
    # upstream provider that only exists downstream (sizing).
    REQUIRES_UPSTREAM: list[str] = []
    PROVIDES_DOWNSTREAM = ["sized_orders"]

    @dataclass(slots=True)
    class Params:
        enabled: bool = True

    def __init__(self, params: "StubMarketEntry.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        bs = ctx.bar_state
        bs.sized_orders = [replace(i, order_type="market") for i in bs.sized_orders]
        return PhaseResult(decision=[], blocked=False,
                           reason=f"stub market entry: {len(bs.sized_orders)} stamped",
                           facts={"stamped": len(bs.sized_orders)}, metrics={})

    @property
    def version_marker(self) -> str:
        return "stub_market_entry_v1"


def with_entry_seam(config: StrategyConfig) -> StrategyConfig:
    """Return `config` with an explicit StubMarketEntry entry_timing seam (#386 — no implicit MOO)."""
    phases = dict(config.phases)
    phases["entry_timing"] = Slot(impl=StubMarketEntry, params=StubMarketEntry.Params())
    return dataclasses.replace(config, name=f"{config.name}-entryseam", phases=phases)
