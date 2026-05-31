"""Universe phase: RANK + CAP (#220 / #238 / R1) — consumes the FILTER phase's eligible set.

Kind:    universe
Marker:  dv_rank_cap_v1
Params:  enabled=True
         (NO coarse_max — the cap (scan breadth) is the SINGLE source lean_entry.COARSE_MAX,
          read off qc. A second coarse_max here was dead/drift-prone, #238 dedup.)

MODEL (#238 / R1 UN-FUSE, Falk — filter floors FIRST, this phase ranks the survivors):
  - R1 un-fuses the formerly-fused filter+rank. The FILTER phase (tradeability_floors) reads
    the shared-upstream `qc._bar_metrics`, applies the floors, and emits `bar_state.eligible`
    (canonical uppercase, ∩ active). This RANK phase consumes that `eligible` list, ranks it
    DV-desc (ticker-asc tiebreak) using `qc._trailing_dv`, caps to `qc.COARSE_MAX`, and emits
    `bar_state.ranked_candidates` in rank order. NO stored universe file (the 326 scar).
  - THE #182 FIX (now at the consumer): the ranked order is produced by ITERATING the ranked
    list (rank_and_cap's sort output), NOT the active set (iterating qc._active would reorder
    by the set's hash order = nondeterministic, local≠cloud). SELECTION still happens
    downstream (bct_score_full, score>=7).
  - The cap is `qc.COARSE_MAX` (scan breadth — NOT a position count, NOT a frozen 326), read
    off qc as the single source (lean_entry.COARSE_MAX). This phase carries no cap param.

REQUIRES_UPSTREAM:
  - Declared as ["filter"] — the engine validates REQUIRES_UPSTREAM against phase KINDS (see
    engine._validate_dependencies + the existing convention: signal REQUIRES_UPSTREAM=["universe"],
    sizing=["signal"]). "filter" is the kind that PROVIDES_DOWNSTREAM "eligible"; declaring the
    KIND (not the provides-string "eligible") is what the validator accepts, and it enforces the
    R1 ordering: filter (PHASE_ORDER idx 1) precedes universe (idx 2) → validation passes.
    [Spec asked for ["eligible"]; that is a provides-string, not a kind — the validator would
     raise DependencyError on it. Used the kind-correct ["filter"], same intent. FLAGGED.]

Fail-loud (the #182 lessons):
  - The wiring fail-loud (None → raise) now lives in the FILTER phase (it reads the upstream
    `_bar_metrics`). This phase consumes a BOUNDED list (`bar_state.eligible`, default []) →
    no fall-through-all risk: an empty/absent eligible can only ever yield empty candidates.
  - empty eligible -> empty candidates, NO raise (zero-candidate / pre-warmup day).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine.base import BasePhase, PhaseResult
from engine.context import PhaseContext
from runtime.universe_select import rank_and_cap


class DvRankCap(BasePhase):
    PHASE_KIND = "universe"
    REQUIRES_UPSTREAM: list[str] = ["filter"]  # depends on the filter kind (PROVIDES "eligible")
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
        eligible = ctx.bar_state.eligible  # always a list (default []), never None

        if not eligible:
            # Zero-candidate / pre-warmup day -> empty, NEVER raise.
            ctx.bar_state.ranked_candidates = []
            return PhaseResult(
                decision="empty",
                blocked=False,
                reason=f"no live universe candidates for {date_str}",
                facts={"date": date_str, "count": 0},
                metrics={},
            )

        # RANK + CAP: eligible (canonical uppercase, from the filter phase) ranked DV-desc
        # (ticker-asc tiebreak) via qc._trailing_dv, capped to qc.COARSE_MAX (single source).
        # rank_and_cap's dv lookup is case-insensitive (eligible uppercase, dv keys lowercase).
        dv = getattr(qc, "_trailing_dv", {})
        coarse_max = getattr(qc, "COARSE_MAX", 9999)
        ctx.bar_state.ranked_candidates = rank_and_cap(eligible, dv, coarse_max=coarse_max)
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
