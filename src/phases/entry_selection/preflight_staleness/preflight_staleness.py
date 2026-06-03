"""Entry-selection sub-role 1: the PRE-FLIGHT STALENESS gate (#276b-1 / #270, GH#25).

Kind: entry_selection · Clock: INTRADAY · Marker: preflight_staleness_v1

The FIRST intraday-execution phase. On T+1's 5-min clock it re-validates each standing daily
candidate against its daily-decision SNAPSHOT ({signal_price, daily_kijun}, captured by the #276b-0
handoff) — DON'T enter a thesis the overnight/open already broke. George's gap discipline as a phase.

ASYMMETRIC gate (HQ ruling, grounded in BCT-6: George's recorded entries have MEAN GAP +5.1% and
~85% trend UP into the event — gap-UPS are the NORM, not staleness). A symmetric "reject any gap > X"
would KILL his bread-and-butter entries. So:
  - ALLOW a gap-UP within a GENEROUS tolerance (`gap_up_tolerance_pct`) — the normal case.
  - INVALIDATE a gap-DOWN (current < signal price — the thesis weakened), an EXCESSIVE gap-up
    (> tolerance — a runaway chase), OR a close BELOW the daily Kijun (structural thesis broken,
    `below_kijun_invalidates`).

This is the STALENESS gate, NOT the entry trigger — confirmation (intraday-Tenkan reclaim + volume)
is the separate `BctIntradayConfirm` phase that runs after this. Pre-flight only kills candidates
whose T+1 state already invalidated the daily thesis.

Reads the #276b-0 snapshot via `qc.snapshot_for_entry(sym)` (H1: a subscribed name with no decided
thesis is NOT enterable → skip-loud; H2: a stale snapshot → DegradedDataError) and the latest
COMPLETED 5-min close (`qc._intraday[sym]["last_close"]`) as the current-price reference (look-ahead
safe — a completed bar, never the forming one). Charter: single code path, no count caps, RAW.

Changelog:
  v1  asymmetric pre-flight staleness gate (allow bounded gap-up, invalidate gap-down / below-Kijun /
      excessive gap-up), reading the 276b-0 daily→intraday snapshot + the maintained intraday close.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine.base import BasePhase, PhaseResult
from engine.symbol_key import canonical_symbol_key
from engine.context import OrderIntent, PhaseContext
from phases.shared.param_space import ComplexityDecl, ParamSpace


def preflight_valid(
    *,
    current_price: float,
    signal_price: float,
    daily_kijun: float,
    gap_up_tolerance_pct: float,
    below_kijun_invalidates: bool,
) -> tuple[bool, str]:
    """PURE asymmetric pre-flight decision (golden-masterable — no QC objects).

    Returns (valid, reason). VALID iff the candidate is a bounded gap-UP above the daily Kijun:
        signal_price <= current_price <= signal_price * (1 + gap_up_tolerance_pct)  AND  above Kijun.
    INVALIDATE (reason): degraded signal_price; below daily Kijun; gap-DOWN; excessive gap-up.
    Asymmetric BY DESIGN — gap-ups within tolerance are George's norm; only the down/below/runaway
    cases break the thesis (BCT-6)."""
    if signal_price <= 0.0:
        return False, "degraded_signal_price"  # no valid reference — cannot validate
    if below_kijun_invalidates and current_price < daily_kijun:
        return False, "below_daily_kijun"       # structural thesis broken
    if current_price < signal_price:
        return False, "gap_down"                # thesis weakened (George enters on gap-UPS, not dips)
    if current_price > signal_price * (1.0 + gap_up_tolerance_pct):
        return False, "excessive_gap_up"        # runaway chase — bounded
    return True, "ok"                            # bounded gap-up, above Kijun


class PreFlightStaleness(BasePhase):
    PHASE_KIND = "entry_selection"
    PHASE_RESOLUTION = "intraday"
    REQUIRES_UPSTREAM = ["signal"]
    PROVIDES_DOWNSTREAM = ["sized_orders"]  # GATES the standing candidate stubs in place

    # ADR D5: one swept axis — the gap-up tolerance ceiling (the asymmetric chase bound). The
    # below_kijun_invalidates rule is a structural invariant (not a swept knob).
    COMPLEXITY = ComplexityDecl(
        free_params=1,
        note="gap_up_tolerance_pct — the asymmetric gap-up chase ceiling (below-Kijun is structural).",
    )

    @dataclass(slots=True)
    class Params:
        gap_up_tolerance_pct: float = 0.10   # GENEROUS (BCT-6 mean gap +5.1%): allow gap-ups to +10%
        below_kijun_invalidates: bool = True  # close below daily Kijun → thesis broken (structural)
        enabled: bool = True

        @classmethod
        def space(cls) -> ParamSpace:
            """Sweepable axis: the gap-up tolerance ceiling (generous — must clear George's +5.1%)."""
            return ParamSpace(axes={"gap_up_tolerance_pct": (0.08, 0.10, 0.15)})

    def __init__(self, params: "PreFlightStaleness.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        qc = ctx.qc
        active_by_key = {canonical_symbol_key(s): s for s in getattr(qc, "_active", set())}  # #276b-1 FIX3
        intraday = getattr(qc, "_intraday", {})
        kept: list[OrderIntent] = []
        invalidated = 0
        reasons: dict[str, int] = {}
        for intent in ctx.bar_state.sized_orders:
            sym = active_by_key.get(canonical_symbol_key(intent.ticker))
            if sym is None:
                invalidated += 1  # candidate not subscribed → not validatable here; H1 territory
                continue
            # H1/H2 (276b-0): the snapshot is the authority. None → not enterable (skip-loud); a
            # stale decision_date → DegradedDataError raised inside snapshot_for_entry.
            snap = qc.snapshot_for_entry(sym)
            if snap is None:
                invalidated += 1
                continue
            st = intraday.get(sym)
            last_close = st.get("last_close") if st else None
            if last_close is None:
                invalidated += 1  # no completed intraday bar yet → cannot validate this tick; defer
                continue
            valid, reason = preflight_valid(
                current_price=float(last_close),
                signal_price=float(snap["signal_price"]),
                daily_kijun=float(snap["daily_kijun"]),
                gap_up_tolerance_pct=self.p.gap_up_tolerance_pct,
                below_kijun_invalidates=self.p.below_kijun_invalidates,
            )
            if valid:
                kept.append(intent)
                ctx.record_funnel("preflight_pass", sym)  # #276b-1 funnel stage 3 (observe-only)
            else:
                invalidated += 1
                reasons[reason] = reasons.get(reason, 0) + 1
        ctx.bar_state.sized_orders = kept
        return PhaseResult(
            decision=kept,
            blocked=False,  # entry_selection gates candidates, never blocks the bar
            reason=f"pre-flight: kept {len(kept)}, invalidated {invalidated} {reasons}",
            facts={"kept": len(kept), "invalidated": invalidated, **{f"reason_{k}": v for k, v in reasons.items()}},
            metrics={},
        )

    @property
    def version_marker(self) -> str:
        return "preflight_staleness_v1"
