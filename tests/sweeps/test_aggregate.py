"""Aggregation tests (#214 component 4) — mean/std/worst on known per-window metrics."""
from __future__ import annotations

import math

import pytest

from sweeps.aggregate import aggregate
from sweeps.types import ConfigRun, PhaseChoice, ResultMetrics, SweepConfig, Window, WindowResult


def _config() -> SweepConfig:
    return SweepConfig(choices=(PhaseChoice("signal", "Mock", (("a", 1),), 1),))


def _run(sharpes: list[float], rets: list[float], dds: list[float], orders: list[int]) -> ConfigRun:
    wrs = tuple(
        WindowResult(
            window=Window(name=f"w{i}", start="", end=""),
            metrics=ResultMetrics(sharpe=s, ret_pct=r, dd_pct=d, orders=o),
        )
        for i, (s, r, d, o) in enumerate(zip(sharpes, rets, dds, orders, strict=True))
    )
    return ConfigRun(config=_config(), window_results=wrs)


def test_mean_std_correct_on_known_values() -> None:
    # sharpe = [2,4,4,4,5,5,7,9] -> mean 5, population std 2.0 (textbook example).
    run = _run(
        sharpes=[2, 4, 4, 4, 5, 5, 7, 9],
        rets=[0.0] * 8,
        dds=[0.0] * 8,
        orders=[0] * 8,
    )
    agg = aggregate(run)
    assert agg.sharpe.mean == pytest.approx(5.0)
    assert agg.sharpe.std == pytest.approx(2.0)
    assert agg.sharpe.n == 8


def test_worst_is_min_for_higher_is_better_metrics() -> None:
    run = _run(sharpes=[1.0, 3.0, 2.0], rets=[5.0, 1.0, 9.0], dds=[10.0, 5.0, 8.0], orders=[1, 2, 3])
    agg = aggregate(run)
    # Sharpe + Ret%: higher better -> worst = min.
    assert agg.sharpe.worst == 1.0
    assert agg.ret_pct.worst == 1.0
    assert agg.sharpe.minimum == 1.0
    assert agg.sharpe.maximum == 3.0


def test_worst_is_max_for_drawdown() -> None:
    # DD% lower is better -> worst = the LARGEST drawdown.
    run = _run(sharpes=[1, 1, 1], rets=[0, 0, 0], dds=[5.0, 12.0, 8.0], orders=[0, 0, 0])
    agg = aggregate(run)
    assert agg.dd_pct.worst == 12.0
    assert agg.dd_pct.maximum == 12.0


def test_std_zero_for_constant_metric() -> None:
    run = _run(sharpes=[3, 3, 3], rets=[0, 0, 0], dds=[0, 0, 0], orders=[0, 0, 0])
    agg = aggregate(run)
    assert agg.sharpe.std == 0.0
    assert agg.sharpe.mean == 3.0


def test_aggregate_rejects_empty_run() -> None:
    with pytest.raises(ValueError, match="no window results"):
        aggregate(ConfigRun(config=_config(), window_results=()))
