"""Entry-selection variant: scanner-rank-aware gap/loud-open confirmation.

Kind: entry_selection · Clock: INTRADAY · Marker: rank_aware_gap_confirm_v1

This phase consumes the LambdaMART scanner rank frozen into the daily candidate snapshot. It does
not score candidates itself. Rank only changes how much completed-bar intraday evidence is required:
top-ranked names may pass a looser gap/loud-open rule, mid-ranked names use the current canonical
rule, and lower-ranked names need stronger confirmation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine.base import BasePhase, PhaseResult
from engine.context import PhaseContext
from engine.symbol_key import canonical_symbol_key
from phases.entry_selection.bct_intraday_confirm.bct_intraday_confirm import _window_mean
from phases.entry_selection.bct_intraday_gap_vol_confirm.bct_intraday_gap_vol_confirm import (
    gap_vol_confirm_decision,
)
from phases.shared.param_space import ComplexityDecl, ParamSpace


def rank_aware_gap_confirm_decision(
    *,
    scanner_rank: int | None,
    gap_pct: float | None,
    curr_vol: float,
    vol_mean: float | None,
    bars_elapsed: int,
    window_bars: int,
    top_rank_max: int,
    mid_rank_max: int,
    top_gap_threshold: float,
    top_vol_mult: float,
    mid_gap_threshold: float,
    mid_vol_mult: float,
    tail_gap_threshold: float,
    tail_vol_mult: float,
) -> tuple[bool, str, str]:
    """Return (confirmed, reason, bucket) for a point-in-time rank-aware entry decision."""
    if scanner_rank is None or scanner_rank <= 0:
        return False, "no_scanner_context", "missing"
    if scanner_rank <= top_rank_max:
        bucket = "top"
        gap_threshold = top_gap_threshold
        vol_mult = top_vol_mult
    elif scanner_rank <= mid_rank_max:
        bucket = "mid"
        gap_threshold = mid_gap_threshold
        vol_mult = mid_vol_mult
    else:
        bucket = "tail"
        gap_threshold = tail_gap_threshold
        vol_mult = tail_vol_mult
    ok, reason = gap_vol_confirm_decision(
        gap_pct=gap_pct,
        gap_threshold=gap_threshold,
        curr_vol=curr_vol,
        vol_mean=vol_mean,
        vol_mult=vol_mult,
        bars_elapsed=bars_elapsed,
        window_bars=window_bars,
    )
    return ok, f"{bucket}_{reason}", bucket


class RankAwareGapConfirm(BasePhase):
    PHASE_KIND = "entry_selection"
    PHASE_RESOLUTION = "intraday"
    REQUIRES_UPSTREAM = ["signal", "scanner_ranker_features"]
    PROVIDES_DOWNSTREAM = ["sized_orders"]

    COMPLEXITY = ComplexityDecl(
        free_params=0,
        note="Canonical rank-bucket confirmer; custom sweep grids count rank bucket knobs explicitly.",
    )

    @dataclass(slots=True)
    class Params:
        top_rank_max: int = 10
        mid_rank_max: int = 20
        top_gap_threshold: float = 0.025
        top_vol_mult: float = 0.80
        mid_gap_threshold: float = 0.030
        mid_vol_mult: float = 1.00
        tail_gap_threshold: float = 0.050
        tail_vol_mult: float = 1.25
        window_bars: int = 6
        enabled: bool = True

        @classmethod
        def space(cls) -> ParamSpace:
            return ParamSpace(axes={})

    def __init__(self, params: "RankAwareGapConfirm.Params", logger: Any) -> None:
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
        buckets: dict[str, int] = {}
        for intent in ctx.bar_state.sized_orders:
            tk = intent.ticker
            cs = confirm_state.setdefault(tk, {"bars": 0, "confirmed": False, "expired": False})
            sym = active_by_key.get(canonical_symbol_key(tk))
            if cs["confirmed"]:
                kept.append(intent)
                if sym is not None:
                    ctx.record_funnel("gap_eligible", sym)
                    ctx.record_funnel("confirm_fire", sym)
                continue
            if cs["expired"]:
                continue
            if sym is None:
                reasons["no_active_symbol"] = reasons.get("no_active_symbol", 0) + 1
                continue

            st = intraday.get(sym)
            if st is None:
                reasons["no_feed"] = reasons.get("no_feed", 0) + 1
                continue
            snap = qc.snapshot_for_entry(sym)
            if snap is None:
                reasons["no_snapshot"] = reasons.get("no_snapshot", 0) + 1
                continue

            signal_price = float(snap["signal_price"])
            curr_close = st.get("last_close")
            gap_pct = ((curr_close - signal_price) / signal_price
                       if (curr_close is not None and signal_price > 0.0) else None)
            last_bar = st.get("last_bar")
            curr_vol = float(getattr(last_bar, "volume", 0.0)) if last_bar is not None else 0.0
            vol_mean = _window_mean(st.get("vol_window"))
            scanner_rank_raw = snap.get("scanner_rank")
            scanner_rank = int(scanner_rank_raw) if scanner_rank_raw is not None else None

            cs["bars"] += 1
            ok, reason, bucket = rank_aware_gap_confirm_decision(
                scanner_rank=scanner_rank,
                gap_pct=gap_pct,
                curr_vol=curr_vol,
                vol_mean=vol_mean,
                bars_elapsed=cs["bars"],
                window_bars=self.p.window_bars,
                top_rank_max=self.p.top_rank_max,
                mid_rank_max=self.p.mid_rank_max,
                top_gap_threshold=self.p.top_gap_threshold,
                top_vol_mult=self.p.top_vol_mult,
                mid_gap_threshold=self.p.mid_gap_threshold,
                mid_vol_mult=self.p.mid_vol_mult,
                tail_gap_threshold=self.p.tail_gap_threshold,
                tail_vol_mult=self.p.tail_vol_mult,
            )
            reasons[reason] = reasons.get(reason, 0) + 1
            buckets[bucket] = buckets.get(bucket, 0) + 1

            core_reason = reason.removeprefix(f"{bucket}_") if bucket != "missing" else reason
            if core_reason in ("confirmed", "quiet_open", "no_vol_baseline"):
                ctx.record_funnel("gap_eligible", sym)
            if ok:
                cs["confirmed"] = True
                confirmed += 1
                kept.append(intent)
                ctx.record_funnel("confirm_fire", sym)
            elif core_reason == "window_closed":
                cs["expired"] = True

        ctx.bar_state.sized_orders = kept
        return PhaseResult(
            decision=kept,
            blocked=False,
            reason=f"rank-aware-gap-confirm: confirmed {confirmed}, kept {len(kept)} {reasons}",
            facts={
                "confirmed": confirmed,
                "kept": len(kept),
                **{f"reason_{key}": value for key, value in reasons.items()},
                **{f"bucket_{key}": value for key, value in buckets.items()},
            },
            metrics={},
        )

    @property
    def version_marker(self) -> str:
        return "rank_aware_gap_confirm_v1"
