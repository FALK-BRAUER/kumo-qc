"""Filter phase: tradeability FLOORS (#233 / #238) — eligibility gate, runs BEFORE universe.

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

MODEL (#238 live-coarse integration — the floors are APPLIED LIVE, this phase REPORTS):
  - The tradeability floors (min_price, min_avg_dollar_volume) are now applied LIVE inside
    runtime.universe_select.select_live_universe (run once-daily by lean_entry._coarse_
    selection). Every ticker the live selection keeps has ALREADY cleared the floors. There
    is no longer a precomputed `qc._eligible` artifact (the stored-file mechanism the #238
    work retired — the 326 scar).
  - This phase therefore EMITS the live-selected eligible set: qc._ranked_today ∩ qc._active
    (the names that passed the floors AND are truly subscribed). The Params remain as the
    PROVENANCE of the floor values applied live (fingerprint/config-hash); the floor MATH
    moved to select_live_universe, mirrored by these params (they MUST stay in sync — the
    lean_entry MIN_PRICE / MIN_AVG_DOLLAR_VOLUME / ADV_WINDOW wire the same numbers).
  - Keeps the filter→universe seam (filter emits the eligible set; universe ranks+caps),
    preserving REQUIRED_PHASES("filter") and the engine's phase ordering. NOT the entry-side
    `eligibility` phase kind (which gates positions after sizing).
  - POINT-IN-TIME, survivorship-clean by construction (the live coarse feed is the day's
    tradeable set; delisted names simply never appear in the coarse feed for that day).

Fail-loud (the #182 lessons):
  - `_ranked_today` is None -> FAIL LOUD (raise). Never pass-through-all (the 19k
                              fall-through trap). Absent at runtime = a live-selection wiring
                              bug (lean_entry must always assign it, [] on a zero day).
  - empty ranked list      -> empty eligible, NO raise (zero-candidate / pre-warmup day).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from base import BasePhase, PhaseResult, UniverseLoadError
from context import PhaseContext


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
        ranked_today = getattr(qc, "_ranked_today", None)

        if ranked_today is None:
            raise UniverseLoadError(
                f"tradeability_floors: _ranked_today not set on {date_str} — refusing to "
                f"trade-everything (live selection wiring bug; fix lean_entry._coarse_"
                f"selection). Never pass-through-all."
            )

        if not ranked_today:
            # Zero-candidate day / pre-warmup (the live selection assigns [] not None).
            ctx.bar_state.eligible = []
            return PhaseResult(
                decision="empty",
                blocked=False,
                reason=f"no eligible (live) for {date_str}",
                facts={"date": date_str, "count": 0},
                metrics={},
            )

        # The live-selected set already cleared the floors (applied in select_live_universe).
        # Emit it ∩ the truly-subscribed active set, sorted for a deterministic, order-stable
        # `eligible` list (rank is the universe phase's job).
        # CASE: ranked tickers lowercase, QC Symbol.value uppercase — match case-insensitively
        # and emit the canonical _active value (consistent with the universe phase + signal).
        active_by_lower = {s.value.lower(): s.value for s in getattr(qc, "_active", set())}
        ctx.bar_state.eligible = sorted(
            active_by_lower[t.lower()] for t in ranked_today if t.lower() in active_by_lower
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
