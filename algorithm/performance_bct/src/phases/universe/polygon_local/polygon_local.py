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
from engine.base import PhaseInterface, PhaseResult, UniverseLoadError
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
            # Fail-loud if date is within the JSON's key range (date-key mismatch = bug)
            if poly:
                min_key = min(poly)
                max_key = max(poly)
                if min_key <= date_str <= max_key:
                    raise UniverseLoadError(
                        f"date_str {date_str!r} not in universe (range {min_key}..{max_key}) — date-key mismatch"
                    )
            # Outside range: no entries for this date
            ctx.bar_state.ranked_candidates = []
            return PhaseResult(
                decision="empty",
                blocked=False,
                reason=f"date {date_str} outside universe range",
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
