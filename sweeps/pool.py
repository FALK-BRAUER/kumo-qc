"""Isolated parallel pool (#214 component 2) — run N configs concurrently, capped + isolated.

Runs many configs over the 6-window panel with BOUNDED concurrency. Each (config, window)
backtest is ISOLATED: the run-a-config primitive is INJECTED (the RunConfig Protocol), so
the pool never touches LEAN itself — it only schedules calls to that primitive. Tests inject
a deterministic mock (ZERO real backtest / cloud spend); the real adapter (which would give
each run a unique LEAN project / local-id / cache dir + symlinked data + marker verification,
per sweeps/README) is integration-flagged and never unit-run.

Isolation mechanism (the design judgement):
  - The pool unit is ONE (config, window) call to the injected primitive. There is NO shared
    mutable state between units: each call receives only its immutable SweepConfig + Window
    and returns an immutable ResultMetrics. The pool collects results into per-config buckets
    keyed by config_hash, never a shared accumulator the workers write concurrently.
  - Concurrency is capped by `max_workers` (a thread pool — the real primitive is
    IO/subprocess-bound on LEAN, so threads are right; the mock is pure + thread-safe).
  - Collation is DETERMINISTIC: regardless of completion order, results are re-sorted into
    (config order, window order) before building ConfigRuns. Two runs of the same grid with
    the same primitive produce byte-identical ConfigRun ordering.

The real adapter's per-run isolation (unique project id, cache, data symlink, marker check)
lives BEHIND the RunConfig Protocol — the pool's contract is "isolated unit in, metrics out",
and the adapter satisfies it. The pool guarantees no cross-unit state; the adapter guarantees
no cross-unit filesystem/cloud collision.
"""
from __future__ import annotations

from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from sweeps.types import (
    ConfigRun,
    ResultMetrics,
    RunConfig,
    SweepConfig,
    Window,
    WindowResult,
)
from sweeps.windows import MANDATORY_WINDOW_COUNT, SIX_WINDOWS, validate_window_panel

DEFAULT_MAX_WORKERS = 4
"""Default concurrency cap. The real LEAN adapter is subprocess-bound; keep modest to avoid
swamping the host / cloud node budget. Tunable per sweep."""


@dataclass(frozen=True, slots=True)
class _Unit:
    """One isolated work unit: a (config-index, config, window) triple. Immutable."""

    config_index: int
    config: SweepConfig
    window: Window


def run_pool(
    configs: Sequence[SweepConfig],
    run: RunConfig,
    *,
    windows: Sequence[Window] = SIX_WINDOWS,
    max_workers: int = DEFAULT_MAX_WORKERS,
    min_windows: int = MANDATORY_WINDOW_COUNT,
) -> list[ConfigRun]:
    """Run every config over every window via the injected primitive, capped + isolated.

    Returns one ConfigRun per input config, in INPUT ORDER, each with its window_results in
    WINDOW ORDER — deterministic regardless of thread scheduling. Validates the no-single-number
    mandate (>= `min_windows`, default the canonical 6) before scheduling any work; a LOCAL sweep on
    the data-runnable subset passes the runnable count (#338-ws3 — still a distribution, not a point).

    Isolation: each unit is an independent call to `run(config, window)` with no shared
    mutable state. Concurrency is capped at `max_workers`. The mock primitive in tests is
    pure; the real adapter isolates LEAN runs behind the same Protocol.
    """
    validate_window_panel(windows, min_windows=min_windows)
    if max_workers < 1:
        raise ValueError(f"max_workers must be >= 1, got {max_workers}")

    units = [
        _Unit(config_index=ci, config=cfg, window=w)
        for ci, cfg in enumerate(configs)
        for w in windows
    ]
    if not units:
        return []

    # Buckets keyed by config index; each worker writes ONLY its own (index, window) cell via
    # the returned tuple — no shared-state writes inside workers (the result is collated after
    # all futures resolve, so there is no concurrent mutation to race on).
    def _do(unit: _Unit) -> tuple[int, Window, ResultMetrics]:
        metrics = run(unit.config, unit.window)
        return unit.config_index, unit.window, metrics

    collected: list[tuple[int, Window, ResultMetrics]] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for result in executor.map(_do, units):
            collected.append(result)

    # Deterministic collation: group by config index, order window_results by the panel order.
    window_order = {w.name: i for i, w in enumerate(windows)}
    by_config: dict[int, list[tuple[int, Window, ResultMetrics]]] = {}
    for ci, window, metrics in collected:
        by_config.setdefault(ci, []).append((ci, window, metrics))

    runs: list[ConfigRun] = []
    for ci, cfg in enumerate(configs):
        cells = by_config.get(ci, [])
        cells.sort(key=lambda c: window_order[c[1].name])
        window_results = tuple(
            WindowResult(window=w, metrics=m) for _, w, m in cells
        )
        runs.append(ConfigRun(config=cfg, window_results=window_results))
    return runs
