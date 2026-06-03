"""Entry-timing library catalog (ADR D3 — FIRST catalog for the entry_timing kind).

Mirrors the signal catalog (phases/signal/library.py — the #228 template): the entry_timing kind
exposes its `ENTRY_TIMING_PHASES` tuple of DIRECT CLASS REFERENCES — the canonical type-checked
enumeration a sweep/discovery runner (#214) selects from:

    ENTRY_TIMING_PHASES: tuple[type[BasePhase], ...] = (MarketOnOpenEntry,)

Why a typed tuple of class refs (NOT a string registry): see phases/entry_selection/library.py —
the same ADR D3 rationale (mypy membership, no runtime KeyError, sweep reads space()/COMPLEXITY
without constructing). Strategy WIRING uses explicit Slot(...); this is DISCOVERY/SWEEP only.

Membership rule: an entry_timing impl lands here when merged-correct. Phase-2 variants
(BuyStopEntry #149, LimitPullbackEntry) append here as they graduate.
"""
from __future__ import annotations

from engine.base import BasePhase
from phases.entry_timing.confirmed_market_entry.confirmed_market_entry import ConfirmedMarketEntry
from phases.entry_timing.market_on_open_entry.market_on_open_entry import MarketOnOpenEntry

# MarketOnOpenEntry = the DAILY/fixture baseline (next-open MOO); ConfirmedMarketEntry = the #270
# INTRADAY confirmed-market entry (fire now at confirm). Mutually exclusive in a wired config
# (entry_timing instances share one clock — engine _phase_clock). champion_intraday wires
# ConfirmedMarketEntry; the catalog lists both (discovery/sweep only).
ENTRY_TIMING_PHASES: tuple[type[BasePhase], ...] = (MarketOnOpenEntry, ConfirmedMarketEntry)
