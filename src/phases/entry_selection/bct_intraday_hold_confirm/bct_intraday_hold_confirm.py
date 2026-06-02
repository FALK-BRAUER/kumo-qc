"""Entry-selection variant: INTRADAY ABOVE-TENKAN HOLD + rising-vol confirm (#276b-1 EXPERIMENT).

Kind: entry_selection · Clock: INTRADAY · Marker: bct_intraday_hold_confirm_v1

A SECOND intraday entry-confirm mechanic, built as an EXPERIMENT (run-to-learn, HQ) — NOT a champion
decision. The proven BctIntradayConfirm uses a tenkan-reclaim CROSS (≤→>), which is geometrically
OPPOSED to the pre-flight gap-up gate: a gap-up is typically ALREADY ABOVE the intraday Tenkan, so
there is no from-below cross to reclaim → ~0 confirms (no_reclaim_cross dominated; cloud Q1 + local
2wk both fired 0). This variant instead confirms on a HOLD ABOVE the Tenkan (a LEVEL, not a cross) +
a volume expansion — which CAN fire for a gap-up that opens + holds above Tenkan with conviction.

THE QUESTION this experiment answers (report both): (a) does the hold-confirm FIRE where the
reclaim-cross didn't? (b) does it have EDGE (Sharpe vs the champion_asis baseline), or does it just
fire on ~every gap-up (= no selectivity = no better than the blind-MOO fixture)? A confirm that
fires on everything is not a confirm — the rising-vol gate is the selectivity; the experiment
measures whether that selectivity carries edge.

Conditions (completed 5-min bars, windowed, defer-until-fired-or-window-closes — same lifecycle as
BctIntradayConfirm): close > intraday Tenkan (HOLD above) AND this bar's volume > mean(vol window) ×
vol_mult. NO reclaim-cross requirement (that is the proven phase, kept intact).

Changelog:
  v1  above-Tenkan hold + rising-volume confirm (the gap-up-compatible alternative to the
      reclaim-cross), windowed + deferred. EXPERIMENT — evidence for the mechanic methodology pass.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine.base import BasePhase, PhaseResult
from engine.symbol_key import canonical_symbol_key
from engine.context import PhaseContext
from phases.entry_selection.bct_intraday_confirm.bct_intraday_confirm import _window_mean
from phases.shared.param_space import ComplexityDecl, ParamSpace


def hold_confirm_decision(
    *,
    curr_above: bool | None,
    curr_vol: float,
    vol_mean: float | None,
    vol_mult: float,
    bars_elapsed: int,
    window_bars: int,
) -> tuple[bool, str]:
    """PURE above-Tenkan-hold decision (golden-masterable). CONFIRM iff, within the window, the
    completed-bar close is ABOVE the intraday Tenkan (a LEVEL check — `curr_above`) AND volume
    expands over the window-mean baseline × vol_mult. Unlike the reclaim-cross, NO from-below edge
    is required → a gap-up already above Tenkan CAN confirm (the whole point of the experiment)."""
    if bars_elapsed > window_bars:
        return False, "window_closed"
    if curr_above is None:
        return False, "warming"
    if not curr_above:
        return False, "below_tenkan"        # not holding above the Tenkan → no confirm
    if vol_mean is None or vol_mean <= 0.0:
        return False, "no_vol_baseline"
    if curr_vol <= vol_mean * vol_mult:
        return False, "weak_volume"          # the selectivity gate — no volume expansion → no confirm
    return True, "confirmed"


class BctIntradayHoldConfirm(BasePhase):
    PHASE_KIND = "entry_selection"
    PHASE_RESOLUTION = "intraday"
    REQUIRES_UPSTREAM = ["signal"]
    PROVIDES_DOWNSTREAM = ["sized_orders"]

    COMPLEXITY = ComplexityDecl(
        free_params=2,
        note="vol_mult (the volume-expansion selectivity gate) + window_bars (confirm window).",
    )

    @dataclass(slots=True)
    class Params:
        vol_mult: float = 1.5
        window_bars: int = 24
        enabled: bool = True

        @classmethod
        def space(cls) -> ParamSpace:
            return ParamSpace(axes={"vol_mult": (1.3, 1.5, 2.0), "window_bars": (12, 24, 36)})

    def __init__(self, params: "BctIntradayHoldConfirm.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        qc = ctx.qc
        active_by_key = {canonical_symbol_key(s): s for s in getattr(qc, "_active", set())}  # #276b-1 FIX3
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
                continue
            if cs["expired"]:
                continue
            sym = active_by_key.get(canonical_symbol_key(tk))
            st = intraday.get(sym) if sym is not None else None
            if st is None:
                reasons["no_feed"] = reasons.get("no_feed", 0) + 1
                continue
            ti = st.get("intraday_tenkan")
            tenkan = ti.current.value if (ti is not None and getattr(ti, "is_ready", False)) else None
            curr_close = st.get("last_close")
            curr_above = (curr_close > tenkan) if (tenkan is not None and curr_close is not None) else None
            last_bar = st.get("last_bar")
            curr_vol = float(getattr(last_bar, "volume", 0.0)) if last_bar is not None else 0.0
            vol_mean = _window_mean(st.get("vol_window"))
            cs["bars"] += 1
            ok, reason = hold_confirm_decision(
                curr_above=curr_above, curr_vol=curr_vol, vol_mean=vol_mean,
                vol_mult=self.p.vol_mult, bars_elapsed=cs["bars"], window_bars=self.p.window_bars,
            )
            reasons[reason] = reasons.get(reason, 0) + 1
            if ok:
                cs["confirmed"] = True
                confirmed += 1
                kept.append(intent)
            elif reason == "window_closed":
                cs["expired"] = True
        ctx.bar_state.sized_orders = kept
        return PhaseResult(
            decision=kept,
            blocked=False,
            reason=f"intraday-hold-confirm: confirmed {confirmed}, kept {len(kept)} {reasons}",
            facts={"confirmed": confirmed, "kept": len(kept),
                   **{f"reason_{k}": v for k, v in reasons.items()}},
            metrics={},
        )

    @property
    def version_marker(self) -> str:
        return "bct_intraday_hold_confirm_v1"
