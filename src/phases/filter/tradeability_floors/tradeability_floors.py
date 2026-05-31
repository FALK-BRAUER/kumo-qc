"""Filter phase: tradeability FLOORS (#233 / #238 / R1) — eligibility gate, runs FIRST.

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

MODEL (#238 / R1 UN-FUSE — the floors are APPLIED HERE, this is the REAL first filter):
  - The SHARED UPSTREAM (runtime.lean_entry._coarse_selection, once-daily) builds
    `qc._bar_metrics = {ticker_lower: (close, trailing_dv)}` — prefilter survivors with RAW
    trailing metrics, NO floors/rank/cap. R1 (Falk): the filter and the rank are now DISTINCT
    phases, filter FIRST. This phase APPLIES the PRECISE floors via apply_floors
    (close >= min_price AND trailing_dv >= min_avg_dollar_volume) — no longer a re-expose of
    a precomputed `_ranked_today` (that was the FUSED no-op; un-fused per R1).
  - `min_price` + `min_avg_dollar_volume` are FUNCTIONAL (they drive the floor). `adv_window`
    is the PROVENANCE of the upstream trailing window — the trailing mean is computed in
    runtime.lean_entry.build_bar_metrics; this mirrors lean_entry.ADV_WINDOW (they MUST stay
    in sync; this phase does not recompute the window, it documents it).
  - Emits `bar_state.eligible` = the floored tickers ∩ the truly-subscribed active set
    (case-insensitive), as the canonical uppercase Symbol.value, sorted for determinism.
    Rank + cap is the RANK phase's job (dv_rank_cap, downstream).
  - Keeps the filter→universe→signal seam (filter emits eligible; rank ranks+caps), preserving
    REQUIRED_PHASES("filter") and the engine's phase ordering. NOT the entry-side `eligibility`
    phase kind (which gates positions after sizing).
  - POINT-IN-TIME, survivorship-clean by construction (the live coarse feed is the day's
    tradeable set; delisted names simply never appear in the coarse feed for that day).

Fail-loud (the #182 lessons):
  - `_bar_metrics` is None -> FAIL LOUD (raise). Never pass-through-all (the 19k fall-through
                             trap). Absent at runtime = a shared-upstream wiring bug
                             (lean_entry._coarse_selection must always assign it, {} on a zero
                             day). The wiring guard lives HERE now (the first consumer of the
                             upstream metrics).
  - empty `{}` metrics     -> empty eligible, NO raise (zero-candidate / pre-warmup day).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine.base import BasePhase, PhaseResult, UniverseLoadError
from engine.context import PhaseContext
from runtime.universe_select import apply_floors


class TradeabilityFloors(BasePhase):
    PHASE_KIND = "filter"
    REQUIRES_UPSTREAM: list[str] = []
    PROVIDES_DOWNSTREAM: list[str] = ["eligible"]

    @dataclass(slots=True)
    class Params:
        min_price: float = 10.0
        min_avg_dollar_volume: float = 100_000_000.0  # liquidity threshold (see header)
        adv_window: int = 20  # PROVENANCE of the upstream trailing window (lean_entry.ADV_WINDOW)
        enabled: bool = True

    def __init__(self, params: "TradeabilityFloors.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        qc = ctx.qc
        date_str = ctx.time.strftime("%Y-%m-%d")
        bar_metrics = getattr(qc, "_bar_metrics", None)

        if bar_metrics is None:
            raise UniverseLoadError(
                f"tradeability_floors: _bar_metrics not set on {date_str} — refusing to "
                f"trade-everything (shared-upstream wiring bug; fix lean_entry._coarse_"
                f"selection). Never pass-through-all."
            )

        if not bar_metrics:
            # Zero-candidate day / pre-warmup (the shared upstream assigns {} not None).
            ctx.bar_state.eligible = []
            return PhaseResult(
                decision="empty",
                blocked=False,
                reason=f"no eligible (live) for {date_str}",
                facts={"date": date_str, "count": 0},
                metrics={},
            )

        # APPLY THE FLOORS (R1: this is the real filter, run FIRST). floored = lowercase
        # tickers clearing close>=min_price AND trailing_dv>=min_avg_dollar_volume, sorted.
        floored = apply_floors(
            bar_metrics,
            min_price=self.p.min_price,
            min_avg_dollar_volume=self.p.min_avg_dollar_volume,
        )

        # Intersect with the truly-subscribed active set (case-insensitive), emit the canonical
        # uppercase Symbol.value, sorted. Rank is the RANK phase's job (dv_rank_cap).
        active_by_lower = {s.value.lower(): s.value for s in getattr(qc, "_active", set())}
        ctx.bar_state.eligible = sorted(
            active_by_lower[t] for t in floored if t in active_by_lower
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
