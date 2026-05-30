"""Sample shared helper — proves transitive-import closure (phase imports this)."""
from __future__ import annotations


def threshold_ok(value: float, minimum: float) -> bool:
    return value >= minimum
