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

# THE canonical 6 validation windows (Falk-locked 2026-06-03). RECENT-regime quarterly panel,
# equal-size so all 6 finish ~same wall-clock in parallel. Supersedes the old 2020-2024 default
# (which never matched what we actually validate on — a real config bug). w5/w6 OVERLAP BY DESIGN
# (2026 Q1 and Feb-Apr 2026) — Falk wants denser coverage of the recent 2026 regime, so the panel is
# NOT required to be non-overlapping (the old "non-overlapping" assumption is RETIRED; the validator
# enforces only count==6 + unique names). Warmup coverage confirmed: w1 (Jan-2025) warms 560d back to
# ~mid-2023 (the FY2025 panel ran that), w5/w6 (2026) warm to ~2024 — all locally runnable (only
# pre-2023 was the gap that killed FY2024-OOS). Daily data extends to 2026-05-08.
SIX_WINDOWS: tuple[Window, ...] = (
    Window(name="w1_2025q1", start="2025-01-01", end="2025-03-31"),
    Window(name="w2_2025q2", start="2025-04-01", end="2025-06-30"),
    Window(name="w3_2025q3", start="2025-07-01", end="2025-09-30"),
    Window(name="w4_2025q4", start="2025-10-01", end="2025-12-31"),
    Window(name="w5_2026q1", start="2026-01-01", end="2026-03-31"),
    Window(name="w6_2026_feb_apr", start="2026-02-01", end="2026-04-30"),
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
