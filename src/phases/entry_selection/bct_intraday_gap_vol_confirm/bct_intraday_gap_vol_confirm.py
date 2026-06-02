"""Entry-selection variant: GAP-MAGNITUDE + LOUD-OPEN confirm (#276b-1 / #277 — the Rank-1 mechanic).

Kind: entry_selection · Clock: INTRADAY · Marker: bct_intraday_gap_vol_confirm_v1

The data-grounded confirm (HQ's George gap-up analysis, research/intraday-confirm-mechanic-analysis.md
— the Rank-1 candidate). The geometry the analysis PROVED: 96.5% of George's entries gap up (mean
+5.17%); 93.8% open already above prior close and never dip below it → a from-below reclaim cross
DOES NOT EXIST → the reclaim-cross confirm fires ~0× BY STRUCTURE. And winners OPEN STRONG + HOLD
(median open→close +0.22%) — they do NOT surge, so a rising-VOLUME-SURGE gate also rejects them.

What DOES separate the winning cohort, using ONLY real-time-observable-at-open signals (NO Tenkan —
the BCT pipeline has no validated intraday Tenkan): GAP MAGNITUDE + a LOUD (not quiet) OPEN.
  - gap_pct = (intraday price − signal_price) / signal_price ≥ `gap_threshold` (≥+3-4%): the
    selective gap cohort (gap≥+4% alone fired 30% at 91% win; gap≥+3% + loud-open fired 14% at 92%).
  - first-bar volume ≥ `vol_mult` × the window-mean baseline (LOUD = at least average; vol_mult=1.0).
    NOT a surge multiple (winners hold, don't surge — a >1.5× gate kills them, the Rank-2 result).
NO Tenkan dependency (Rank-1's edge over the hold-confirm, which rests on unvalidated intraday-Tenkan
machinery). Windowed to the OPEN-30m (the gap+loud-open signal lives at the open), defer-until-fired.

EXPERIMENT framing (HQ): evidence for Falk's confirm-mechanic methodology call, NOT an autonomous
champion pick. CAVEATS the cloud test must own: BCT date-lag (±1-2d, event-candle ≠ fill bar) +
small-n cohorts → the 92% win is INDICATIVE; the cloud Sharpe is the truth. The built execution
engine (inject/sizing/Kijun-floor/FIRE + daily exit) is REUSED — only this confirm phase swaps in.

Changelog:
  v1  gap-magnitude (≥threshold) + loud-open (vol ≥ baseline) confirm, no-Tenkan, open-30m window.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine.base import BasePhase, PhaseResult
from engine.symbol_key import canonical_symbol_key
from engine.context import PhaseContext
from phases.entry_selection.bct_intraday_confirm.bct_intraday_confirm import _window_mean
from phases.shared.param_space import ComplexityDecl, ParamSpace


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
    """PURE gap+loud-open decision (golden-masterable, NO Tenkan). CONFIRM iff, within the open
    window, the gap (intraday vs signal price) is ≥ gap_threshold AND this bar's volume is ≥ vol_mult
    × the window-mean baseline (a LOUD open — vol_mult=1.0 = at-least-average, NOT a surge multiple).
    gap_pct None = no price yet (warming)."""
    if bars_elapsed > window_bars:
        return False, "window_closed"
    if gap_pct is None:
        return False, "warming"
    if gap_pct < gap_threshold:
        return False, "gap_too_small"          # below the selective gap cohort
    if vol_mean is None or vol_mean <= 0.0:
        return False, "no_vol_baseline"
    if curr_vol < vol_mean * vol_mult:
        return False, "quiet_open"              # not a loud open (< baseline) — the selectivity gate
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
        gap_threshold: float = 0.03   # gap ≥ +3% (the selective cohort; sweep 0.03/0.04/0.05)
        vol_mult: float = 1.0         # LOUD open = vol ≥ 1× baseline (NOT a surge — winners hold)
        window_bars: int = 6          # open-30m (6 × 5-min) — the gap+loud-open signal lives at open
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
                # already confirmed on a prior tick → still record stages 4+5 (a confirmed candidate
                # IS gap-eligible) so the per-day dedup set stays complete. #276b-1 funnel.
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
            # H1/H2 (276b-0): the snapshot's signal_price is the gap reference (T's decision close).
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
            # #276b-1 funnel stage 4 (gap_eligible): the gap-magnitude check PASSED this tick. The
            # decision returns gap_too_small ONLY when gap < threshold; any reason AFTER that point
            # (confirmed | quiet_open | no_vol_baseline) means the gap cleared the bar (observe-only).
            if reason in ("confirmed", "quiet_open", "no_vol_baseline"):
                ctx.record_funnel("gap_eligible", sym)
            if ok:
                cs["confirmed"] = True
                confirmed += 1
                kept.append(intent)
                ctx.record_funnel("confirm_fire", sym)  # #276b-1 funnel stage 5 (observe-only)
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
