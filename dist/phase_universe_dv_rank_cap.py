"""Universe phase: RANK + CAP (#220) — consumes the precomputed ranked candidate artifact.

Kind:    universe
Marker:  dv_rank_cap_v1
Params:  coarse_max=9999, enabled=True
         (the tradeability floors moved OUT to the filter phase #233. This phase only
          ranks+caps. coarse_max mirrors scripts/build_universe.py, carried for
          provenance/fingerprint.)

MODEL (#220 rescoped, Falk — filter -> rank+cap, seam (B) two artifacts):
  - The filter phase (#233) gates tradeability and emits the eligible set; the OFFLINE
    build_universe.py ranks that eligible set by dollar-volume DESC (ties ticker ASC) and
    caps to coarse_max, producing the RANKED candidate artifact. This phase consumes that
    artifact at runtime and emits `ranked_candidates` IN RANK ORDER.
  - coarse_max is scan BREADTH (default 9999 = unbounded), NOT a position/slot count. NOT
    a frozen 326.
  - THE #182 FIX: the artifact is stored in rank order and this phase preserves it (it
    iterates the precomputed list, NOT the active set) so local+cloud scan the same set
    in the same order. SELECTION still happens downstream (bct_score_full, score>=7).
  - REQUIRES_UPSTREAM is [] by design: the dependency on the filter is at BUILD time
    (the ranked artifact is built from the filter artifact), not a runtime bar_state read.
    This phase reads its own artifact (`qc._universe`), so it has no upstream bar_state dep.

Fail-loud (the #182 lessons):
  - `_universe` is None  -> FAIL LOUD (raise). Never pass-through-all (the 19k
                            fall-through trap). Absent at runtime = a load/wiring bug.
  - date not in the dict -> empty, NO raise (non-trading day / pre-listing / post-
                            substrate). build_universe preserves every filter date, so a
                            missing date is never a silent gap.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from base import BasePhase, PhaseResult, UniverseLoadError
from context import PhaseContext


class DvRankCap(BasePhase):
    PHASE_KIND = "universe"
    REQUIRES_UPSTREAM: list[str] = []
    PROVIDES_DOWNSTREAM: list[str] = ["ranked_candidates"]

    @dataclass(slots=True)
    class Params:
        coarse_max: int = 9999  # scan breadth after DV-desc rank; 9999 = unbounded
        enabled: bool = True

    def __init__(self, params: "DvRankCap.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        qc = ctx.qc
        date_str = ctx.time.strftime("%Y-%m-%d")
        universe = getattr(qc, "_universe", None)

        if universe is None:
            raise UniverseLoadError(
                f"dv_rank_cap: _universe not loaded on {date_str} — refusing to "
                f"trade-everything (load/wiring bug; fix Initialize). Never pass-through-all."
            )

        today_list = universe.get(date_str)
        if today_list is None:
            # Non-trading day / pre-listing / post-substrate. Empty, NO per-day raise
            # (the #182 weekend trap). build_universe preserves every date → no silent gap.
            ctx.bar_state.ranked_candidates = []
            return PhaseResult(
                decision="empty",
                blocked=False,
                reason=f"no universe entry for {date_str} (non-trading day / out of range)",
                facts={"date": date_str, "count": 0},
                metrics={},
            )

        # PRESERVE RANK ORDER: today_list is DV-desc ranked. Filter to active symbols while
        # keeping that order (iterate the list, not the active set) — the #182 fix. Iterating
        # qc._active here would reorder by the set's hash order = nondeterministic.
        active_vals = {s.value for s in getattr(qc, "_active", set())}
        ctx.bar_state.ranked_candidates = [t for t in today_list if t in active_vals]
        return PhaseResult(
            decision="ranked",
            blocked=False,
            reason=f"{len(ctx.bar_state.ranked_candidates)} ranked candidates for {date_str}",
            facts={"date": date_str, "count": len(ctx.bar_state.ranked_candidates)},
            metrics={},
        )

    @property
    def version_marker(self) -> str:
        return "dv_rank_cap_v1"
