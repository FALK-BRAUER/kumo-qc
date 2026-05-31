"""Signal-phase library catalog (ADR D3 — THE FIRST catalog, sets the enumeration pattern).

Every phase KIND exposes a `<KIND>_PHASES` tuple of DIRECT CLASS REFERENCES — the canonical,
type-checked enumeration of the impls a sweep/discovery runner may select for that kind. This
is the template every later kind copies (universe/regime/sizing/exit/entry_timing/...):

    SIGNAL_PHASES: tuple[type[BasePhase], ...] = (BctScoreFull,)

Why a typed tuple of class refs (NOT a string registry):
  - Conforms to CONVENTIONS.md "DIRECT CLASS REFERENCES, not strings". A registry may exist
    ONLY as a sweep-discovery catalog — and even then it holds classes, not name strings.
  - mypy --strict checks membership at the call site; a renamed/removed phase is a compile
    error here, not a runtime KeyError in a sweep three hours in.
  - A sweep runner enumerates `SIGNAL_PHASES`, reads each `.Params.space()` for the axes and
    `.COMPLEXITY` for the overfitting penalty — all without constructing the phase or wiring a
    StrategyConfig. Strategy WIRING still uses explicit Slot(impl=..., params=...) per
    CONVENTIONS; this catalog is for DISCOVERY/SWEEP only, never for runtime phase resolution.

Membership rule: a signal impl lands here when it is merged-correct (tests + header + charter)
— independent of whether it beats the champion. sample_bct (the config-only teaching fixture)
is deliberately EXCLUDED: it is not a real qualify impl and must never be sweep-selected.
"""
from __future__ import annotations

from engine.base import BasePhase
from phases.signal.bct_score_full.bct_score_full import BctScoreFull

SIGNAL_PHASES: tuple[type[BasePhase], ...] = (BctScoreFull,)
