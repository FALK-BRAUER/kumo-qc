"""`LocalLeanRun` (#214 A.3) — the real local run-a-config adapter (the fast filter).

Satisfies the `RunConfig` Protocol (`__call__ -> ResultMetrics`) and `RichRunConfig`
(`run_result -> RunResult`). Drives `lean backtest` in an ISOLATED project dir, parses the
result, marker-verifies, and FAILS LOUD on degraded data — it never returns a mirage metric.

Single code path (CLAUDE.md §Cloud/Local Parity): the LEAN result JSON and the cloud
statistics are parsed by the SAME `result_parse` module. Local is the harness that emulates
cloud; the only local-specific concern is filesystem isolation (per-run dir, data symlink,
unique local-id), which lives HERE behind the Protocol — the mechanics above never see it.

Isolation contract (one call = one isolated unit, per pool.py + sweeps/README):
  1. Build the dist closure for `config` into `runs/<config_hash>/<window>/` (throwaway,
     gitignored) via the injected `dist_builder` — never overwrites the tracked `dist/`.
  2. Symlink the read-only data substrate into the run dir (never copy).
  3. Inject START_DATE/END_DATE from `window` into main.py (the qc_v2_cloud _inject pattern).
  4. Run LEAN in that isolated project (injected `run_lean` — subprocess in prod).
  5. Marker-verify the executed code (fabrication guard) — RAISE on mismatch.
  6. Parse the result JSON -> RunResult.
  7. FAIL LOUD on degraded data (empty-warmup-coarse / outage) — RAISE, never score a mirage.

Testability: `dist_builder`, `run_lean`, and `find_result` are INJECTED callables. Unit
tests pass fakes that touch a temp FS + a fixture result JSON — ZERO real LEAN, ZERO Docker.
The prod defaults shell to the real `lean backtest`.
"""
from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sweeps.adapters.result_parse import parse_run_result
from sweeps.types import (
    DegradedDataError,
    MarkerMismatchError,
    ResultMetrics,
    ResultParseError,
    RunResult,
    SweepConfig,
    Window,
)

# Injected steps (defaults shell to the real toolchain; tests override with fakes).
DistBuilder = Callable[[SweepConfig, Window, Path], str]
"""Build the dist closure for `config`/`window` into the given run dir; return the expected
marker present in the deployed main.py (the readback check)."""
RunLean = Callable[[Path], int]
"""Run `lean backtest` in the given project dir; return the process exit code."""
FindResult = Callable[[Path], Path]
"""Locate the result JSON in the project's backtests/ output; raise if absent."""


def _default_find_result(project_dir: Path) -> Path:
    """Locate the LEAN result JSON: the newest backtests/<ts>/<id>.json (not order-events /
    summary / data-monitor). Raises ResultParseError if no run output exists (fail loud —
    a missing artifact is NOT a zero result)."""
    bt_root = project_dir / "backtests"
    if not bt_root.is_dir():
        raise ResultParseError(f"no backtests/ output under {project_dir} — LEAN did not run")
    runs = sorted((d for d in bt_root.iterdir() if d.is_dir()), key=lambda d: d.stat().st_mtime)
    for run_dir in reversed(runs):
        for js in sorted(run_dir.glob("*.json")):
            name = js.name
            if any(skip in name for skip in ("order-events", "-summary", "data-monitor")):
                continue
            return js
    raise ResultParseError(f"no result JSON under {bt_root} — LEAN produced no parseable output")


def _default_run_lean(project_dir: Path) -> int:
    """Shell to `lean backtest` with the host Docker fix (MEMORY: LEAN Docker host)."""
    env = dict(os.environ)
    env.setdefault("DOCKER_HOST", "unix:///Users/falk/.docker/run/docker.sock")
    proc = subprocess.run(
        ["lean", "backtest", str(project_dir)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    return proc.returncode


def _read_executed_marker(result_path: Path) -> str | None:
    """Read the executed-code marker from the run's code/main.py snapshot (the contamination
    guard, scripts/lean-bt.sh). Returns the main.py text, or None if the snapshot is absent."""
    code_main = result_path.parent / "code" / "main.py"
    if code_main.is_file():
        return code_main.read_text(encoding="utf-8")
    return None


@dataclass(frozen=True, slots=True)
class LocalLeanRun:
    """The real local run-a-config primitive. Integration-flagged; unit-tested on fixtures.

    `dist_builder` folds a SweepConfig's chosen impls+params into a throwaway dist closure
    in the per-run dir + injects the window. `runs_root` is the gitignored isolation root
    (`sweeps/runs/`). `marker_check=True` enforces the fabrication guard. `run_lean` /
    `find_result` are injectable for testing (defaults shell to the real toolchain)."""

    dist_builder: DistBuilder
    data_root: Path
    runs_root: Path
    marker_check: bool = True
    run_lean: RunLean = _default_run_lean
    find_result: FindResult = _default_find_result

    def _run_dir(self, config: SweepConfig, window: Window) -> Path:
        """The UNIQUE isolated project dir for this (config, window) — no cross-run collision."""
        return self.runs_root / config.config_hash / window.name

    def _symlink_data(self, run_dir: Path) -> None:
        """Symlink the read-only data substrate (never copy — MEMORY: worktree data symlink)."""
        link = run_dir / "data"
        if link.exists() or link.is_symlink():
            return
        link.symlink_to(self.data_root)

    def run_result(self, config: SweepConfig, window: Window) -> RunResult:
        """Run the isolated LEAN backtest and parse it into a full RunResult. RAISES on a
        marker mismatch (contamination), a degraded run (empty-warmup-coarse), or an
        unparseable/absent artifact — NEVER returns a mirage metric."""
        run_dir = self._run_dir(config, window)
        run_dir.mkdir(parents=True, exist_ok=True)

        expected_marker = self.dist_builder(config, window, run_dir)
        self._symlink_data(run_dir)

        rc = self.run_lean(run_dir)
        if rc != 0:
            raise ResultParseError(
                f"lean backtest exited {rc} for config {config.config_hash} window "
                f"{window.name} — a non-zero exit is a failed run, not a result"
            )

        result_path = self.find_result(run_dir)

        if self.marker_check:
            executed = _read_executed_marker(result_path)
            if executed is None:
                raise MarkerMismatchError(
                    f"no code/main.py snapshot beside {result_path} — cannot verify which "
                    f"code ran (fabrication guard); refusing the result"
                )
            if expected_marker and expected_marker not in executed:
                raise MarkerMismatchError(
                    f"marker '{expected_marker}' NOT in executed code/main.py for config "
                    f"{config.config_hash} — possible cross-run contamination; result rejected"
                )

        result: dict[str, Any] = json.loads(result_path.read_text(encoding="utf-8"))
        run_result = parse_run_result(result)
        if run_result.is_degraded:
            raise DegradedDataError(
                f"degraded run for config {config.config_hash} window {window.name}: "
                f"orders={run_result.metrics.orders} (empty-warmup-coarse / data outage) — "
                f"crashing rather than banking a mirage metric (G-DATA gate)"
            )
        return run_result

    def __call__(self, config: SweepConfig, window: Window) -> ResultMetrics:
        """The RunConfig Protocol surface: returns the leaderboard-facing metrics trio."""
        return self.run_result(config, window).metrics
