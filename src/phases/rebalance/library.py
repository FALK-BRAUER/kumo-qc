"""Catalog of sweepable rebalance phases."""
from __future__ import annotations

from phases.rebalance.industry_warmup.industry_warmup import IndustryWarmup

REBALANCE_PHASES = (IndustryWarmup,)
