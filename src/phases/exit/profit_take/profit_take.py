"""Exit phase: ProfitTake — bank TRENDING winners at/near the peak (#364 R2, layered on R1-C).

The #270 pure-let-run champion NEVER booked → realized-negative (paper gains evaporated). Rotation
(R1-C) protects runners + recycles only truly-dead; ProfitTake adds the OTHER half: realize the
protected runner's gain on a disciplined trailing/laddered trim, instead of riding it back to flat.

Three modes (one-lever-diff R2 screen), DAILY clock, PARTIAL-exit capable:
  - "partial_trim"      : at gain >= trim_at_gain, sell trim_frac of the position ONCE; the rest
                          rides until close < daily Kijun (then full exit). Bank half the win, let
                          the other half run on a structure stop.
  - "tenkan_ratchet"    : a ratcheting trailing stop — tracks daily Tenkan (tight) until the runner
                          confirms (close >= Tenkan), then tracks daily Kijun (room); the stop only
                          RATCHETS UP (never lowered). Full exit when close < the ratchet stop.
  - "scale_out_ladder"  : sell 1/3 at +ladder1, 1/3 at +ladder2 (each rung once), final 1/3 on
                          close < daily Kijun. Bank in tranches up the move.

Per-position state lives in qc._position_meta[sym]["pt"] (persists across days; engine clears the
whole meta entry on a FULL close → clean re-entry). Needs entry_price (engine-stamped) + a ready
d_ichi. default enabled=False → byte-unchanged (the phase emits nothing).

blocked=False always. Emits PARTIAL exit intents (qty < full holding) — the remaining position stays
invested; only the final rung / Kijun-break is a full close.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from engine.base import BasePhase, PhaseResult
from engine.context import OrderIntent, PhaseContext


class ProfitTake(BasePhase):
    PHASE_KIND = "exit_target"  # the engine's recognized profit-TARGET exit slot (in PHASE_ORDER)
    PHASE_RESOLUTION = "daily"
    REQUIRES_UPSTREAM: list[str] = []
    PROVIDES_DOWNSTREAM = ["exit_intents"]

    @dataclass(slots=True)
    class Params:
        mode: str = "partial_trim"      # partial_trim | tenkan_ratchet | scale_out_ladder
        trim_at_gain: float = 0.20      # partial_trim: gain threshold to trim
        trim_frac: float = 0.5          # partial_trim: fraction sold at the threshold
        ladder1: float = 0.20           # scale_out_ladder: first rung gain (sell 1/3)
        ladder2: float = 0.40           # scale_out_ladder: second rung gain (sell 1/3)
        enabled: bool = False           # default OFF → byte-unchanged

    def __init__(self, params: "ProfitTake.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params

    @staticmethod
    def _ctx(qc: Any, sym: Any) -> tuple[float, float, float, float] | None:
        """(close, entry_px, tenkan, kijun) or None if unavailable / d_ichi not ready / no entry."""
        meta = getattr(qc, "_position_meta", {}).get(sym)
        if meta is None:
            return None
        entry_px = float(meta.get("entry_price", 0.0) or 0.0)
        if entry_px <= 0.0:
            return None
        ind = getattr(qc, "_indicators", {}).get(sym)
        d_ichi = ind.get("d_ichi") if ind else None
        if d_ichi is None or not getattr(d_ichi, "is_ready", False):
            return None
        try:
            close = float(qc.securities[sym].close)
            return close, entry_px, float(d_ichi.tenkan.current.value), float(d_ichi.kijun.current.value)
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _pt_state(qc: Any, sym: Any) -> dict[str, Any]:
        """Per-position ProfitTake state, persisted in _position_meta[sym]['pt']."""
        meta = qc._position_meta.setdefault(sym, {})
        st: dict[str, Any] = meta.setdefault("pt", {})
        return st

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        qc = ctx.qc
        date_str = ctx.time.strftime("%Y-%m-%d")
        pf = qc.portfolio
        trims = 0
        for sym, holding in list(pf.items()):
            if not getattr(holding, "invested", False):
                continue
            c = self._ctx(qc, sym)
            if c is None:
                continue
            close, entry_px, tenkan, kijun = c
            gain = (close - entry_px) / entry_px
            qty = int(holding.quantity)
            st = self._pt_state(qc, sym)
            sell = 0
            full = False
            if self.p.mode == "partial_trim":
                if not st.get("trimmed") and gain >= self.p.trim_at_gain:
                    sell = int(qty * self.p.trim_frac); st["trimmed"] = True
                elif st.get("trimmed") and close < kijun:
                    sell = qty; full = True
            elif self.p.mode == "tenkan_ratchet":
                ref = kijun if (st.get("crossed") or close >= tenkan) else tenkan
                if close >= tenkan:
                    st["crossed"] = True
                st["stop"] = max(float(st.get("stop", 0.0)), ref)  # ratchet up only, never lower
                if close < st["stop"]:
                    sell = qty; full = True
            elif self.p.mode == "scale_out_ladder":
                rungs = st.setdefault("rungs", [])
                if 1 not in rungs and gain >= self.p.ladder1:
                    sell = qty // 3; rungs.append(1)
                elif 2 not in rungs and gain >= self.p.ladder2:
                    sell = qty // 3; rungs.append(2)
                elif close < kijun:
                    sell = qty; full = True
            if sell <= 0:
                continue
            sell = min(sell, qty)
            ctx.bar_state.exit_intents.append(OrderIntent(
                ticker=sym.value, qty=-sell, price=close, stop=0.0,
                module="exit.profit_take", risk_dollars=0.0,
            ))
            trims += 1
            log = getattr(qc, "log", None)
            if callable(log):
                kind = "full" if full else "partial"
                log(f"PROFIT_TAKE|{date_str}|{sym.value}|{self.p.mode}|{kind}|"
                    f"gain={gain:.3f}|sold={sell}/{qty}")
        return PhaseResult(decision=[], blocked=False,
                           reason=f"{trims} profit-take trim(s) [{self.p.mode}]",
                           facts={"trims": trims}, metrics={})

    @property
    def version_marker(self) -> str:
        return "profit_take_v1"
