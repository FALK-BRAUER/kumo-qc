from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from base import BasePhase, PhaseResult
from context import PhaseContext
from symbol_key import canonical_symbol_key
from shared_param_space import ComplexityDecl, ParamSpace


def confirm_decision(
    *,
    prev_above: bool | None,
    curr_above: bool | None,
    curr_vol: float,
    vol_mean: float | None,
    vol_mult: float,
    bars_elapsed: int,
    window_bars: int,
) -> tuple[bool, str]:
    if bars_elapsed > window_bars:
        return False, "window_closed"
    if curr_above is None:
        return False, "warming"
    if prev_above is None:
        return False, "no_prior_bar"
    if not (curr_above and not prev_above):
        return False, "no_reclaim_cross"
    if vol_mean is None or vol_mean <= 0.0:
        return False, "no_vol_baseline"
    if curr_vol <= vol_mean * vol_mult:
        return False, "weak_volume"
    return True, "confirmed"


def _window_mean(window: Any) -> float | None:
    if window is None:
        return None
    count = getattr(window, "count", None)
    if count is None:
        try:
            count = len(window)
        except TypeError:
            return None
    if not count:
        return None
    return sum(float(window[i]) for i in range(count)) / count


class BctIntradayConfirm(BasePhase):
    PHASE_KIND = "entry_selection"
    PHASE_RESOLUTION = "intraday"
    REQUIRES_UPSTREAM = ["signal"]
    PROVIDES_DOWNSTREAM = ["sized_orders"]

    COMPLEXITY = ComplexityDecl(
        free_params=2,
        note="vol_mult (volume-expansion ceiling) + window_bars (confirm window length).",
    )

    @dataclass(slots=True)
    class Params:
        vol_mult: float = 1.5
        window_bars: int = 24
        enabled: bool = True

        @classmethod
        def space(cls) -> ParamSpace:
            return ParamSpace(axes={"vol_mult": (1.3, 1.5, 2.0), "window_bars": (12, 24, 36)})

    def __init__(self, params: "BctIntradayConfirm.Params", logger: Any) -> None:
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
            cs = confirm_state.setdefault(
                tk, {"bars": 0, "confirmed": False, "expired": False, "prev_above": None}
            )
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
            ok, reason = confirm_decision(
                prev_above=cs["prev_above"], curr_above=curr_above, curr_vol=curr_vol,
                vol_mean=vol_mean, vol_mult=self.p.vol_mult,
                bars_elapsed=cs["bars"], window_bars=self.p.window_bars,
            )
            if curr_above is not None:
                cs["prev_above"] = curr_above
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
            reason=f"intraday-confirm: confirmed {confirmed}, kept {len(kept)} {reasons}",
            facts={"confirmed": confirmed, "kept": len(kept),
                   **{f"reason_{k}": v for k, v in reasons.items()}},
            metrics={},
        )

    @property
    def version_marker(self) -> str:
        return "bct_intraday_confirm_v1"
