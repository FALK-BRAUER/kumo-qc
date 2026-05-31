"""Aggregation (#214 component 4) — per-metric distribution across the 6 windows.

ADR-0001 D5.1: a config's output is a DISTRIBUTION, not a number. This module reduces a
ConfigRun's per-window ResultMetrics into the summary statistics the scorer needs: mean,
std (population), min, max, and the "worst" value per metric. "Worst" is direction-aware:
for Sharpe/Ret% higher is better so worst = min; for DD% (a drawdown magnitude, lower is
better) worst = max. The scorer ranks on these distributions, never a single window.

Pure functions, no numpy dependency (std is population std, computed directly) — keeps the
runner importable in any context and avoids pinning a numeric stack the sweep mechanics
don't otherwise need.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from sweeps.types import ConfigRun, SweepConfig


@dataclass(frozen=True, slots=True)
class MetricStats:
    """Distribution summary of one metric across the windows.

    `mean`/`std` are population statistics; `min`/`max` the extremes; `worst` the
    direction-aware worst case (min for higher-is-better, max for drawdown). n = window
    count (the distribution's sample size — must be the mandatory 6 for a valid sweep row).
    """

    mean: float
    std: float
    minimum: float
    maximum: float
    worst: float
    n: int


@dataclass(frozen=True, slots=True)
class AggregateResult:
    """All per-metric distributions for one config, ready for scoring + the leaderboard."""

    config: SweepConfig
    sharpe: MetricStats
    ret_pct: MetricStats
    dd_pct: MetricStats
    orders: MetricStats
    n_windows: int


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def _std(values: Sequence[float]) -> float:
    """Population standard deviation. 0.0 for a single value (no spread)."""
    if len(values) < 2:
        return 0.0
    mu = _mean(values)
    var = sum((v - mu) ** 2 for v in values) / len(values)
    return math.sqrt(var)


def _stats(values: Sequence[float], *, higher_is_better: bool) -> MetricStats:
    lo = min(values)
    hi = max(values)
    worst = lo if higher_is_better else hi
    return MetricStats(
        mean=_mean(values),
        std=_std(values),
        minimum=lo,
        maximum=hi,
        worst=worst,
        n=len(values),
    )


def aggregate(run: ConfigRun) -> AggregateResult:
    """Reduce a config's per-window results into per-metric distributions.

    Sharpe + Ret% higher-is-better (worst = min); DD% is a drawdown magnitude where lower is
    better (worst = max). Order count is summarised for visibility (worst = min, arbitrary —
    it is not a quality metric, just reported).
    """
    if not run.window_results:
        raise ValueError("cannot aggregate a ConfigRun with no window results")

    sharpe = [wr.metrics.sharpe for wr in run.window_results]
    ret = [wr.metrics.ret_pct for wr in run.window_results]
    dd = [wr.metrics.dd_pct for wr in run.window_results]
    orders = [float(wr.metrics.orders) for wr in run.window_results]

    return AggregateResult(
        config=run.config,
        sharpe=_stats(sharpe, higher_is_better=True),
        ret_pct=_stats(ret, higher_is_better=True),
        dd_pct=_stats(dd, higher_is_better=False),
        orders=_stats(orders, higher_is_better=True),
        n_windows=len(run.window_results),
    )
