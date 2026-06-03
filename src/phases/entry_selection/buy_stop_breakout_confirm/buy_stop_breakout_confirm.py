"""Entry-selection variant V1 (#348): BUY-STOP BREAKOUT confirm — forward-confirmation entry.

Kind: entry_selection · Clock: INTRADAY · Marker: buy_stop_breakout_confirm_v1

The #348 thesis lever. The instrumentation PROVED no static entry-day feature separates winners from
losers — HOOD (+175%) and MRVL (-37%) are identical at entry (score 7, conditions 11111101). So don't
PREDICT at signal-day; require the name to PROVE itself: enter ONLY when intraday price clears a
BUY-STOP set above the signal-day close (signal_price × (1 + breakout_buffer)). A name that breaks out
and runs (HOOD) triggers the stop; one that gaps then chops/fades (MRVL) never clears it → no entry.
This is Falk's own live mechanic (buy-stop-confirmed breakout) — delayed confirmation over prediction.

ONE VARIABLE vs S1: the entry-selection ALGO swaps (gap+vol confirm → buy-stop breakout); the
PreFlightStaleness guard, min_score>=7, regime, sizing, exit are all unchanged (the bridge preserves
them). The buy-stop level (breakout_buffer) and the wait window (window_bars) are sweepable to find
the discriminating breakout magnitude.

State (qc._entry_confirm, shared with the other confirm phases): per candidate {bars, confirmed,
expired}. A buy-stop rests for the window (default full session) — fills the first bar price clears
the level, expires unfilled at window close (the name failed to prove the breakout). blocked=False.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine.base import BasePhase, PhaseResult
from engine.context import PhaseContext
from engine.symbol_key import canonical_symbol_key
from phases.shared.param_space import ComplexityDecl, ParamSpace


def breakout_confirm_decision(
    *,
    curr_price: float | None,
    signal_price: float,
    breakout_buffer: float,
    bars_elapsed: int,
    window_bars: int,
) -> tuple[bool, str]:
    """PURE buy-stop decision (golden-masterable). CONFIRM iff, within the wait window, the intraday
    price has cleared the buy-stop = signal_price × (1 + breakout_buffer). curr_price None = warming."""
    if bars_elapsed > window_bars:
        return False, "window_closed"           # never broke out → the name failed to prove itself
    if curr_price is None or signal_price <= 0.0:
        return False, "warming"
    if curr_price < signal_price * (1.0 + breakout_buffer):
        return False, "below_buystop"           # not yet above the breakout level
    return True, "confirmed"                      # broke out → buy-stop fills


class BuyStopBreakoutConfirm(BasePhase):
    PHASE_KIND = "entry_selection"
    PHASE_RESOLUTION = "intraday"
    REQUIRES_UPSTREAM = ["signal"]
    PROVIDES_DOWNSTREAM = ["sized_orders"]

    COMPLEXITY = ComplexityDecl(
        free_params=2,
        note="breakout_buffer (buy-stop level above signal close) + window_bars (wait window).",
    )

    @dataclass(slots=True)
    class Params:
        # batch-1: sT10e's validated buy-stop level = signal close + 0.75% (one value, one variable).
        # batch-2 sweep candidates (if V1 shows signal): 0.005 / 0.0075 / 0.01 / 0.015.
        breakout_buffer: float = 0.0075
        window_bars: int = 78           # same-day: wait up to a full session (78 × 5-min) for breakout
        enabled: bool = True

        @classmethod
        def space(cls) -> ParamSpace:
            return ParamSpace(axes={"breakout_buffer": (0.005, 0.0075, 0.01, 0.015),
                                    "window_bars": (12, 39, 78)})

    def __init__(self, params: "BuyStopBreakoutConfirm.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        qc = ctx.qc
        active_by_key = {canonical_symbol_key(s): s for s in getattr(qc, "_active", set())}  # FIX3
        intraday = getattr(qc, "_intraday", {})
        confirm_state = getattr(qc, "_entry_confirm", None)
        if confirm_state is None:
            qc._entry_confirm = {}
            confirm_state = qc._entry_confirm
        kept: list[Any] = []
        confirmed = 0
        reasons: dict[str, int] = {}
        for intent in ctx.bar_state.sized_orders:
            tk = intent.ticker
            cs = confirm_state.setdefault(tk, {"bars": 0, "confirmed": False, "expired": False})
            if cs["confirmed"]:
                kept.append(intent)
                _sym = active_by_key.get(canonical_symbol_key(tk))
                if _sym is not None:
                    ctx.record_funnel("confirm_fire", _sym)  # already-confirmed stays in the dedup set
                continue
            if cs["expired"]:
                continue
            sym = active_by_key.get(canonical_symbol_key(tk))
            st = intraday.get(sym) if sym is not None else None
            if st is None:
                reasons["no_feed"] = reasons.get("no_feed", 0) + 1
                continue
            snap = qc.snapshot_for_entry(sym)  # H1/H2 (276b-0): signal_price = T's decision close
            if snap is None:
                reasons["no_snapshot"] = reasons.get("no_snapshot", 0) + 1
                continue
            signal_price = float(snap["signal_price"])
            curr_close = st.get("last_close")
            cs["bars"] += 1
            ok, reason = breakout_confirm_decision(
                curr_price=curr_close, signal_price=signal_price,
                breakout_buffer=self.p.breakout_buffer,
                bars_elapsed=cs["bars"], window_bars=self.p.window_bars,
            )
            reasons[reason] = reasons.get(reason, 0) + 1
            if ok:
                cs["confirmed"] = True
                confirmed += 1
                kept.append(intent)
                ctx.record_funnel("confirm_fire", sym)
            elif reason == "window_closed":
                cs["expired"] = True
        ctx.bar_state.sized_orders = kept
        return PhaseResult(
            decision=kept,
            blocked=False,
            reason=f"buy-stop-breakout-confirm: confirmed {confirmed}, kept {len(kept)} {reasons}",
            facts={"confirmed": confirmed, "kept": len(kept),
                   **{f"reason_{k}": v for k, v in reasons.items()}},
            metrics={},
        )

    @property
    def version_marker(self) -> str:
        return "buy_stop_breakout_confirm_v1"
