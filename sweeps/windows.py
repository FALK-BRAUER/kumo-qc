"""Validation windows (#214 component 3) — the mandatory 6-window runner.

ADR-0001 D5.1: NO single-number results. Every config's output is the DISTRIBUTION across
the mandatory 6 windows, never one backtest. This module owns the 6 windows and the
per-config runner that drives the INJECTED run-a-config primitive over all of them.

The windows are out-of-sample slices spanning the available history (the charter's
"out-of-window validation" invariant, ADR D5.6). They are defined here as the single source
of truth; a sweep MAY override them (e.g. a shorter parity window) but the default IS the
6-window panel — running fewer is a charter violation the runner refuses.

The runner is phase-agnostic and compute-free here: it only calls the injected RunConfig
Protocol. In tests that primitive is a deterministic mock (ZERO real LEAN). The 6 calls per
config are independent → the parallel pool (pool.py) is what actually fans them out; this
module defines the sequential reference + the window panel.
"""
from __future__ import annotations

from collections.abc import Sequence

from sweeps.types import ConfigRun, RunConfig, SweepConfig, Window, WindowResult

# The mandatory 6 validation windows (ADR D5.1). Non-overlapping OOS slices across the
# available daily history. These are the canonical panel; a sweep that runs fewer is a
# charter violation. Dates are ISO; the real run-a-config adapter maps them to LEAN
# start/end. (Exact spans are a config knob, not logic — six windows is the invariant.)
SIX_WINDOWS: tuple[Window, ...] = (
    Window(name="w1_2020h1", start="2020-01-01", end="2020-06-30"),
    Window(name="w2_2020h2", start="2020-07-01", end="2020-12-31"),
    Window(name="w3_2021", start="2021-01-01", end="2021-12-31"),
    Window(name="w4_2022", start="2022-01-01", end="2022-12-31"),
    Window(name="w5_2023", start="2023-01-01", end="2023-12-31"),
    Window(name="w6_2024", start="2024-01-01", end="2024-12-31"),
)

MANDATORY_WINDOW_COUNT = 6


class WindowPanelError(ValueError):
    """Raised when a sweep is run with fewer than the mandatory 6 windows (D5.1 guard)."""


def validate_window_panel(windows: Sequence[Window]) -> None:
    """Refuse a panel that violates the 6-window mandate (no single-number results).

    The runner enforces the distribution-not-point-estimate invariant at the seam: a panel
    with fewer than 6 windows, or duplicate window names, is rejected loud rather than
    silently producing a thin/peaky result.
    """
    if len(windows) < MANDATORY_WINDOW_COUNT:
        raise WindowPanelError(
            f"window panel has {len(windows)} windows; the mandatory minimum is "
            f"{MANDATORY_WINDOW_COUNT} (ADR D5.1: no single-number results). "
            "Running fewer windows produces a point estimate, not a robustness distribution."
        )
    names = [w.name for w in windows]
    if len(set(names)) != len(names):
        raise WindowPanelError(f"duplicate window names in panel: {names}")


def run_config_over_windows(
    config: SweepConfig,
    run: RunConfig,
    *,
    windows: Sequence[Window] = SIX_WINDOWS,
) -> ConfigRun:
    """Run ONE config over all windows via the injected primitive -> a ConfigRun.

    Sequential reference implementation (pool.py parallelises across configs). Validates the
    panel first (6-window mandate), then calls `run(config, window)` per window and collates
    the results in window order — deterministic regardless of how a parallel pool schedules
    them.
    """
    validate_window_panel(windows)
    results: list[WindowResult] = []
    for window in windows:
        metrics = run(config, window)
        results.append(WindowResult(window=window, metrics=metrics))
    return ConfigRun(config=config, window_results=tuple(results))
