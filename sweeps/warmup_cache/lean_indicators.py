"""#332 — re-export of the LEAN-faithful indicator ports. SINGLE SOURCE OF TRUTH = runtime.
lean_indicators (in src/, so the dist + lean_entry import the SAME logic the cache uses — eliminates
the two-impl drift hazard; the live continuous-weekly fix + the cache share one weekly implementation).
This shim keeps `sweeps.warmup_cache.lean_indicators` imports working for the cache builder + tests."""
from __future__ import annotations

from runtime.lean_indicators import (  # noqa: F401
    ADX,
    SMA,
    Delay,
    Ichimoku,
    Maximum,
    Minimum,
    RateOfChange,
    WeeklyIchimokuAsOf,
    monday_of_week,
)

# Explicit re-export (mypy --strict no-implicit-reexport): this shim's whole purpose is to re-expose
# runtime.lean_indicators under the sweeps.warmup_cache namespace for the cache builder + tests.
__all__ = [
    "ADX", "SMA", "Delay", "Ichimoku", "Maximum", "Minimum",
    "RateOfChange", "WeeklyIchimokuAsOf", "monday_of_week",
]
