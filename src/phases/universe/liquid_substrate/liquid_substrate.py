"""Universe phase: full liquid substrate via tradeability FLOORS only (consumer).

Kind:    universe
Marker:  liquid_substrate_v1
Params:  min_price=5.0, min_avg_dollar_volume=5_000_000, adv_window=20, enabled=True
         (mirror scripts/build_universe.py — the phase consumes the precomputed
          date->eligible-set artifact; the floors live in the precompute. Params carried
          for provenance/fingerprint.)

MODEL (re-grounded #220, Falk):
  - The universe is NOT a top-N / fixed-size cut. It is EVERY name that clears the
    tradeability FLOORS that day: price >= min_price AND trailing-adv_window mean dollar
    volume >= min_avg_dollar_volume. Variable size. No N, no DV ranking, no cap.
  - The floor gates TRADEABILITY (liquid-enough-to-trade). It NEVER selects.
  - SELECTION lives in the signal phase (bct_score_full, George's 8-condition, score>=7).
    Floor in, rate after — no liquidity/DV logic leaks into selection.
  - POINT-IN-TIME, survivorship-clean: each date's eligible set was built only from bars
    dated <= that date. Delisted names drop after their last bar.

Fail-loud (the #182 lessons):
  - `_universe` is None       -> FAIL LOUD (raise). Never pass-through-all (the 19k
                                 fall-through trap). Absent at runtime = a load/wiring bug.
  - date not in the dict      -> empty set, NO raise (non-trading day / pre-listing /
                                 post-substrate). build_universe emits EVERY substrate
                                 trading date, so a missing date is never a silent gap.
  Whole-artifact-empty fail-loud is at Initialize load time.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine.base import BasePhase, PhaseResult, UniverseLoadError
from engine.context import PhaseContext


class LiquidSubstrate(BasePhase):
    PHASE_KIND = "universe"
    REQUIRES_UPSTREAM: list[str] = []
    PROVIDES_DOWNSTREAM: list[str] = ["ranked_candidates"]

    @dataclass(slots=True)
    class Params:
        min_price: float = 5.0
        min_avg_dollar_volume: float = 5_000_000.0
        adv_window: int = 20
        enabled: bool = True

    def __init__(self, params: "LiquidSubstrate.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        qc = ctx.qc
        date_str = ctx.time.strftime("%Y-%m-%d")
        universe = getattr(qc, "_universe", None)

        if universe is None:
            raise UniverseLoadError(
                f"liquid_substrate: _universe not loaded on {date_str} — refusing to "
                f"trade-everything (load/wiring bug; fix Initialize). Never pass-through-all."
            )

        today_list = universe.get(date_str)
        if today_list is None:
            # Non-trading day / pre-listing / post-substrate. Empty, NO per-day raise
            # (the #182 weekend trap). build emits every trading date → no silent gap.
            ctx.bar_state.ranked_candidates = []
            return PhaseResult(
                decision="empty",
                blocked=False,
                reason=f"no universe entry for {date_str} (non-trading day / out of range)",
                facts={"date": date_str, "count": 0},
                metrics={},
            )

        today_set = set(today_list)
        ctx.bar_state.ranked_candidates = [
            s.value for s in getattr(qc, "_active", set())
            if s.value in today_set
        ]
        return PhaseResult(
            decision="liquid",
            blocked=False,
            reason=f"{len(ctx.bar_state.ranked_candidates)} liquid candidates for {date_str}",
            facts={"date": date_str, "count": len(ctx.bar_state.ranked_candidates)},
            metrics={},
        )

    @property
    def version_marker(self) -> str:
        return "liquid_substrate_v1"
