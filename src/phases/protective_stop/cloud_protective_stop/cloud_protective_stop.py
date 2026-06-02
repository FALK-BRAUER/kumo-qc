"""Protective-stop phase: the CLOUD-BOTTOM catastrophic floor (#339 — the real Q1/Q4 lever).

Kind: protective_stop · Clock: INTRADAY · Marker: cloud_protective_stop_v1

A DIFFERENT impl of the protective_stop kind (ADR D1 — floor VARIANTS are different impls, the
sweep axis), swapping the structural floor from the daily KIJUN (KijunProtectiveStop, #290) to the
daily CLOUD BOTTOM (min Senkou A/B). RATIONALE (#339 finding): the champion's BINDING exit is the
protective GTC stop_market — stamped at the KIJUN, it force-exits recoverable Kijun-dips (BCT-3: those
recover ~75% while still ABOVE the cloud), the WORST BCT-3 exit (24% win). Moving the floor to the
cloud bottom lets those dips RIDE and exits only on a true structural break (price below the cloud) —
this is the G3-winning CloudBottomStop (the lone positive of 20+ stop experiments, 1.079 Sharpe,
#254 stops ★★). The daily exit_hard phase is inert behind this stop, so the STOP is the lever.

Same contract as KijunProtectiveStop: stamps `intent.protective_stop` on the FINAL surviving sized
entries pre-FIRE; FIRE_ENTRIES places the resting broker-side GTC stop_market alongside the entry.
DEGENERATE GUARD: a long's floor MUST sit BELOW the entry — if cloud_bottom >= entry the floor is an
immediate stop-out → DECLINE the entry (loud), never place it. Cloud bottom sits BELOW the Kijun in an
uptrend, so this floor is WIDER (looser) than the Kijun floor — declines should be rarer, never more.

Floor source: the 276b-0 decision-day snapshot `daily_cloud_bottom` (min Senkou A/B at decision T,
the same staleness-guarded snapshot the Kijun floor reads — no look-ahead).
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from engine.base import BasePhase, PhaseResult
from engine.context import PhaseContext
from engine.symbol_key import canonical_symbol_key
from phases.shared.param_space import ComplexityDecl, ParamSpace


def cloud_floor(*, entry_price: float, cloud_bottom: float) -> tuple[bool, str]:
    """PURE floor decision (golden-masterable). Returns (ok, reason); when ok the floor IS
    `cloud_bottom`. The cloud bottom is the structural catastrophic floor and MUST sit BELOW the
    entry — a long floor at/above entry is an immediate stop-out (reject, not silent)."""
    if cloud_bottom <= 0.0:
        return False, "degraded_cloud"            # no valid structural reference
    if entry_price <= 0.0:
        return False, "degraded_entry"
    if cloud_bottom >= entry_price:
        return False, "floor_at_or_above_entry"   # would stop out immediately — decline the entry
    return True, "ok"


class CloudProtectiveStop(BasePhase):
    PHASE_KIND = "protective_stop"
    PHASE_RESOLUTION = "intraday"
    REQUIRES_UPSTREAM = ["sizing"]
    PROVIDES_DOWNSTREAM = ["sized_orders"]

    COMPLEXITY = ComplexityDecl(free_params=0, note="daily cloud-bottom structural floor; no swept axes.")

    @dataclass(slots=True)
    class Params:
        enabled: bool = True

        @classmethod
        def space(cls) -> ParamSpace:
            return ParamSpace(axes={})

    def __init__(self, params: "CloudProtectiveStop.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        qc = ctx.qc
        active_by_key = {canonical_symbol_key(s): s for s in getattr(qc, "_active", set())}
        kept: list[Any] = []
        stamped = 0
        declined = 0
        reasons: dict[str, int] = {}
        for intent in ctx.bar_state.sized_orders:
            sym = active_by_key.get(canonical_symbol_key(intent.ticker))
            if sym is None:
                declined += 1
                reasons["not_active"] = reasons.get("not_active", 0) + 1
                continue
            snap = qc.snapshot_for_entry(sym)
            if snap is None:
                declined += 1
                reasons["no_snapshot"] = reasons.get("no_snapshot", 0) + 1
                continue
            # defensive: a snapshot from before the daily_cloud_bottom field landed (deploy-order /
            # stale-branch hazard) → decline this entry (no floor placeable), never KeyError-crash.
            cb = snap.get("daily_cloud_bottom")
            if cb is None:
                declined += 1
                reasons["cloud_bottom_missing"] = reasons.get("cloud_bottom_missing", 0) + 1
                continue
            cloud_bottom = float(cb)
            entry_price = float(intent.price)
            ok, reason = cloud_floor(entry_price=entry_price, cloud_bottom=cloud_bottom)
            if not ok:
                declined += 1
                reasons[reason] = reasons.get(reason, 0) + 1
                log = getattr(qc, "log", None)
                if callable(log):
                    log(
                        f"PROTECTIVE_FLOOR_DECLINE|{ctx.time.date()}|{intent.ticker}|{reason}|"
                        f"cloud_bottom={cloud_bottom:.2f}|entry={entry_price:.2f} (no immediate-stop-out floor #339)"
                    )
                continue
            kept.append(replace(intent, protective_stop=cloud_bottom))
            stamped += 1
        ctx.bar_state.sized_orders = kept
        return PhaseResult(
            decision=kept,
            blocked=False,
            reason=f"cloud protective floor: stamped {stamped}, declined {declined} {reasons}",
            facts={"stamped": stamped, "declined": declined,
                   **{f"reason_{k}": v for k, v in reasons.items()}},
            metrics={},
        )

    @property
    def version_marker(self) -> str:
        return "cloud_protective_stop_v1"
