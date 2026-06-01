"""Protective-stop phase: the daily-Kijun CATASTROPHIC FLOOR (#276b-1 / #290, GH#25).

Kind: protective_stop · Clock: INTRADAY · Marker: kijun_protective_stop_v1

The pre-FIRE phase that stamps `intent.protective_stop` on the FINAL surviving sized entries (runs
after sizing + portfolio_risk + cash, right before FIRE_ENTRIES). FIRE_ENTRIES then places a resting
broker-side GTC stop_market(sym, -qty, protective_stop) ALONGSIDE the entry and TICKET-tracks it, so
the #276a cancel-replace + GUARD-3 lifecycle manage it. This is the #290 CATASTROPHIC FLOOR — a
broker-side stop that fires intrabar on a gap/halt/outage even when the runtime kijun_g3 exit
doesn't — DISTINCT from the runtime exit (exit_hard).

WHY a dedicated pre-FIRE KIND (not entry_timing/sizing): single-responsibility (order_type and qty
are other kinds' jobs) + sweepability — Epic-2 will toggle floor VARIANTS (daily-Kijun vs ATR-mult
vs swing-low) as a clean sweep axis. This impl is the daily-Kijun structural floor: WIDER/structural
than the intraday Tenkan or a swing-low (HQ ruling), sourced from the 276b-0 daily-decision snapshot.

FLOOR = the snapshot's daily Kijun (`qc.snapshot_for_entry(sym)["daily_kijun"]` — H2-staleness-
guarded, decision-day T = the correct structural reference at the T+1 intraday fire, not look-ahead).
DEGENERATE GUARD: a long's floor MUST be BELOW the entry; if daily_kijun >= entry price the floor
would stop the position out immediately — DECLINE the entry (drop it, LOUD log), never place an
immediate-stop-out floor (the silent-bad-trade case for this phase).

Charter: single code path, RAW, no count caps. Completed-bar / decision-day snapshot only.

Changelog:
  v1  daily-Kijun structural catastrophic floor stamped pre-FIRE on the surviving sized entries,
      with the degenerate kijun>=entry loud-decline guard.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from base import BasePhase, PhaseResult
from context import PhaseContext
from shared_param_space import ComplexityDecl, ParamSpace


def protective_floor(*, entry_price: float, daily_kijun: float) -> tuple[bool, str]:
    """PURE floor decision (golden-masterable — no QC objects). Returns (ok, reason); when ok the
    floor level IS `daily_kijun`. The daily Kijun is the structural catastrophic floor and MUST sit
    BELOW the entry — a long floor at/above entry is an immediate stop-out (reject, not silent)."""
    if daily_kijun <= 0.0:
        return False, "degraded_kijun"            # no valid structural reference
    if entry_price <= 0.0:
        return False, "degraded_entry"            # no valid entry reference
    if daily_kijun >= entry_price:
        return False, "floor_at_or_above_entry"   # would stop out immediately — decline the entry
    return True, "ok"


class KijunProtectiveStop(BasePhase):
    PHASE_KIND = "protective_stop"
    PHASE_RESOLUTION = "intraday"
    REQUIRES_UPSTREAM = ["sizing"]            # operates on the FINAL sized intents (post-sizing)
    PROVIDES_DOWNSTREAM = ["sized_orders"]    # stamps protective_stop in place (+ drops degenerate)

    # The level IS the daily Kijun — no sweepable knob here. Floor VARIANTS (ATR-mult, swing-low)
    # are DIFFERENT impls of this kind (ADR D1), the Epic-2 sweep axis — never a flag-branch here.
    COMPLEXITY = ComplexityDecl(free_params=0, note="daily-Kijun structural floor; no swept axes.")

    @dataclass(slots=True)
    class Params:
        enabled: bool = True

        @classmethod
        def space(cls) -> ParamSpace:
            return ParamSpace(axes={})

    def __init__(self, params: "KijunProtectiveStop.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        qc = ctx.qc
        active_by_lower = {s.value.lower(): s for s in getattr(qc, "_active", set())}
        kept: list[Any] = []
        stamped = 0
        declined = 0
        reasons: dict[str, int] = {}
        for intent in ctx.bar_state.sized_orders:
            sym = active_by_lower.get(intent.ticker.lower())
            if sym is None:
                declined += 1
                reasons["not_active"] = reasons.get("not_active", 0) + 1
                continue
            # H1/H2 (276b-0): snapshot is the thesis authority. None → not enterable (skip-loud);
            # a stale decision_date → DegradedDataError raised inside snapshot_for_entry (propagate).
            snap = qc.snapshot_for_entry(sym)
            if snap is None:
                declined += 1
                reasons["no_snapshot"] = reasons.get("no_snapshot", 0) + 1
                continue
            daily_kijun = float(snap["daily_kijun"])
            entry_price = float(intent.price)  # sizing's entry reference price
            ok, reason = protective_floor(entry_price=entry_price, daily_kijun=daily_kijun)
            if not ok:
                declined += 1
                reasons[reason] = reasons.get(reason, 0) + 1
                log = getattr(qc, "log", None)
                if callable(log):
                    log(
                        f"PROTECTIVE_FLOOR_DECLINE|{ctx.time.date()}|{intent.ticker}|{reason}|"
                        f"kijun={daily_kijun:.2f}|entry={entry_price:.2f} (no immediate-stop-out floor #290)"
                    )
                continue  # DECLINE the entry — never fire an immediate-stop-out
            kept.append(replace(intent, protective_stop=daily_kijun))
            stamped += 1
        ctx.bar_state.sized_orders = kept
        return PhaseResult(
            decision=kept,
            blocked=False,
            reason=f"protective floor: stamped {stamped}, declined {declined} {reasons}",
            facts={"stamped": stamped, "declined": declined,
                   **{f"reason_{k}": v for k, v in reasons.items()}},
            metrics={},
        )

    @property
    def version_marker(self) -> str:
        return "kijun_protective_stop_v1"
