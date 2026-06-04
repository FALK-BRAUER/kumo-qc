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
from typing import Any, ClassVar

from engine.base import BasePhase, DegradedDataError, PhaseResult
from engine.symbol_key import canonical_symbol_key
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
        # #340: the entry-seam cap runs in the entry-execution chain → its clock MUST match the chain
        # (the engine's mixed-clocks ConfigError). S1's entry is intraday (sizing resolution="intraday"),
        # so a config with an intraday entry wires resolution="intraday". STRUCTURAL (clock-routing),
        # NOT a behavioral axis → excluded from the config hash. Default "daily" = backward-compatible.
        resolution: str = "daily"
        _HASH_EXCLUDE: ClassVar[frozenset[str]] = frozenset({"resolution"})

        @classmethod
        def space(cls) -> ParamSpace:
            """Sweepable axis: the gross-exposure ceiling fraction."""
            return ParamSpace(axes={"max_gross_pct": (0.8, 1.0, 1.2)})

    def __init__(self, params: "GrossExposureCap.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params
        self.PHASE_RESOLUTION = params.resolution  # clock-route the entry-seam cap (#340)

    def _held_gross(self, qc: Any) -> float:
        """Currently-held gross exposure (abs holdings value — long+short both consume the cap).

        FAIL-LOUD (#181/#261): read the attr DIRECTLY — never getattr-default to 0.0. A silent 0.0
        (absent/renamed attr on the live QC object) would measure new exposure against ZERO held →
        permit max_gross_pct×equity ON TOP of existing holdings = uncapped over-leverage (the Pe
        cloud −0.055 class this safety floor exists to prevent). A degraded read CRASHES, never
        masks the ceiling."""
        if not hasattr(qc.portfolio, "total_holdings_value"):
            raise DegradedDataError(
                "qc.portfolio has no 'total_holdings_value' — the gross-exposure cap cannot "
                "measure held exposure and MUST NOT silently default to 0.0 (that would permit "
                f"max_gross_pct={self.p.max_gross_pct}×equity on top of existing holdings → "
                "over-leverage, the Pe −0.055 class, #181). Fix the QC attribute, never mask it."
            )
        return abs(float(qc.portfolio.total_holdings_value))

    def _bound(
        self, qc: Any, intents: list[OrderIntent], baseline_committed: float
    ) -> tuple[list[OrderIntent], int, float, float]:
        """SINGLE-SOURCE cap math (#181) — shared by the entry seam (evaluate) and the FIRE_ADDS
        seam (bound_adds), so the gross ceiling is enforced by ONE implementation, never duplicated
        (HQ constraint). Keeps each intent whose value fits under `max_gross_pct`×equity given the
        running committed total (starting from `baseline_committed`); drops (does not trim) the rest
        — a partial fill is a different position than the sizer intended; the safety floor refuses
        the over-cap order outright. Returns (kept, dropped, committed, ceiling)."""
        equity = float(qc.portfolio.total_portfolio_value)
        ceiling = equity * self.p.max_gross_pct
        active_by_key = {canonical_symbol_key(s): s for s in getattr(qc, "_active", set())}  # #276b-1 FIX3
        kept: list[OrderIntent] = []
        committed = baseline_committed
        dropped = 0
        for intent in intents:
            sym = active_by_key.get(canonical_symbol_key(intent.ticker))
            if sym is None:
                continue
            try:
                price = float(qc.securities[sym].price)
            except (KeyError, AttributeError, TypeError, ValueError) as exc:
                # a price lookup failure is degraded input — drop (safe direction: do NOT fire an
                # un-priceable order) but NEVER silently; log so it's diagnosable (#261 anti-mirage).
                log = getattr(qc, "log", None)
                if callable(log):
                    log(f"GROSS_CAP|price-lookup failed for {intent.ticker!r}: {exc!r} — order dropped")
                continue
            order_value = abs(intent.qty) * price
            if committed + order_value > ceiling:
                dropped += 1
                continue
            committed += order_value
            kept.append(intent)
        return kept, dropped, committed, ceiling

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        """Entry seam: cap new ENTRIES (sized_orders) against currently-held gross. Runs after
        sizing, before FIRE_ENTRIES."""
        qc = ctx.qc
        kept, dropped, committed, ceiling = self._bound(
            qc, ctx.bar_state.sized_orders, self._held_gross(qc)
        )
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

    def bound_adds(self, ctx: PhaseContext, in_flight_entry_value: float) -> None:
        """FIRE_ADDS seam (#181 BUG-2 Stage 0): cap pyramid ADDS commit-aware, reusing the SAME
        `_bound` math (single-source). The leverage hole this closes: `adds` run AFTER FIRE_ENTRIES
        and emit `add_intents` that previously fired with NO gross check → unbounded on margin.

        COMMIT-AWARE held (the real-money trap): held = live holdings value + the value of THIS
        TICK's already-submitted entry orders (`in_flight_entry_value`). We do NOT trust raw
        total_holdings_value to reflect same-tick FIRE_ENTRIES fills — LEAN fill lag can leave it
        un-updated → undercount → the add overshoots the cap. Counting this tick's entries is the
        conservative, safe direction (if a fill DID land it is double-counted → stricter, never
        looser). Entries fire first; adds are bounded to the REMAINING budget (an interim
        new-first allocation — merit-ranked add-vs-new is the Stage-2 follow-on, #181, gated on
        Stage-1 measurement). No-op when the cap is disabled."""
        if not self.p.enabled:
            return
        qc = ctx.qc
        baseline = self._held_gross(qc) + float(in_flight_entry_value)
        kept, dropped, committed, ceiling = self._bound(qc, ctx.bar_state.add_intents, baseline)
        ctx.bar_state.add_intents = kept
        if dropped:
            log = getattr(qc, "log", None)
            if callable(log):
                log(
                    f"GROSS_CAP_ADDS|dropped={dropped} add(s) over ceiling "
                    f"(committed ${committed:,.0f} / ceiling ${ceiling:,.0f}, "
                    f"in-flight entries ${in_flight_entry_value:,.0f}) #181"
                )

    @property
    def version_marker(self) -> str:
        return "gross_exposure_cap_v1"
