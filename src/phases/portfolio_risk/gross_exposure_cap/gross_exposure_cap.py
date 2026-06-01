"""Portfolio-risk phase: hard GROSS-EXPOSURE cap (#181 / #270 essential).

Kind: portfolio_risk
Marker: gross_exposure_cap_v1
Tested params: max_gross_pct=1.0 (100% — fully invested, no leverage; the SAFETY ceiling).

The SAFETY function (#181): a hard ceiling on total gross exposure so a bug / over-eager sizing
can NOT over-leverage the account (the Pe cloud −0.055 lesson: implicit exposure exploded to
1.44x → a % gross cap is the floor that prevents it). This phase runs AFTER sizing, BEFORE
FIRE_ENTRIES: it TRIMS/DROPS new entries whose combined value would push gross exposure (held +
already-committed-this-bar + the candidate) above `max_gross_pct` × equity. It NEVER blocks the
bar (returns blocked=False) — it bounds what FIRES, not what's decided.

Charter: this is a %-RULE gross cap, NOT a position COUNT cap (the forbidden kind). It bounds
$-exposure as a fraction of equity — the legitimate exposure governor the charter requires
(adds-without-gross-cap → CharterViolation, validate_invariants). PARAMETERIZED (max_gross_pct),
never a hardcoded magic number.

#302 hook: max_gross_pct is a SETTABLE threshold. A future multi-timeframe regime hierarchy (#302)
can MODULATE it (bull→full, bear→reduced) by setting this value per-regime — the cap MECHANISM
here is the safety floor; #302 layers dynamic adjustment on top WITHOUT touching this phase's
enforcement. First cut = a fixed hard ceiling; the regime-driver comes later.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine.base import BasePhase, PhaseResult
from engine.context import OrderIntent, PhaseContext
from phases.shared.param_space import ComplexityDecl, ParamSpace


class GrossExposureCap(BasePhase):
    PHASE_KIND = "portfolio_risk"
    REQUIRES_UPSTREAM = ["sizing"]
    PROVIDES_DOWNSTREAM = ["sized_orders"]

    # ADR D5: one swept axis — the cap fraction (the safety ceiling, tunable per the no-hardcoded rule).
    COMPLEXITY = ComplexityDecl(
        free_params=1,
        note="max_gross_pct — the hard gross-exposure ceiling (safety floor; #302 may modulate).",
    )

    @dataclass(slots=True)
    class Params:
        max_gross_pct: float = 1.0  # 100% = fully invested, no leverage (the default safety ceiling)
        enabled: bool = True

        @classmethod
        def space(cls) -> ParamSpace:
            """Sweepable axis: the gross-exposure ceiling fraction."""
            return ParamSpace(axes={"max_gross_pct": (0.8, 1.0, 1.2)})

    def __init__(self, params: "GrossExposureCap.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        qc = ctx.qc
        equity = float(qc.portfolio.total_portfolio_value)
        # the hard ceiling in $ — equity × the parameterized cap fraction.
        ceiling = equity * self.p.max_gross_pct
        # currently-held gross exposure (abs holdings value — long+short both consume the cap).
        held_gross = abs(float(getattr(qc.portfolio, "total_holdings_value", 0.0)))

        active_by_value = {s.value: s for s in getattr(qc, "_active", set())}
        kept: list[OrderIntent] = []
        committed = held_gross
        dropped = 0
        for intent in ctx.bar_state.sized_orders:
            sym = active_by_value.get(intent.ticker)
            if sym is None:
                continue
            try:
                price = float(qc.securities[sym].price)
            except Exception:
                continue
            order_value = abs(intent.qty) * price
            # HARD enforce: drop the entry if it would breach the gross ceiling. (Drop, not trim —
            # a partial fill below the sizer's quantity is a different position than intended; the
            # safety floor refuses the over-cap order outright. A trimming variant is a later impl.)
            if committed + order_value > ceiling:
                dropped += 1
                continue
            committed += order_value
            kept.append(intent)

        ctx.bar_state.sized_orders = kept
        return PhaseResult(
            decision=kept,
            blocked=False,  # bounds what FIRES, never blocks the bar
            reason=(
                f"gross-cap {self.p.max_gross_pct:.2f}×equity: kept {len(kept)}, dropped {dropped} "
                f"(committed ${committed:,.0f} / ceiling ${ceiling:,.0f})"
            ),
            facts={
                "kept": len(kept), "dropped": dropped,
                "committed_gross": committed, "ceiling": ceiling,
                "max_gross_pct": self.p.max_gross_pct,
            },
            metrics={},
        )

    @property
    def version_marker(self) -> str:
        return "gross_exposure_cap_v1"
