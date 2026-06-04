"""Add phase: StagedRiskPyramid — pyramid INTO confirmed winners (#340-B / Pe-rampup, #172/#178).

Kind: adds   Marker: staged_risk_pyramid_<variant>_v1

The strategy is let-winners-run; this phase AMPLIFIES the right tail by adding staged-risk tranches
to a HELD position that is (a) IN PROFIT and (b) printing a FRESH Tenkan>Kijun cross (the Pe trigger,
the recorded 1.486-Sharpe winner). ADD-TO-WINNERS-ONLY — never averages down. Tranche sizing reuses
the prior pure pyramid_engine (Pe-rampup = staged $200/$400/$600, anti-Kelly grow-with-evidence),
capped at `max_adds` per position. The engine bounds add_intents to the gross cap at FIRE_ADDS
(GrossExposureCap.bound_adds) → adds never breach leverage. Core S1 (signal/entry/exit) UNTOUCHED.

State: per-position {entry_date, lots, prev_tk_above}, keyed by symbol, reset on a new entry_date
(re-entry) and GC'd when the position closes — so `lots`/the cross-edge never leak across positions.
A fresh position seeds state on first sight and does NOT add that bar (no prior bar to cross from).

Charter: adds run only when the bar is not blocked (engine ENTRY_ONLY_PHASES). A cold/absent daily
Ichimoku → benign SKIP (no add), NOT a raise: unlike an exit (an unprotected ride), a missing add is
a missed opportunity, not unevaluated risk.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine.base import BasePhase, PhaseResult
from engine.context import OrderIntent, PhaseContext
from phases.shared.param_space import ComplexityDecl, ParamSpace

from .pyramid_engine import add_dollars


class StagedRiskPyramid(BasePhase):
    PHASE_KIND = "adds"
    # DAILY clock (deliberate — code-review #340-B): an add fires market-on-open off a DAILY fresh
    # Tenkan>Kijun cross. This is daily-decision→MOO, the shape the two-clock charter avoids for fresh
    # ENTRIES — but an add is NOT a fresh entry: it amplifies a HELD position that ALREADY cleared the
    # intraday entry-confirm gate, on a daily STRUCTURAL signal (the cross). The intraday-confirm
    # discipline guards UNPROVEN entries; an add to a proven, in-profit held winner is a structural
    # let-run amplification. Faithful to the daily-triggered Pe-rampup (the recorded 1.486). The
    # survival-ledger BT is the gate; an intraday add-confirm is a deferred v2 if this proves out.
    PHASE_RESOLUTION = "daily"
    REQUIRES_UPSTREAM: list[str] = []
    PROVIDES_DOWNSTREAM = ["add_intents"]

    @dataclass(slots=True)
    class Params:
        variant: str = "Pe-rampup"   # pyramid_engine sizing scheme (the 1.486-Sharpe winner)
        max_adds: int = 2            # adds per position (lots cap = 1 initial + max_adds)
        enabled: bool = True

        @classmethod
        def space(cls) -> ParamSpace:
            return ParamSpace(axes={"max_adds": (1, 2, 3)})

    COMPLEXITY = ComplexityDecl(free_params=1, note="max_adds (the add cap); variant fixed per run.")

    def __init__(self, params: "StagedRiskPyramid.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params
        self._state: dict[Any, dict] = {}  # symbol → {entry_date, lots, prev_tk_above}

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        qc = ctx.qc
        added: list[str] = []
        live: set = set()

        for symbol, holding in list(qc.portfolio.items()):
            if not holding.invested:
                continue
            live.add(symbol)
            if qc.transactions.get_open_orders(symbol):
                continue  # an order already in flight for this name — don't stack
            ind = getattr(qc, "_indicators", {}).get(symbol)
            meta = getattr(qc, "_position_meta", {}).get(symbol)
            if ind is None or meta is None:
                continue
            d_ichi = ind.get("d_ichi")
            if d_ichi is None or not d_ichi.is_ready:
                continue  # benign: no warm signal → no add (a missed add, not unevaluated risk)
            close = float(qc.securities[symbol].close)
            entry_price = float(meta["entry_price"])
            entry_date = meta["entry_date"]
            if entry_price <= 0.0 or close <= 0.0:
                continue

            tk_above = d_ichi.tenkan.current.value > d_ichi.kijun.current.value
            st = self._state.get(symbol)
            if st is None or st["entry_date"] != entry_date:
                # new (or re-entered) position → seed state; NO add on the first bar (no prior cross)
                self._state[symbol] = {"entry_date": entry_date, "lots": 1, "prev_tk_above": tk_above}
                continue
            fresh_cross = tk_above and not st["prev_tk_above"]  # the Pe trigger: a FRESH Tenkan>Kijun cross
            st["prev_tk_above"] = tk_above

            if st["lots"] - 1 >= self.p.max_adds:        # this position has used all its adds
                continue
            if not (close > entry_price and fresh_cross):  # ADD-TO-WINNERS-ONLY + fresh confirmation
                continue
            dollars = add_dollars(self.p.variant, st["lots"], entry_price=entry_price, close=close)
            if dollars <= 0.0:
                continue
            qty = int(dollars / close)
            if qty < 1:
                continue
            ctx.bar_state.add_intents.append(OrderIntent(
                ticker=symbol.value, qty=qty, price=close, stop=0.0,
                module="adds.staged_risk_pyramid", risk_dollars=float(dollars),
            ))
            st["lots"] += 1
            added.append(symbol.value)

        for s in [s for s in self._state if s not in live]:  # GC closed positions (no leak / stale re-entry)
            self._state.pop(s, None)

        return PhaseResult(
            decision=added, blocked=False,
            reason=f"staged-risk pyramid ({self.p.variant}): {len(added)} adds",
            facts={"add_count": len(added)}, metrics={},
        )

    @property
    def version_marker(self) -> str:
        return f"staged_risk_pyramid_{self.p.variant}_v1"
