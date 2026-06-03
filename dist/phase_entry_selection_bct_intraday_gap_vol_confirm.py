from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from base import BasePhase, PhaseResult
from symbol_key import canonical_symbol_key
from context import PhaseContext
from phase_entry_selection_bct_intraday_confirm import _window_mean
from shared_param_space import ComplexityDecl, ParamSpace


def gap_vol_confirm_decision(
    *,
    gap_pct: float | None,
    gap_threshold: float,
    curr_vol: float,
    vol_mean: float | None,
    vol_mult: float,
    bars_elapsed: int,
    window_bars: int,
) -> tuple[bool, str]:
    if bars_elapsed > window_bars:
        return False, "window_closed"
    if gap_pct is None:
        return False, "warming"
    if gap_pct < gap_threshold:
        return False, "gap_too_small"
    if vol_mean is None or vol_mean <= 0.0:
        return False, "no_vol_baseline"
    if curr_vol < vol_mean * vol_mult:
        return False, "quiet_open"
    return True, "confirmed"


class BctIntradayGapVolConfirm(BasePhase):
    PHASE_KIND = "entry_selection"
    PHASE_RESOLUTION = "intraday"
    REQUIRES_UPSTREAM = ["signal"]
    PROVIDES_DOWNSTREAM = ["sized_orders"]

    COMPLEXITY = ComplexityDecl(
        free_params=3,
        note="gap_threshold (the selective gap cohort) + vol_mult (loud-open) + window_bars (open window).",
    )

    @dataclass(slots=True)
    class Params:
        gap_threshold: float = 0.03
        vol_mult: float = 1.0
        window_bars: int = 6
        enabled: bool = True

        @classmethod
        def space(cls) -> ParamSpace:
            return ParamSpace(axes={"gap_threshold": (0.03, 0.04, 0.05),
                                    "vol_mult": (1.0, 1.25, 1.5),
                                    "window_bars": (6, 12)})

    def __init__(self, params: "BctIntradayGapVolConfirm.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        qc = ctx.qc
        active_by_key = {canonical_symbol_key(s): s for s in getattr(qc, "_active", set())}
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
                    ctx.record_funnel("gap_eligible", _sym)
                    ctx.record_funnel("confirm_fire", _sym)
                continue
            if cs["expired"]:
                continue
            sym = active_by_key.get(canonical_symbol_key(tk))
            st = intraday.get(sym) if sym is not None else None
            if st is None:
                reasons["no_feed"] = reasons.get("no_feed", 0) + 1
                continue
            curr_close = st.get("last_close")
            snap = qc.snapshot_for_entry(sym)
            if snap is None:
                reasons["no_snapshot"] = reasons.get("no_snapshot", 0) + 1
                continue
            signal_price = float(snap["signal_price"])
            gap_pct = ((curr_close - signal_price) / signal_price
                       if (curr_close is not None and signal_price > 0.0) else None)
            last_bar = st.get("last_bar")
            curr_vol = float(getattr(last_bar, "volume", 0.0)) if last_bar is not None else 0.0
            vol_mean = _window_mean(st.get("vol_window"))
            cs["bars"] += 1
            ok, reason = gap_vol_confirm_decision(
                gap_pct=gap_pct, gap_threshold=self.p.gap_threshold, curr_vol=curr_vol,
                vol_mean=vol_mean, vol_mult=self.p.vol_mult,
                bars_elapsed=cs["bars"], window_bars=self.p.window_bars,
            )
            reasons[reason] = reasons.get(reason, 0) + 1
            if reason in ("confirmed", "quiet_open", "no_vol_baseline"):
                ctx.record_funnel("gap_eligible", sym)
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
            reason=f"intraday-gap-vol-confirm: confirmed {confirmed}, kept {len(kept)} {reasons}",
            facts={"confirmed": confirmed, "kept": len(kept),
                   **{f"reason_{k}": v for k, v in reasons.items()}},
            metrics={},
        )

    @property
    def version_marker(self) -> str:
        return "bct_intraday_gap_vol_confirm_v1"
