"""Universe phase: RANK + CAP (#220 / #238) — consumes the LIVE-selected ranked order.

Kind:    universe
Marker:  dv_rank_cap_v1
Params:  enabled=True
         (the tradeability floors + the DV-desc rank + the coarse_max cap ALL live in the
          live selection runtime.universe_select.select_live_universe, capped via
          lean_entry.COARSE_MAX — the SINGLE source. This phase only EXPOSES the already-
          filtered+ranked+capped live order to the bar_state; it carries no cap param of its
          own, #238 dedup: a second coarse_max here was dead/drift-prone.)

MODEL (#238 live-coarse integration, Falk — filter→rank+cap computed LIVE, no file):
  - runtime.lean_entry._coarse_selection computes the universe ONCE-DAILY from QC's coarse
    feed (ground truth) via select_live_universe (filter→rank→cap) and stores the ranked
    ticker order on `qc._ranked_today` (DV-desc, ticker-asc tiebreak, capped). NO stored
    universe file (the 326 scar). This phase reads that live ranked order and emits
    `ranked_candidates` IN RANK ORDER, intersected with the truly-subscribed set. The cap
    (lean_entry.COARSE_MAX, scan breadth — NOT a position count, NOT a frozen 326) is already
    applied in select_live_universe; this phase does NOT re-cap.
  - THE #182 FIX (now at the consumer): the ranked order is preserved by ITERATING the
    ranked list, NOT the active set (iterating qc._active would reorder by the set's hash
    order = nondeterministic, local≠cloud). SELECTION still happens downstream
    (bct_score_full, score>=7).
  - REQUIRES_UPSTREAM is [] by design: the live selection (lean_entry) feeds qc._ranked_today
    before the engine runs; this phase reads that runtime state, not an upstream bar_state.

Fail-loud (the #182 lessons):
  - `_ranked_today` is None -> FAIL LOUD (raise). Never pass-through-all (the 19k
                              fall-through trap). Absent at runtime = a wiring bug (the live
                              selection must always assign it, [] on a zero-candidate day).
  - empty ranked list      -> empty candidates, NO raise (zero-candidate / pre-warmup day).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine.base import BasePhase, PhaseResult, UniverseLoadError
from engine.context import PhaseContext


class DvRankCap(BasePhase):
    PHASE_KIND = "universe"
    REQUIRES_UPSTREAM: list[str] = []
    PROVIDES_DOWNSTREAM: list[str] = ["ranked_candidates"]

    @dataclass(slots=True)
    class Params:
        enabled: bool = True  # cap (coarse_max) lives in lean_entry.COARSE_MAX (single source)

    def __init__(self, params: "DvRankCap.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        qc = ctx.qc
        date_str = ctx.time.strftime("%Y-%m-%d")
        ranked_today = getattr(qc, "_ranked_today", None)

        if ranked_today is None:
            raise UniverseLoadError(
                f"dv_rank_cap: _ranked_today not set on {date_str} — refusing to "
                f"trade-everything (live selection wiring bug; fix lean_entry._coarse_"
                f"selection). Never pass-through-all."
            )

        if not ranked_today:
            # Zero-candidate day / pre-warmup (the live selection assigns [] not None).
            ctx.bar_state.ranked_candidates = []
            return PhaseResult(
                decision="empty",
                blocked=False,
                reason=f"no live universe candidates for {date_str}",
                facts={"date": date_str, "count": 0},
                metrics={},
            )

        # PRESERVE RANK ORDER: ranked_today is DV-desc ranked (from select_live_universe).
        # Filter to the truly-subscribed active symbols while keeping that order (iterate the
        # ranked list, not the active set) — the #182 fix. Iterating qc._active here would
        # reorder by the set's hash order = nondeterministic.
        # CASE: ranked tickers are lowercase (zip stems / coarse value lowered); QC
        # Symbol.value is uppercase. Match case-insensitively and EMIT the canonical _active
        # value (what the signal phase keys its symbol lookup on, active_by_value[ticker]).
        active_by_lower = {s.value.lower(): s.value for s in getattr(qc, "_active", set())}
        ctx.bar_state.ranked_candidates = [
            active_by_lower[t.lower()] for t in ranked_today if t.lower() in active_by_lower
        ]
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
