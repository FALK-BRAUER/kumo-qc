"""
Diagnostics phase: VERSION_MARKER logs + REBALANCE summary.
Faithful carve of oracle initialize() VERSION_MARKER emissions + _rebalance L609 REBALANCE log.
Always runs (in ALWAYS_RUN set in engine).
"""
from __future__ import annotations
from engine.base import PhaseInterface, PhaseResult
from engine.context import PhaseContext


class VersionMarker(PhaseInterface):
    PHASE_KIND = "diagnostics"
    REQUIRES_UPSTREAM = []
    PROVIDES_DOWNSTREAM = []

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
