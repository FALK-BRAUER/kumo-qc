"""Protective-stop library catalog (ADR D3 — FIRST catalog for the protective_stop kind).

The protective_stop kind (new pre-FIRE KNOWN_KIND, #276b-1/#290) sets `intent.protective_stop` on
the surviving sized entries so FIRE_ENTRIES places + ticket-tracks the broker-side GTC catastrophic
floor. Exposes `PROTECTIVE_STOP_PHASES` — DIRECT CLASS REFERENCES (see entry_selection/library.py
for the ADR D3 rationale: mypy membership, no runtime KeyError, sweep reads space()/COMPLEXITY).

Membership rule: a protective_stop impl lands here when merged-correct. The Epic-2 floor VARIANTS
(ATR-mult, swing-low) append here as they graduate — each a clean sweep axis (ADR D1: different
floor algorithm = new class, never a flag-branch of the daily-Kijun impl).
"""
from __future__ import annotations

from engine.base import BasePhase
from phases.protective_stop.kijun_protective_stop.kijun_protective_stop import KijunProtectiveStop

PROTECTIVE_STOP_PHASES: tuple[type[BasePhase], ...] = (KijunProtectiveStop,)
