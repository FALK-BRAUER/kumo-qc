"""6-window runner tests (#214 component 3). All on the mock runner. ZERO real backtest."""
from __future__ import annotations

import pytest

from sweeps.types import ResultMetrics, Window
from sweeps.windows import (
    MANDATORY_WINDOW_COUNT,
    SIX_WINDOWS,
    WindowPanelError,
    run_config_over_windows,
    validate_window_panel,
)
from sweeps.enumerate import enumerate_phase
from tests.sweeps.conftest import TwoAxisPhase, constant_runner, make_runner


def test_six_windows_panel_is_six_and_unique() -> None:
    assert len(SIX_WINDOWS) == MANDATORY_WINDOW_COUNT == 6
    names = [w.name for w in SIX_WINDOWS]
    assert len(set(names)) == 6
    validate_window_panel(SIX_WINDOWS)  # does not raise


def test_validate_rejects_fewer_than_six() -> None:
    with pytest.raises(WindowPanelError, match="mandatory minimum"):
        validate_window_panel(SIX_WINDOWS[:5])


def test_validate_rejects_duplicate_window_names() -> None:
    dup = (*SIX_WINDOWS[:5], Window(name=SIX_WINDOWS[0].name, start="x", end="y"))
    with pytest.raises(WindowPanelError, match="duplicate"):
        validate_window_panel(dup)


def test_run_config_over_windows_calls_primitive_per_window() -> None:
    cfg = enumerate_phase(TwoAxisPhase)[0]  # type: ignore[arg-type]
    calls: list[str] = []

    def runner(config, window):  # type: ignore[no-untyped-def]
        calls.append(window.name)
        return ResultMetrics(sharpe=1.0, ret_pct=10.0, dd_pct=5.0, orders=3)

    run = run_config_over_windows(cfg, runner)
    assert calls == [w.name for w in SIX_WINDOWS]
    assert len(run.window_results) == 6
    assert run.config is cfg


def test_run_config_collates_in_window_order() -> None:
    cfg = enumerate_phase(TwoAxisPhase)[0]  # type: ignore[arg-type]
    table = {
        (cfg.config_hash, w.name): ResultMetrics(sharpe=float(i), ret_pct=0.0, dd_pct=0.0, orders=i)
        for i, w in enumerate(SIX_WINDOWS)
    }
    run = run_config_over_windows(cfg, make_runner(table))
    # window_results carry the panel order, sharpe == window index.
    assert [wr.window.name for wr in run.window_results] == [w.name for w in SIX_WINDOWS]
    assert [wr.metrics.sharpe for wr in run.window_results] == [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]
