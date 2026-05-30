"""Diagnostics phase: VERSION_MARKER logs + REBALANCE summary.

Kind: diagnostics
Marker: version_marker_v1
Tested params: enabled=True (champion-asis-v1; no overrides)
Charter: single code path, always runs (ALWAYS_RUN set in engine), never blocks.
Faithful carve of oracle initialize() VERSION_MARKER emissions + _rebalance L609
REBALANCE log (baseline-oracle-v0).
DO NOT modify evaluate() logic — breaks champion-asis-v1 parity (ARCH-C ±0.01 gate).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine.base import BasePhase, PhaseResult
from engine.context import PhaseContext


class VersionMarker(BasePhase):
    PHASE_KIND = "diagnostics"
    REQUIRES_UPSTREAM: list[str] = []
    PROVIDES_DOWNSTREAM: list[str] = []

    @dataclass(slots=True)
    class Params:
        enabled: bool = True

    def __init__(self, params: "VersionMarker.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        qc = ctx.qc
        date_str = ctx.time.strftime("%Y-%m-%d")

        # Count results from prior phases for REBALANCE summary log
        sized = ctx.bar_state.sized_orders
        exits = ctx.bar_state.exit_intents
        adds = ctx.bar_state.add_intents

        # Open count from sizing phase facts (if available)
        sizing_outputs = ctx.bar_state.phase_outputs.get("sizing", [])
        open_count = sizing_outputs[-1].facts.get("open", 0) if sizing_outputs else 0
        new_entries = len(sized)

        qc.log(f"REBALANCE|{date_str}|open={open_count}|new_entries={new_entries}|exits={len(exits)}")

        return PhaseResult(
            decision="logged",
            blocked=False,
            reason="version markers + rebalance summary logged",
            facts={"date": date_str, "entries": new_entries, "exits": len(exits)},
            metrics={},
        )

    @property
    def version_marker(self) -> str:
        return "version_marker_v1"
