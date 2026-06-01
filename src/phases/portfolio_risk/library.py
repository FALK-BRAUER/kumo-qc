"""Portfolio-risk-phase library catalog (ADR D3 — FIRST catalog for the portfolio_risk kind).

Mirrors the sizing catalog (phases/sizing/library.py): the kind exposes a `PORTFOLIO_RISK_PHASES`
tuple of DIRECT CLASS REFERENCES — the canonical, type-checked enumeration a sweep/discovery
runner (#214) selects from. mypy verifies membership; strategy WIRING still uses explicit
Slot(impl=..., params=...). Discovery/sweep only, never runtime phase resolution.

  - GrossExposureCap (#181): the hard %-gross-exposure ceiling — the SAFETY floor that prevents
    over-leverage (the Pe 1.44x scar). Parameterized (max_gross_pct); #302 may modulate it.
"""
from __future__ import annotations

from engine.base import BasePhase
from phases.portfolio_risk.gross_exposure_cap.gross_exposure_cap import GrossExposureCap

PORTFOLIO_RISK_PHASES: tuple[type[BasePhase], ...] = (GrossExposureCap,)
