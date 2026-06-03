from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from base import BasePhase, PhaseResult, UniverseLoadError
from symbol_key import canonical_symbol_key
from context import PhaseContext


class DvRankCap(BasePhase):
    PHASE_KIND = "universe"
    REQUIRES_UPSTREAM: list[str] = []
    PROVIDES_DOWNSTREAM: list[str] = ["ranked_candidates"]

    @dataclass(slots=True)
    class Params:
        enabled: bool = True

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
                f"trade-everything (selection-gate wiring bug; fix lean_entry._coarse_"
                f"selection). Never pass-through-all."
            )

        if not ranked_today:
            ctx.bar_state.ranked_candidates = []
            return PhaseResult(
                decision="empty",
                blocked=False,
                reason=f"no live universe candidates for {date_str}",
                facts={"date": date_str, "count": 0},
                metrics={},
            )

        active_by_key = {canonical_symbol_key(s): s.value for s in getattr(qc, "_active", set())}
        ctx.bar_state.ranked_candidates = [
            active_by_key[canonical_symbol_key(t)] for t in ranked_today if canonical_symbol_key(t) in active_by_key
        ]

        cands = ctx.bar_state.ranked_candidates
        h = sha256(",".join(cands).encode("utf-8")).hexdigest()
        qc.log(f"TRACKED_CANDIDATES|{date_str}|count={len(cands)}|hash={h}")

        return PhaseResult(
            decision="ranked",
            blocked=False,
            reason=f"{len(cands)} ranked candidates for {date_str}",
            facts={"date": date_str, "count": len(cands)},
            metrics={},
        )

    @property
    def version_marker(self) -> str:
        return "dv_rank_cap_v1"
