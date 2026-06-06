"""Profit phase: GainScaleOut — partial scale-out at GAIN MILESTONES, on ALL positions (the inverse of
PgProfitTake, which exempted proved monsters and trimmed only never-proved faders).

Kind: profit · Clock: DAILY (co-clocked with exit_hard — the #379 over-sell invariant) · Marker:
gain_scale_out_v1.

THE DATA (S1 FY2025): the monsters give back HALF their peak to the cloud-bottom trail — QBTS +150%→+43%
(gave back 107pts), PAAS +96→+32 (63), RBLX +148→+72 (76), HOOD +274→+198 (77); ~30 PORTFOLIO points
peak-to-floor = the +42.8% M2M vs +21.13% floor gap. AND 15/19 closed losers PROVED (VST +28, BJ +26,
META +18) before collapsing to a loss. BOTH monsters and proved-then-died losers give back from a peak.

THE LEVER: trim `trim_frac` of the CURRENT size each time a position's gain crosses a milestone
(+50/+100/+150% by default), ONCE per milestone, for EVERY invested position. Banks the QBTS/PAAS
blow-offs + the VST/BJ proved-then-died peaks, while the remaining 67-75% rides the cloud-bottom trail
through the gap-recovery (so it does NOT trip the dip-clip failure that killed full-exit/tight-trail
levers — it trims at STRENGTH, not on a dip). PARTIAL only — never a full exit (that's exit_hard's job;
the engine refuses a full trim, #379 Part A, and resizes the protective stop DOWN on each trim).

Gain is measured on CLOSE (you can only sell at an observed close, not a retroactive intraday high).
State on qc._scaleout_state: {entry_date, fired: set(milestones already trimmed)}; reset on re-entry,
GC on close.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from engine.base import BasePhase, PhaseResult
from engine.context import OrderIntent, PhaseContext
from phases.shared.param_space import ComplexityDecl, ParamSpace


def _state(qc: Any) -> dict:
    st = getattr(qc, "_scaleout_state", None)
    if st is None:
        st = {}
        qc._scaleout_state = st
    return st


class GainScaleOut(BasePhase):
    PHASE_KIND = "profit"
    PHASE_RESOLUTION = "daily"          # MUST co-clock with exit_hard (the #379 over-sell invariant)
    REQUIRES_UPSTREAM: list[str] = []
    PROVIDES_DOWNSTREAM = ["trim_intents"]

    COMPLEXITY = ComplexityDecl(free_params=2, note="trim_frac + milestones (the scale-out schedule).")

    @dataclass(slots=True)
    class Params:
        # gain thresholds (fraction over entry) at which to scale out, each ONCE.
        milestones: tuple = (0.50, 1.00, 1.50)
        trim_frac: float = 0.25            # fraction of CURRENT size trimmed at each milestone
        enabled: bool = True

        @classmethod
        def space(cls) -> ParamSpace:
            return ParamSpace(axes={"trim_frac": (0.20, 0.25, 0.33)})

    def __init__(self, params: "GainScaleOut.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        qc = ctx.qc
        date_str = ctx.time.strftime("%Y-%m-%d")
        st = _state(qc)
        meta = getattr(qc, "_position_meta", {})
        milestones = tuple(sorted(self.p.milestones))
        trims: list[str] = []
        freed = 0.0
        live: set = set()
        for sym, holding in list(qc.portfolio.items()):
            if not getattr(holding, "invested", False):
                continue
            live.add(sym)
            m = meta.get(sym)
            if not m or "entry_price" not in m:
                continue
            try:
                entry = float(m["entry_price"])
                close = float(qc.securities[sym].close)
                qty = int(holding.quantity)
            except (KeyError, AttributeError, TypeError, ValueError):
                continue
            if entry <= 0.0 or qty <= 0:
                continue
            entry_date = m.get("entry_date")
            rec = st.get(sym)
            if rec is None or rec["entry_date"] != entry_date:   # new / re-entered → reset the schedule
                st[sym] = rec = {"entry_date": entry_date, "fired": set()}
            gain = (close - entry) / entry
            # every UN-fired milestone this gain has crossed (handles a gap that clears several at once)
            crossed = [ms for ms in milestones if gain >= ms and ms not in rec["fired"]]
            if not crossed:
                continue
            trim_qty = int(qty * self.p.trim_frac)
            if trim_qty < 1 or trim_qty >= qty:
                # nothing to trim (sub-share) or would be a full exit (that's exit_hard's job, #379 Part A).
                # still MARK the milestones fired so we don't busy-retry a sub-share trim every bar.
                rec["fired"].update(crossed)
                continue
            rec["fired"].update(crossed)        # one trim per milestone — mark all crossed this bar
            ctx.bar_state.trim_intents.append(OrderIntent(
                ticker=sym.value, qty=-trim_qty, price=close, stop=0.0,
                module="profit.gain_scale_out", risk_dollars=0.0,
            ))
            freed += trim_qty * close
            trims.append(sym.value)
            log = getattr(qc, "log", None)
            if callable(log):
                hi = max(crossed)
                log(f"SCALE_OUT|{date_str}|{sym.value}|gain {gain*100:.0f}% crossed +{hi*100:.0f}%|"
                    f"trim {trim_qty}/{qty} @ {close:.2f} freed~${trim_qty * close:,.0f}")
        for s in [s for s in st if s not in live]:               # GC closed positions
            st.pop(s, None)
        return PhaseResult(
            decision=trims, blocked=False,
            reason=f"{len(trims)} gain-milestone scale-out(s) freed~${freed:,.0f}",
            facts={"trims": len(trims), "freed_cash": freed}, metrics={},
        )

    @property
    def version_marker(self) -> str:
        return "gain_scale_out_v1"
