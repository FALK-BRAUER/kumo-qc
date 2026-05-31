"""Entry-selection library catalog (ADR D3 — FIRST catalog for the entry_selection kind).

Mirrors the signal catalog (phases/signal/library.py — the #228 template): every phase KIND
exposes a `<KIND>_PHASES` tuple of DIRECT CLASS REFERENCES, the canonical type-checked
enumeration a sweep/discovery runner (#214) selects from for that kind:

    ENTRY_SELECTION_PHASES: tuple[type[BasePhase], ...] = (BctEntryConfirm,)

Why a typed tuple of class refs (NOT a string registry):
  - Conforms to CONVENTIONS.md "DIRECT CLASS REFERENCES, not strings". A registry may exist
    ONLY as a sweep-discovery catalog, and even then it holds classes, not name strings.
  - mypy --strict checks membership at the call site; a renamed/removed phase is a compile error
    here, not a runtime KeyError mid-sweep.
  - A sweep runner enumerates the tuple, reads each `.Params.space()` for the axes and
    `.COMPLEXITY` for the overfitting penalty — without constructing the phase or wiring a
    StrategyConfig. Strategy WIRING still uses explicit Slot(impl=..., params=...); this catalog
    is DISCOVERY/SWEEP only, never runtime phase resolution.

Membership rule: an entry_selection impl lands here when it is merged-correct (tests + header +
charter) — independent of whether it beats the baseline. Phase-2 variants (#148 ResistanceZone,
#150 RiskReward, #64 DojiDelay) append here as they graduate.
"""
from __future__ import annotations

from engine.base import BasePhase
from phases.entry_selection.bct_entry_confirm.bct_entry_confirm import BctEntryConfirm

ENTRY_SELECTION_PHASES: tuple[type[BasePhase], ...] = (BctEntryConfirm,)
