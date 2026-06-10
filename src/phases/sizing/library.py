"""Sizing-phase library catalog (ADR D3 — FIRST catalog for the sizing kind).

Mirrors the signal catalog (phases/signal/library.py — the #228 template) and the
entry_selection catalog (#253): every phase KIND exposes a `<KIND>_PHASES` tuple of DIRECT
CLASS REFERENCES — the canonical, type-checked enumeration a sweep/discovery runner (#214)
selects from for that kind:

    SIZING_PHASES: tuple[type[BasePhase], ...] = (FlatPctHeatcap, ScoreTierHeatcap, RankAwareHeatcap)

Why a typed tuple of class refs (NOT a string registry):
  - Conforms to CONVENTIONS.md "DIRECT CLASS REFERENCES, not strings". A registry may exist
    ONLY as a sweep-discovery catalog, and even then it holds classes, not name strings.
  - mypy --strict checks membership at the call site; a renamed/removed phase is a compile error
    here, not a runtime KeyError mid-sweep.
  - A sweep runner enumerates the tuple, reads each `.Params.space()` for the axes and
    `.COMPLEXITY` for the overfitting penalty — without constructing the phase or wiring a
    StrategyConfig. Strategy WIRING still uses explicit Slot(impl=..., params=...); this catalog
    is DISCOVERY/SWEEP only, never runtime phase resolution.

Membership rule: a sizing impl lands here when it is merged-correct (tests + header + charter) —
independent of whether it beats the baseline.
  - FlatPctHeatcap: the champion-asis sizer (flat position_pct + committed-cash heat-cap; ignores
    the X/4 entry-confirm score).
  - ScoreTierHeatcap: the score-aware sizer — the published X/4 BINDS via the methodology tiers
    (4/4 full . 3/4 75% . 2/4 50% . <2 no-entry), COMPOSED WITH the same heat-cap.
  - RankAwareHeatcap: the opt-in scanner-rank sizer — LambdaMART rank buckets scale the per-name
    target, COMPOSED WITH the same heat-cap.
"""
from __future__ import annotations

from engine.base import BasePhase
from phases.sizing.flat_pct_heatcap.flat_pct_heatcap import FlatPctHeatcap
from phases.sizing.rank_aware_heatcap.rank_aware_heatcap import RankAwareHeatcap
from phases.sizing.score_tier_heatcap.score_tier_heatcap import ScoreTierHeatcap

SIZING_PHASES: tuple[type[BasePhase], ...] = (FlatPctHeatcap, ScoreTierHeatcap, RankAwareHeatcap)
