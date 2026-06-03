from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from base import BasePhase, PhaseResult
from context import PhaseContext
from symbol_key import canonical_symbol_key
from shared_param_space import ComplexityDecl, ParamSpace


def cloud_floor(*, entry_price: float, cloud_bottom: float) -> tuple[bool, str]:
    if cloud_bottom <= 0.0:
        return False, "degraded_cloud"
    if entry_price <= 0.0:
        return False, "degraded_entry"
    if cloud_bottom >= entry_price:
        return False, "floor_at_or_above_entry"
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
