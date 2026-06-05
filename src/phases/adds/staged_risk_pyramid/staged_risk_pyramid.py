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

from phases.adds.staged_risk_pyramid.pyramid_engine import add_dollars


def _is_stop_order(order: Any) -> bool:
    """True if a LEAN open order is a resting protective STOP (StopMarket/StopLimit/TrailingStop).

    Such a GTC stop sits on EVERY held position (CloudProtectiveStop places one at FIRE_ENTRIES) — so
    it must NOT block a pyramid add. THE #340-B BUG: the open-order guard skipped every held name every
    bar (FY: 2326/2326 evals = 100% open-order-present, ZERO adds, byte-identical to S1) because the
    standing protective stop made get_open_orders() always non-empty. Pending ENTRY/ADD orders
    (Market/MarketOnOpen/Limit) are NOT stops → they still block (so adds never STACK on an unfilled
    order — the guard's real purpose).

    Name-based (`str(order.type)` contains 'STOP') — deliberately avoids a hard `QuantConnect.Orders`
    enum import so the pure-Python unit tests run without the LEAN runtime; every OrderType member with
    'Stop' in its name (StopMarket/StopLimit/TrailingStop) is a resting/protective order, never a
    pending entry. Checks both snake (`type`) and Pascal (`Type`) bindings defensively.

    ASSUMPTION (pinned, code-review #340-B): clr renders a C# OrderType enum value as its MEMBER NAME
    ("StopMarket"), not its integer ("4"). The whole fix hinges on this — if str() ever yielded the
    int, every order would read non-stop and the zero-adds bug would silently return. Verified against
    the LEAN OrderType members (no non-stop member contains 'stop'); the regression tests assert it."""
    t = getattr(order, "type", None)
    if t is None:
        t = getattr(order, "Type", "")
    return "STOP" in str(t).upper()


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

    def _diag(self, qc: Any, sym: Any, reason: str, **fields: Any) -> None:
        """#340-B instrumentation: per-held-position per-bar add-eval trace → LEAN log.txt. Makes the
        no-op FAIL-LOUD-VISIBLE (a pyramid firing 0 adds over a full year is a bug, not 'no opportunity'
        — the skip_reason histogram pinpoints WHERE the add-path dies). Diagnostic-only; remove/gate
        once the add-path is proven firing."""
        log = getattr(qc, "log", None)
        if callable(log):
            kv = " ".join(f"{k}={v}" for k, v in fields.items())
            log(f"PYRAMID_EVAL|{getattr(sym, 'value', sym)}|reason={reason} {kv}")

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        qc = ctx.qc
        added: list[str] = []
        live: set = set()

        for symbol, holding in list(qc.portfolio.items()):
            if not holding.invested:
                continue
            live.add(symbol)
            open_orders = qc.transactions.get_open_orders(symbol) or []
            pending_entry_add = [o for o in open_orders if not _is_stop_order(o)]
            if pending_entry_add:
                # a pending ENTRY/ADD is still in flight for this name — don't STACK a duplicate add.
                # Resting GTC protective STOPS are EXCLUDED (#340-B): they sit on every held position
                # and previously blocked every add (the guard fired on the stop, never on a real
                # in-flight entry/add). Now the guard fires ONLY on pending entries/adds.
                self._diag(qc, symbol, "pending-entry-add",
                           pending=len(pending_entry_add), stops=len(open_orders) - len(pending_entry_add))
                continue
            ind = getattr(qc, "_indicators", {}).get(symbol)
            meta = getattr(qc, "_position_meta", {}).get(symbol)
            if ind is None or meta is None:
                self._diag(qc, symbol, "ind-or-meta-none", has_ind=ind is not None, has_meta=meta is not None)
                continue
            d_ichi = ind.get("d_ichi")
            if d_ichi is None or not d_ichi.is_ready:
                self._diag(qc, symbol, "dichi-cold", dichi=d_ichi is not None)
                continue  # benign: no warm signal → no add (a missed add, not unevaluated risk)
            close = float(qc.securities[symbol].close)
            entry_price = float(meta["entry_price"])
            entry_date = meta["entry_date"]
            if entry_price <= 0.0 or close <= 0.0:
                self._diag(qc, symbol, "bad-price", entry=entry_price, close=close)
                continue

            tk_above = d_ichi.tenkan.current.value > d_ichi.kijun.current.value
            unreal_pct = (close / entry_price - 1.0) * 100.0
            st = self._state.get(symbol)
            if st is None or st["entry_date"] != entry_date:
                # new (or re-entered) position → seed state; NO add on the first bar (no prior cross)
                self._state[symbol] = {"entry_date": entry_date, "lots": 1, "prev_tk_above": tk_above}
                self._diag(qc, symbol, "seed", tk_above=tk_above, unreal_pct=round(unreal_pct, 1))
                continue
            prev_tk_above = st["prev_tk_above"]
            fresh_cross = tk_above and not prev_tk_above  # the Pe trigger: a FRESH Tenkan>Kijun cross
            st["prev_tk_above"] = tk_above

            if st["lots"] - 1 >= self.p.max_adds:        # this position has used all its adds
                self._diag(qc, symbol, "lots-maxed", lots=st["lots"], max_adds=self.p.max_adds)
                continue
            if not (close > entry_price and fresh_cross):  # ADD-TO-WINNERS-ONLY + fresh confirmation
                self._diag(qc, symbol, "no-trigger", tk_above=tk_above, prev_tk=prev_tk_above,
                           fresh_cross=fresh_cross, winner=close > entry_price, unreal_pct=round(unreal_pct, 1))
                continue
            # uncapped=True → max_adds (enforced above) is the SINGLE cap source; the engine's ramp
            # keeps sizing past the ADD_SIZES list (#340-B review: capped mode silently returns $0 for
            # add-index ≥ len(sizes), making max_adds=3 a no-op for its top tranche). Identical $ to
            # capped mode within [200,400,600]; only extends the rampup beyond it.
            dollars = add_dollars(self.p.variant, st["lots"], uncapped=True, entry_price=entry_price, close=close)
            if dollars <= 0.0:
                self._diag(qc, symbol, "zero-dollars", lots=st["lots"])
                continue
            qty = int(dollars / close)
            if qty < 1:
                self._diag(qc, symbol, "qty-lt-1", dollars=dollars, close=close)
                continue
            ctx.bar_state.add_intents.append(OrderIntent(
                ticker=symbol.value, qty=qty, price=close, stop=0.0,
                module="adds.staged_risk_pyramid", risk_dollars=float(dollars),
            ))
            st["lots"] += 1
            added.append(symbol.value)
            self._diag(qc, symbol, "ADD-PLACED", lots=st["lots"], qty=qty, dollars=dollars,
                       unreal_pct=round(unreal_pct, 1))

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
