from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from base import BasePhase, PhaseResult, UniverseLoadError
from context import PhaseContext


class DvRankCap(BasePhase):
    PHASE_KIND = "universe"
    REQUIRES_UPSTREAM: list[str] = []
    PROVIDES_DOWNSTREAM: list[str] = ["ranked_candidates"]

    @dataclass(slots=True)
    class Params:
        enabled: bool = True  # cap (coarse_max) lives at the selection gate (single source)

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
            # Zero-candidate day / pre-warmup (the selection gate assigns [] not None).
            ctx.bar_state.ranked_candidates = []
            return PhaseResult(
                decision="empty",
                blocked=False,
                reason=f"no live universe candidates for {date_str}",
                facts={"date": date_str, "count": 0},
                metrics={},
            )

        # PRESERVE RANK ORDER: ranked_today is DV-desc ranked (floored+ranked+capped at the
        # selection gate). Filter to the truly-subscribed active symbols while keeping that
        # order (iterate the ranked list, not the active set) — the #182 fix. Iterating
        # qc._active here would reorder by the set's hash order = nondeterministic.
        # CASE: ranked tickers are lowercase (zip stems / coarse value lowered); QC
        # Symbol.value is uppercase. Match case-insensitively and EMIT the canonical _active
        # value (what the signal phase keys its symbol lookup on, active_by_value[ticker]).
        active_by_lower = {s.value.lower(): s.value for s in getattr(qc, "_active", set())}
        ctx.bar_state.ranked_candidates = [
            active_by_lower[t.lower()] for t in ranked_today if t.lower() in active_by_lower
        ]

        # Diff-ladder TRACKED-CANDIDATE rung: count + sha256 of the emitted ranked_candidates
        # (what is actually tracked this bar) — distinct from the once-daily SELECTION rung.
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
