"""Isolated parallel pool tests (#214 component 2). Mock runner, ZERO real backtest.

Asserts: all configs x all windows run; capped concurrency respected; isolation (no shared
mutable state — concurrent runs of a stateful-looking mock stay correct); deterministic
collation regardless of thread completion order.
"""
from __future__ import annotations

import threading
import time

import pytest

from sweeps.enumerate import enumerate_catalog
from sweeps.pool import run_pool
from sweeps.types import ResultMetrics, SweepConfig, Window
from sweeps.windows import SIX_WINDOWS
from tests.sweeps.conftest import MOCK_CATALOG, constant_runner, make_runner


def _full_table(configs: list[SweepConfig]) -> dict[tuple[str, str], ResultMetrics]:
    # Deterministic per-cell metrics: sharpe encodes (config index, window index).
    table: dict[tuple[str, str], ResultMetrics] = {}
    for ci, cfg in enumerate(configs):
        for wi, w in enumerate(SIX_WINDOWS):
            table[(cfg.config_hash, w.name)] = ResultMetrics(
                sharpe=ci * 10.0 + wi, ret_pct=float(ci), dd_pct=float(wi), orders=ci + wi
            )
    return table


def test_pool_runs_all_configs_over_all_windows() -> None:
    configs = enumerate_catalog(MOCK_CATALOG)  # type: ignore[arg-type]  # 9 configs
    runs = run_pool(configs, make_runner(_full_table(configs)), max_workers=4)
    assert len(runs) == len(configs)
    assert all(len(r.window_results) == 6 for r in runs)


def test_pool_preserves_input_config_order() -> None:
    configs = enumerate_catalog(MOCK_CATALOG)  # type: ignore[arg-type]
    runs = run_pool(configs, make_runner(_full_table(configs)), max_workers=4)
    assert [r.config.config_hash for r in runs] == [c.config_hash for c in configs]


def test_pool_collation_is_deterministic_in_window_order() -> None:
    configs = enumerate_catalog(MOCK_CATALOG)  # type: ignore[arg-type]
    table = _full_table(configs)
    runs = run_pool(configs, make_runner(table), max_workers=8)
    for ci, r in enumerate(runs):
        # window_results in panel order; sharpe == ci*10 + window-index.
        assert [wr.window.name for wr in r.window_results] == [w.name for w in SIX_WINDOWS]
        assert [wr.metrics.sharpe for wr in r.window_results] == [ci * 10.0 + wi for wi in range(6)]


def test_pool_two_runs_identical_output() -> None:
    configs = enumerate_catalog(MOCK_CATALOG)  # type: ignore[arg-type]
    table = _full_table(configs)
    a = run_pool(configs, make_runner(table), max_workers=4)
    b = run_pool(configs, make_runner(table), max_workers=8)
    # Same config order + same per-window metrics regardless of worker count.
    assert [r.config.config_hash for r in a] == [r.config.config_hash for r in b]
    for ra, rb in zip(a, b, strict=True):
        assert [wr.metrics.sharpe for wr in ra.window_results] == [
            wr.metrics.sharpe for wr in rb.window_results
        ]


def test_pool_respects_concurrency_cap() -> None:
    # A runner that records peak concurrency; assert it never exceeds max_workers.
    configs = enumerate_catalog(MOCK_CATALOG)  # type: ignore[arg-type]
    lock = threading.Lock()
    state = {"active": 0, "peak": 0}

    def runner(config: SweepConfig, window: Window) -> ResultMetrics:
        with lock:
            state["active"] += 1
            state["peak"] = max(state["peak"], state["active"])
        time.sleep(0.005)  # widen the window for overlap
        with lock:
            state["active"] -= 1
        return ResultMetrics(sharpe=1.0, ret_pct=1.0, dd_pct=1.0, orders=1)

    run_pool(configs, runner, max_workers=3)
    assert state["peak"] <= 3
    assert state["peak"] >= 1


def test_pool_isolation_no_cross_unit_state_bleed() -> None:
    # Each unit gets ONLY its own config+window; a runner keyed on (config,window) returns
    # the right cell even under concurrency -> no bleed.
    configs = enumerate_catalog(MOCK_CATALOG)  # type: ignore[arg-type]
    table = _full_table(configs)
    runs = run_pool(configs, make_runner(table), max_workers=8)
    for ci, r in enumerate(runs):
        for wi, wr in enumerate(r.window_results):
            assert wr.metrics.sharpe == ci * 10.0 + wi  # exact expected cell


def test_pool_empty_configs() -> None:
    assert run_pool([], constant_runner(ResultMetrics(1, 1, 1, 1)), max_workers=2) == []


def test_pool_rejects_bad_worker_count() -> None:
    configs = enumerate_catalog(MOCK_CATALOG)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="max_workers"):
        run_pool(configs, constant_runner(ResultMetrics(1, 1, 1, 1)), max_workers=0)


def test_pool_enforces_six_window_mandate() -> None:
    from sweeps.windows import WindowPanelError

    configs = enumerate_catalog(MOCK_CATALOG)  # type: ignore[arg-type]
    with pytest.raises(WindowPanelError):
        run_pool(configs, constant_runner(ResultMetrics(1, 1, 1, 1)), windows=SIX_WINDOWS[:3])
