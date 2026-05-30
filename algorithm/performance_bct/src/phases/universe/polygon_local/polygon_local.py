"""
Universe phase: per-day polygon snapshot filter.
Reads self._polygon_universe (set in Initialize) and restricts ranked_candidates
to today's snapshot tickers. Faithful carve of oracle _rebalance L522-530.

NOTE: Universe LOADING (add_equity for all tickers) stays in algorithm Initialize()
for the ARCH-C carve. This phase only handles the per-bar daily filter.
After #182 unified loader lands and ARCH-D harness is wired, Initialize loading
will move here as a proper universe.source phase.
"""
from __future__ import annotations
from engine.base import PhaseInterface, PhaseResult
from engine.context import PhaseContext


class PolygonLocal(PhaseInterface):
    PHASE_KIND = "universe"
    REQUIRES_UPSTREAM = []
    PROVIDES_DOWNSTREAM = ["ranked_candidates"]

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        qc = ctx.qc
        date_str = ctx.time.strftime("%Y-%m-%d")
        poly = getattr(qc, "_polygon_universe", None)

        if poly is None:
            # No universe loaded — pass through all active symbols (oracle fallback)
            ctx.bar_state.ranked_candidates = [str(s) for s in getattr(qc, "_active", set())]
            return PhaseResult(
                decision="all",
                blocked=False,
                reason="no polygon_universe — all active symbols",
                facts={"count": len(ctx.bar_state.ranked_candidates)},
                metrics={},
            )

        today_list = poly.get(date_str)
        if today_list is None:
            # Missing date = non-trading day (weekend/holiday) — legitimately absent from JSON.
            # The schedule fires every_day() but JSON keys are trading days only.
            # NOT fail-loud: the date-key FORMAT mismatch bug class (e.g. "20250102" vs
            # "2025-01-02") manifests as ALL dates missing, caught by the whole-universe
            # empty guard in the loader (main.py Initialize), not per-bar here.
            ctx.bar_state.ranked_candidates = []
            return PhaseResult(
                decision="empty",
                blocked=False,
                reason=f"date {date_str} not a trading day in universe",
                facts={"date": date_str, "count": 0},
                metrics={},
            )

        today_set = set(today_list)
        ctx.bar_state.ranked_candidates = [
            s.value for s in getattr(qc, "_active", set())
            if s.value in today_set
        ]
        return PhaseResult(
            decision="filtered",
            blocked=False,
            reason=f"{len(ctx.bar_state.ranked_candidates)} candidates for {date_str}",
            facts={"date": date_str, "count": len(ctx.bar_state.ranked_candidates)},
            metrics={},
        )

    @property
    def version_marker(self) -> str:
        return "polygon_local_v1"
