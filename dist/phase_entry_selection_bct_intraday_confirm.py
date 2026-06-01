"""Entry-selection sub-role 2: the INTRADAY ENTRY-CONFIRM trigger (#276b-1 / #270, GH#25).

Kind: entry_selection · Clock: INTRADAY · Marker: bct_intraday_confirm_v1

The intraday EVENT that actually fires an entry on T+1. A daily candidate (snapshot'd by 276b-0,
pre-flight-validated by PreFlightStaleness) WAITS on the 5-min clock for the BCT intraday entry
signal, then confirms. Two conditions, both on COMPLETED 5-min bars:

  1. TENKAN RECLAIM — the EVENT, an upward CROSS of the intraday Tenkan, NOT a level check. The
     completed-bar close goes from ≤ Tenkan (prior bar) to > Tenkan (this bar). A level check
     ("close > Tenkan") would fire on ANY bar already above Tenkan (no edge) — wrong. We track the
     prior bar's above/below state per candidate and fire only on the not-above → above transition.
  2. RISING VOLUME — this bar's volume > mean(intraday vol window) × `vol_mult` (default 1.5). NOT
     strictly-increasing; a volume EXPANSION over the recent baseline (the conviction filter).

WINDOW: confirm is allowed for ~`window_bars` completed 5-min bars (≈24 = 2h; the mass is the
open 30m). The candidate DEFERS across bars until it confirms OR the window closes — a candidate
that never confirms is dropped (SG5), no bleed into T+2 (per-session state cleared at session end).

Reads the per-candidate intraday state `qc._intraday[sym]` ({intraday_tenkan, vol_window,
last_close, last_bar} — maintained by lean_entry on each 5-min bar) and tracks deferred progress in
`qc._entry_confirm[ticker]` (the 276b-0 session store, cleared at session end). It GATES the
injected candidate stubs in `ctx.bar_state.sized_orders`: a CONFIRMED candidate is kept (flows to
entry_timing → sizing → FIRE_ENTRIES); a deferred/expired one is dropped THIS tick. Charter: single
code path, completed-bar only (look-ahead-safe), RAW.

Changelog:
  v1  intraday tenkan-reclaim CROSS + rising-volume confirm, windowed + deferred, reading the
      276b-0 intraday state + session-persistent confirm progress.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from base import BasePhase, PhaseResult
from context import PhaseContext
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
    """PURE intraday-confirm decision (golden-masterable — no QC objects).

    CONFIRM iff, within the window, the completed-bar close CROSSED UP through the intraday Tenkan
    (the EVENT: prior bar NOT above → this bar above) AND this bar's volume exceeds the window-mean
    baseline × vol_mult. `*_above` = (close > Tenkan) for that bar, or None when the reading is not
    yet available (Tenkan cold / no close). Returns (confirmed, reason).

    The CROSS (not a level): `curr_above and not prev_above`. An already-above bar
    (prev_above=True, curr_above=True) has NO edge → declines `no_reclaim_cross` (the silent-break
    this phase is designed to avoid)."""
    if bars_elapsed > window_bars:
        return False, "window_closed"            # SG5 — confirm window elapsed, drop the candidate
    if curr_above is None:
        return False, "warming"                  # Tenkan cold / no completed close yet → defer
    if prev_above is None:
        return False, "no_prior_bar"             # need a prior completed bar to detect the cross edge
    if not (curr_above and not prev_above):
        return False, "no_reclaim_cross"         # NOT the upward cross (already-above, or below)
    if vol_mean is None or vol_mean <= 0.0:
        return False, "no_vol_baseline"          # no volume baseline yet → can't gate volume
    if curr_vol <= vol_mean * vol_mult:
        return False, "weak_volume"              # no volume expansion → no conviction
    return True, "confirmed"


def _window_mean(window: Any) -> float | None:
    """Mean of a RollingWindow[float] (or a fake exposing .count + [i]); None if empty."""
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
    PROVIDES_DOWNSTREAM = ["sized_orders"]  # GATES the injected candidate stubs in place

    # ADR D5: two swept axes — the volume-expansion multiple + the confirm-window length. The
    # reclaim CROSS is a structural invariant (not a knob).
    COMPLEXITY = ComplexityDecl(
        free_params=2,
        note="vol_mult (volume-expansion ceiling) + window_bars (confirm window length).",
    )

    @dataclass(slots=True)
    class Params:
        vol_mult: float = 1.5       # this-bar volume must exceed window-mean × this (expansion)
        window_bars: int = 24       # confirm window in completed 5-min bars (≈2h; mass in open 30m)
        enabled: bool = True

        @classmethod
        def space(cls) -> ParamSpace:
            return ParamSpace(axes={"vol_mult": (1.3, 1.5, 2.0), "window_bars": (12, 24, 36)})

    def __init__(self, params: "BctIntradayConfirm.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        qc = ctx.qc
        active_by_lower = {s.value.lower(): s for s in getattr(qc, "_active", set())}
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
                kept.append(intent)  # confirmed earlier this session → flows to entry (re-fire safe)
                continue
            if cs["expired"]:
                continue  # window already closed for this candidate → dropped (SG5)
            sym = active_by_lower.get(tk.lower())
            st = intraday.get(sym) if sym is not None else None
            if st is None:
                reasons["no_feed"] = reasons.get("no_feed", 0) + 1
                continue  # no intraday feed this tick → defer (drop the stub, no fire)
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
                cs["prev_above"] = curr_above  # advance the cross edge-tracker on a valid reading
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
            blocked=False,  # entry_selection gates candidates, never blocks the bar
            reason=f"intraday-confirm: confirmed {confirmed}, kept {len(kept)} {reasons}",
            facts={"confirmed": confirmed, "kept": len(kept),
                   **{f"reason_{k}": v for k, v in reasons.items()}},
            metrics={},
        )

    @property
    def version_marker(self) -> str:
        return "bct_intraday_confirm_v1"
