"""Universe phase: point-in-time top-N by trailing dollar volume (consumer).

Kind:    universe
Marker:  dynamic_dollar_volume_v1
Params:  n=1500, price_floor=10.0, dv_floor=5_000_000.0, dv_window=20, enabled=True
         (these MIRROR scripts/build_universe.py — the phase does NOT recompute; it
          consumes the precomputed date->set artifact and carries the params purely
          for provenance/fingerprinting.)

Charter (ARCH2-U / #220):
  - n / price_floor / dv_floor / dv_window are universe-BREADTH params — how wide the
    investable set is. They are NEVER position-slot or count caps. No time / hold logic
    lives here.
  - POINT-IN-TIME, NO SNAPSHOT: the precomputed dict is keyed by trading date; each
    date's list was built only from bars dated <= that date (no hindsight,
    survivorship-clean). This phase only does the per-bar lookup + intersect with active.
  - Single code path (local == cloud). The precomputed dict is loaded ONCE in
    Initialize (QCAlgorithm) and stashed as `self._dynamic_universe`; the phase reads
    it from `ctx.qc._dynamic_universe`. NO relative file reads in the phase.

Fail-loud semantics (the #182 lessons — both traps closed):
  - `_dynamic_universe` is None        -> FAIL LOUD (raise). Never pass-through-all-active
                                          (~19k) — that's the #182 fall-through-to-everything
                                          trap. Absent at runtime = a load/wiring bug; a log
                                          warning is not enough (logs-aren't-enough lesson).
  - date not in the dict (any reason)  -> empty set, NO raise. The schedule fires
                                          every_day(); weekends/holidays and zero-eligible
                                          trading days legitimately have no key. Raising
                                          per-day on a missing date is exactly the #182
                                          weekend trap — never do it. No entries that bar.
  The fail-loud for a corrupt/empty universe is at LOAD time (Initialize: artifact empty
  or unparseable -> raise UniverseLoadError before the engine runs). A date-format
  mismatch manifests as ALL dates missing -> caught by that load guard + zero-trades
  signature, not by a per-bar raise.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine.base import BasePhase, PhaseResult, UniverseLoadError
from engine.context import PhaseContext


class DynamicDollarVolume(BasePhase):
    PHASE_KIND = "universe"
    REQUIRES_UPSTREAM: list[str] = []
    PROVIDES_DOWNSTREAM: list[str] = ["ranked_candidates"]

    @dataclass(slots=True)
    class Params:
        n: int = 1500
        price_floor: float = 10.0
        dv_floor: float = 5_000_000.0
        dv_window: int = 20
        enabled: bool = True

    def __init__(self, params: "DynamicDollarVolume.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        qc = ctx.qc
        date_str = ctx.time.strftime("%Y-%m-%d")
        universe = getattr(qc, "_dynamic_universe", None)

        if universe is None:
            # FAIL LOUD — never pass-through-all. _dynamic_universe absent at runtime = a
            # load/wiring bug; trading the entire substrate (~19k) is the #182 fall-through
            # trap (worse than the 326 leak). A log warning is NOT enough (logs-aren't-enough,
            # the contamination lesson) — raise so the bug surfaces, never trade-everything.
            raise UniverseLoadError(
                f"dynamic_dollar_volume: _dynamic_universe not loaded on {date_str} "
                f"— refusing to trade-everything (load/wiring bug; fix Initialize)"
            )

        today_list = universe.get(date_str)
        if today_list is None:
            # Missing date = non-trading day (weekend/holiday) OR zero-eligible day.
            # Empty set, NO raise (the #182 weekend trap — never per-day-raise). The
            # corrupt/empty-artifact fail-loud is at Initialize load time, not here.
            ctx.bar_state.ranked_candidates = []
            return PhaseResult(
                decision="empty",
                blocked=False,
                reason=f"no universe entry for {date_str} (non-trading day or zero-eligible)",
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
        return "dynamic_dollar_volume_v1"
