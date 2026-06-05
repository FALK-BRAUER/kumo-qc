"""Shared PROVER-STATE — the single source of truth for "has this held position PROVED (a potential
monster)?" used by every prover-gated/asymmetric phase (exit-model loser-cut, #379 profit-take, any
future TR-style lever). ONE state object on `qc._prover_state`, both phases READ it — never a parallel
re-implementation (HQ #379-B flag 1: a re-impl would re-introduce the two already-fixed bugs —
prove-on-close-only + GC-erases-flag-on-cold-bar — AND could DISAGREE with another phase on "proved"
[one exempts a monster, the other clips it = contradiction]).

PROVED = the position's MAX FAVORABLE EXCURSION reached ≥ entry × (1 + prove_pct) (default +5%) at any
point since entry. Prove on max(close, bar-HIGH) — a fast monster that gapped/ran >+5% intraday but
closed below it STILL proves (a close-only prove would false-exempt-miss an intraday runner). The flag
is STICKY (once proved, stays proved until the position closes), SURVIVES cold-data bars (an invested
position stays tracked even on a missing-indicator bar — never erase the flag), reset on re-entry
(entry_date change), and GC'd when the position closes (no stale flag leaking into a re-entry).

Idempotent within a bar: max-tracking + GC are monotonic, so calling update_prover_state() from
multiple phases the same bar is harmless. Each phase calls it (cheap) then reads is_proved().
"""
from __future__ import annotations

from typing import Any

_PROVE_PCT_DEFAULT = 0.05  # +5% MFE = PROVED (a potential monster) → exempt from loser-cut / eligible for trail


def _state(qc: Any) -> dict:
    st = getattr(qc, "_prover_state", None)
    if st is None:
        qc._prover_state = {}
        st = qc._prover_state
    return st


def update_prover_state(qc: Any, prove_pct: float = _PROVE_PCT_DEFAULT) -> None:
    """Refresh qc._prover_state for every invested position: seed/reset on entry, set proved on a
    +prove_pct MFE (close or high), keep proved sticky, survive cold bars, GC closed positions. Cheap;
    call once per phase that gates on the prover state (idempotent within a bar)."""
    st = _state(qc)
    meta = getattr(qc, "_position_meta", {})
    live: set = set()
    for sym, holding in list(qc.portfolio.items()):
        if not getattr(holding, "invested", False):
            continue
        live.add(sym)  # invested → stays tracked even on a cold-data bar (never erase the proved flag)
        m = meta.get(sym)
        if not m or "entry_price" not in m:
            continue
        try:
            entry = float(m["entry_price"])
            close = float(qc.securities[sym].close)
            high = float(getattr(qc.securities[sym], "high", close) or close)
        except (KeyError, AttributeError, TypeError, ValueError):
            continue
        if entry <= 0.0:
            continue
        entry_date = m.get("entry_date")
        rec = st.get(sym)
        if rec is None or rec["entry_date"] != entry_date:   # new / re-entered → reset
            st[sym] = rec = {"entry_date": entry_date, "proved": False}
        if max(close, high) >= entry * (1.0 + prove_pct):     # MFE prove (close OR intraday high)
            rec["proved"] = True
    for s in [s for s in st if s not in live]:               # GC closed (no stale flag into a re-entry)
        st.pop(s, None)


def is_proved(qc: Any, sym: Any) -> bool:
    """True if `sym` has PROVED (≥+prove_pct MFE since entry). Read after update_prover_state()."""
    rec = _state(qc).get(sym)
    return bool(rec and rec.get("proved"))
