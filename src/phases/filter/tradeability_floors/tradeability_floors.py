"""Filter phase: tradeability FLOORS (#233) — eligibility gate, runs BEFORE the universe.

Kind:    filter
Marker:  tradeability_floors_v1
Params:  min_price=10.0, min_avg_dollar_volume=100_000_000, adv_window=20, enabled=True

LIQUIDITY THRESHOLD — min_avg_dollar_volume=100M (fintrack ruling, data-informed):
  The FY2025 breadth curve (median eligible/day): 5M→3237, 10M→2691, 25M→1970, 50M→1430,
  100M→943, 200M→549. 5M was too low (pulled ~2700 marginal names George wouldn't trade,
  and OOM'd the local container). 100M = genuinely liquid large/mid caps (~943/day) — a
  principled LIQUIDITY threshold (not a count cap), a wide-enough liquid net for the score>=7
  signal to filter (trade count → DSR/PBO robustness), and ~3x the local compute margin vs
  2700. Picked on principle, NOT to match the champion (v2 is the corrected pipeline, not a
  clone). If LOCAL infra OOMs at 943, that is a local-RAM limit — validate on cloud or use a
  temp HIGHER local-only floor; do NOT lower the strategy floor to fit local RAM.
         (mirror scripts/build_filter.py — the phase CONSUMES the precomputed
          date->eligible artifact; the floor math lives in the precompute. Params carried
          for provenance/fingerprint.)

MODEL (#233, Falk — filter is its OWN phase with its OWN params):
  - Pure eligibility gate: a name is tradeable on date D iff its latest close >= min_price
    AND its trailing-adv_window mean dollar-volume >= min_avg_dollar_volume. No rank, no
    cap, no Ichimoku — those are downstream (universe ranks+caps; signal scores+selects).
  - Emits `bar_state.eligible` (the eligible set ∩ active). The universe phase reads its
    OWN ranked artifact (built FROM this filter's artifact offline) and emits
    `ranked_candidates` — the seam is two artifacts, true separation (faster #182-class
    divergence root-causing: diff the eligible-set fingerprint first, then the ranked one).
  - NOT the existing entry-side `eligibility` phase kind (which gates positions after
    sizing) — this is the pre-universe tradeability filter.
  - POINT-IN-TIME, survivorship-clean: each date's eligible set was built only from bars
    dated <= that date. Delisted names drop after their last bar.

Fail-loud (the #182 lessons):
  - `_eligible` is None  -> FAIL LOUD (raise). Never pass-through-all (the 19k
                            fall-through trap). Absent at runtime = a load/wiring bug.
  - date not in the dict -> empty, NO raise (non-trading day / pre-listing / post-
                            substrate). build_filter emits EVERY substrate trading date,
                            so a missing date is never a silent gap.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from engine.base import BasePhase, PhaseResult, UniverseLoadError
from engine.context import PhaseContext


class TradeabilityFloors(BasePhase):
    PHASE_KIND = "filter"
    REQUIRES_UPSTREAM: list[str] = []
    PROVIDES_DOWNSTREAM: list[str] = ["eligible"]

    @dataclass(slots=True)
    class Params:
        min_price: float = 10.0
        min_avg_dollar_volume: float = 100_000_000.0  # liquidity threshold (see header)
        adv_window: int = 20
        enabled: bool = True

    def __init__(self, params: "TradeabilityFloors.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        qc = ctx.qc
        date_str = ctx.time.strftime("%Y-%m-%d")
        eligible = getattr(qc, "_eligible", None)

        if eligible is None:
            raise UniverseLoadError(
                f"tradeability_floors: _eligible not loaded on {date_str} — refusing to "
                f"trade-everything (load/wiring bug; fix Initialize). Never pass-through-all."
            )

        today = eligible.get(date_str)
        if today is None:
            # Non-trading day / pre-listing / post-substrate. Empty, NO per-day raise
            # (the #182 weekend trap). build_filter emits every trading date → no silent gap.
            ctx.bar_state.eligible = []
            return PhaseResult(
                decision="empty",
                blocked=False,
                reason=f"no eligible entry for {date_str} (non-trading day / out of range)",
                facts={"date": date_str, "count": 0},
                metrics={},
            )

        # `today` is the filter artifact's per-date value: {ticker: dv} (dict) — its keys
        # are the eligible names. Accept any iterable of tickers (dict or list). The
        # eligible set has NO rank here (rank is the universe phase's job); sort for a
        # deterministic, order-stable `eligible` list.
        members: Iterable[str] = today.keys() if isinstance(today, dict) else today
        # CASE: artifact tickers lowercase, QC Symbol.value uppercase — match case-insensitively
        # and emit the canonical _active value (consistent with the universe phase + signal).
        active_by_lower = {s.value.lower(): s.value for s in getattr(qc, "_active", set())}
        ctx.bar_state.eligible = sorted(
            active_by_lower[t.lower()] for t in members if t.lower() in active_by_lower
        )
        return PhaseResult(
            decision="eligible",
            blocked=False,
            reason=f"{len(ctx.bar_state.eligible)} eligible for {date_str}",
            facts={"date": date_str, "count": len(ctx.bar_state.eligible)},
            metrics={},
        )

    @property
    def version_marker(self) -> str:
        return "tradeability_floors_v1"
