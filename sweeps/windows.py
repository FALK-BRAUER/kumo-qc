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
    # 2026 windows: NOT locally runnable — the local substrate has no 2026 coarse-universe or minute
    # feed (verified #338-ws3: w5 fails loud with #261-5 'empty coarse feed 2026-01-03'). They stay
    # in the canonical panel (Falk-locked) for CLOUD / a future 2026 backfill; LOCAL sweeps skip them.
    Window(name="w5_2026q1", start="2026-01-01", end="2026-03-31", runnable_locally=False),
    Window(name="w6_2026_feb_apr", start="2026-02-01", end="2026-04-30", runnable_locally=False),
)

MANDATORY_WINDOW_COUNT = 6


def local_runnable_windows(windows: Sequence[Window] = SIX_WINDOWS) -> tuple[Window, ...]:
    """The subset of `windows` whose data is available LOCALLY (runnable_locally). Local sweeps run
    these + log the skipped ones — graceful, never a crash on a true data outage (#338-ws3). Cloud /
    a future 2026 backfill runs the full canonical panel. Returns windows in their original order."""
    runnable = tuple(w for w in windows if w.runnable_locally)
    skipped = [w.name for w in windows if not w.runnable_locally]
    if skipped:
        print(f"[windows] LOCAL: running {len(runnable)}/{len(windows)} windows; "
              f"skipped (no local data, cloud/backfill-pending): {skipped}")
    return runnable


class WindowPanelError(ValueError):
    """Raised when a sweep is run with fewer than the mandatory 6 windows (D5.1 guard)."""


def validate_window_panel(windows: Sequence[Window], *, min_windows: int = MANDATORY_WINDOW_COUNT) -> None:
    """Refuse a panel that violates the no-single-number mandate.

    The runner enforces the distribution-not-point-estimate invariant at the seam: a panel
    with fewer than `min_windows` windows, or duplicate window names, is rejected loud rather
    than silently producing a thin/peaky result. `min_windows` defaults to the canonical 6 (cloud /
    full panel); a LOCAL sweep on the data-runnable subset passes the runnable count explicitly
    (#338-ws3: the 2026 windows have no local data — the 4 quarters are still a distribution, NOT a
    point estimate). It must never be set below 2 (that would permit a single-window point estimate).
    """
    if min_windows < 2:
        raise WindowPanelError(
            f"min_windows={min_windows} would permit a point estimate; the floor is 2 (D5.1)."
        )
    if len(windows) < min_windows:
        raise WindowPanelError(
            f"window panel has {len(windows)} windows; the required minimum is "
            f"{min_windows} (ADR D5.1: no single-number results). "
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
