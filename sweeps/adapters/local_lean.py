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
import threading
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from sweeps.adapters.result_parse import parse_run_result
from sweeps.archive.config_serializer import serialize_config
from sweeps.archive.snapshot import RunStatus
from sweeps.types import (
    DegradedDataError,
    MarkerMismatchError,
    ResultMetrics,
    ResultParseError,
    RunResult,
    SweepConfig,
    Window,
)


class ArchivePersister(Protocol):
    """The INJECTED durable-archive hook (#276b). The adapter calls it after a local run reaches a
    terminal verdict, passing the config + the LEAN result-JSON path + the mapped RunStatus; the
    prod closure wraps `sweeps.archive.persist_run` with the provenance bundle, the order-events
    reader as orders_fetch, the caller-stamped timestamp, env='local', and dest_root. Tests pass a
    spy. Single code path with cloud — local differs ONLY in env + orders_fetch source + dest."""

    def __call__(
        self, *, config: SweepConfig, result_path: Path, status: RunStatus, window: Window
    ) -> None: ...

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


class WarmupGate:
    """(C) — serialize the memory-heavy WARMUP phase across concurrent local cells while keeping
    post-warmup EXECUTION parallel.

    WHY: the warmup LOAD (LEAN's progressive 750-day history + indicator build) is the OOM trigger
    at >1 concurrency — two cells both mid-load blow host memory (the w5 death, 2026-06-02, died at
    54% warmup beside a sibling). Execution AFTER warmup is light (steady-state RSS). So a capacity-1
    gate around the WARMUP phase only — a cell holds the gate from launch until LEAN logs the
    transition marker `Algorithm finished warming up.`, then RELEASES it so the next cell can begin
    warming while this one trades on. At most one warmup load in flight; N>1 cells still execute
    concurrently. This buys reliable parallelism today without #332's warmup-cache (which removes the
    warmup cost entirely but needs a LEAN feasibility spike first).

    NOT a workaround branch (CLAUDE.md §parity): it changes only the ORCHESTRATION (when cells start),
    never the strategy code or data path — every cell runs the identical `lean backtest` it would run
    serially. A cell that dies mid-warmup (no marker) releases the gate on process exit — no deadlock.
    Capacity-1 at workers=1 is a no-op (the gate is always immediately available)."""

    DONE_MARKER = "Algorithm finished warming up."

    def __init__(self, capacity: int = 1) -> None:
        # Semaphore(1): exactly one cell in the warmup phase at a time. capacity>1 would allow more
        # concurrent warmups (raise only if a bigger host proves it safe — empirically 1 is right).
        self._sem = threading.Semaphore(capacity)

    def run(self, argv: list[str], env: Mapping[str, str],
            popen: Callable[..., Any] | None = None) -> int:
        """Launch `argv` under the gate: acquire, stream stdout, release at the warmup-done marker
        (or on process exit if the marker never appears), return the exit code. `popen` is injected
        in tests (a FakePopen); prod uses subprocess.Popen with merged stderr + line buffering."""
        _popen = popen or (lambda: subprocess.Popen(  # noqa: E731 — thin prod default
            argv, env=dict(env), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
        ))
        self._sem.acquire()
        proc = _popen()
        return self._stream(proc.stdout, proc.wait, proc)

    def _stream(self, lines: Iterable[str], wait: Callable[[], int], proc: Any) -> int:
        """Consume the line stream; release the gate the instant the warmup-done marker is seen, then
        drain to exit. Pure-logic core (testable with a fake line iterable + wait/returncode)."""
        released = False
        try:
            for line in lines:
                if not released and self.DONE_MARKER in line:
                    self._sem.release()
                    released = True
            wait()
            return getattr(proc, "returncode", 0)
        finally:
            if not released:  # marker never seen (crash/OOM mid-warmup, or no stdout) — free the lane
                self._sem.release()


def make_gated_run_lean(gate: WarmupGate) -> RunLean:
    """Build a RunLean closure that runs `lean backtest <dir>` through the WarmupGate (the Docker
    host fix preserved). Drop-in for `run_lean` on LocalLeanRun — same `(project_dir) -> int`."""
    def run_lean(project_dir: Path) -> int:
        env = dict(os.environ)
        env.setdefault("DOCKER_HOST", "unix:///Users/falk/.docker/run/docker.sock")
        return gate.run(["lean", "backtest", str(project_dir)], env)
    return run_lean


def read_local_orders(result_path: Path) -> list[Mapping[str, Any]]:
    """Read the LEAN `*-order-events.json` beside `result_path` and reconstruct order-shaped dicts
    the snapshotter's `_pair_trades` consumes (the cloud `/orders/read` shape: order-level status /
    quantity / price / symbol / lastFillTime / tag).

    WHY a transform: LEAN emits a FLAT list of order *events* (submitted/filled/...), NOT the
    order-level shape `_pair_trades` expects. We fold each order's events into one order dict —
    taking the FILLED event for fillPrice/fillQuantity/time, signing quantity by `direction`
    (buy=+, sell=-) so the FIFO pairing sees the side correctly.

    DECISION CONTEXT: order EVENTS carry no `tag`, but the LEAN result JSON's `orders` map does
    (identical shape to cloud — verified). We merge the tag in from the sibling result JSON keyed
    by orderId, so the local archive preserves the entry decision_* context (not all CORE_MISSING).
    If the events file is absent, FAIL LOUD (a missing artifact is not 'no orders')."""
    events_path = _find_order_events(result_path)
    if events_path is None:
        raise ResultParseError(
            f"no *-order-events.json beside {result_path} — cannot reconstruct local orders "
            f"for the durable archive (fail loud, #276b)"
        )
    events: list[Mapping[str, Any]] = json.loads(events_path.read_text(encoding="utf-8"))
    tags = _order_tags_from_result(result_path)

    # Fold events per orderId into one order dict (status=filled iff a fill event exists).
    by_order: dict[Any, dict[str, Any]] = {}
    for ev in events:
        oid = ev.get("orderId")
        if oid is None:
            continue
        if str(ev.get("status", "")).lower() != "filled":
            continue
        sign = -1.0 if str(ev.get("direction", "")).lower() == "sell" else 1.0
        qty = abs(float(ev.get("fillQuantity") or ev.get("quantity") or 0.0)) * sign
        by_order[oid] = {
            "id": oid,
            "symbol": {"value": ev.get("symbolValue") or ev.get("symbol")},
            "quantity": qty,
            "price": float(ev.get("fillPrice") or 0.0),
            "status": "filled",
            "time": ev.get("time"),
            "lastFillTime": ev.get("time"),
            "tag": tags.get(oid),
            "type": None,
        }
    return list(by_order.values())


def _find_order_events(result_path: Path) -> Path | None:
    matches = sorted(result_path.parent.glob("*-order-events.json"))
    return matches[0] if matches else None


def _order_tags_from_result(result_path: Path) -> dict[Any, str | None]:
    """Pull each order's `tag` + `type` from the LEAN result JSON's `orders` map (cloud-shaped),
    keyed by order id, so the reconstructed order dicts carry the entry decision tag + exit type.
    Best-effort: a malformed/absent orders map yields no tags (rows degrade to CORE_MISSING, never
    crash) — the events themselves are the load-bearing fill source."""
    try:
        doc = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    orders = doc.get("orders")
    if not isinstance(orders, Mapping):
        return {}
    out: dict[Any, str | None] = {}
    for o in orders.values():
        if isinstance(o, Mapping) and o.get("id") is not None:
            out[o["id"]] = o.get("tag") or None
    return out


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
    persist: ArchivePersister | None = None
    # When run_dirs live INSIDE the lean workspace, lean resolves data via the ROOT lean.json
    # data-folder — a PROJECT-level `data/` symlink then HANGS lean (the Docker bind-mount cannot
    # mount a symlinked dir; verified 2026-06-02: a project data-symlink → 0 output / hang; removing
    # it → the BT runs). So symlink_data defaults False; set True only for standalone out-of-workspace
    # run_dirs that need their own data mount.
    symlink_data: bool = False

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
        if self.symlink_data:
            self._symlink_data(run_dir)  # only for out-of-workspace run_dirs (hangs lean in-workspace)

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
            # Archive the DEGRADED verdict (provenance survives) BEFORE raising — same fail-loud
            # contract as cloud: a dropped run still leaves a durable artifact, the persist call
            # propagates if it fails (never swallows the run verdict).
            if self.persist is not None:
                self._archive(config, result_path, RunStatus.COMPLETED_DEGRADED, window)
            raise DegradedDataError(
                f"degraded run for config {config.config_hash} window {window.name}: "
                f"orders={run_result.metrics.orders} (empty-warmup-coarse / data outage) — "
                f"crashing rather than banking a mirage metric (G-DATA gate)"
            )
        if self.persist is not None:
            self._archive(config, result_path, RunStatus.COMPLETED_CLEAN, window)
        return run_result

    def _archive(self, config: SweepConfig, result_path: Path, status: RunStatus, window: Window) -> None:
        """Invoke the injected persist hook. A persist failure is LOUD — it propagates, it never
        silently swallows the run verdict (the snapshotter's fail-loud contract, #276b). The window
        is threaded so the persist can capture CENSORED-OPEN rows (positions open at the window's end
        — common for a short sweep window; without it, an all-open window archives 0 rows → the
        EmptyTradesError fires on a legitimately-open run, the #325 first-use gap)."""
        assert self.persist is not None
        self.persist(config=config, result_path=result_path, status=status, window=window)

    def __call__(self, config: SweepConfig, window: Window) -> ResultMetrics:
        """The RunConfig Protocol surface: returns the leaderboard-facing metrics trio."""
        return self.run_result(config, window).metrics


def make_local_persist(
    *,
    commit: str,
    data_fingerprint: str,
    objective_version: str,
    dest_root: Path,
    data_root: Path | None = None,
    clock: Callable[[], str] | None = None,
) -> ArchivePersister:
    """Build the local durable-archive persist closure (#276b) — the local twin of
    qc_cloud_prod.make_cloud_run's persist hook. SINGLE CODE PATH with cloud: identical persist_run
    call, differing ONLY in env='local', orders_fetch (the order-events reader), and dest_root —
    legitimate adapter polymorphism, NOT a strategy branch.

    Provenance (commit / data_fingerprint) is INJECTED here because the local dist_builder returns
    only a marker, not a BuildResult; the caller threads the BuildResult fields in. The persist
    `timestamp` is stamped via `clock` (defaults to UTC now ISO) — NEVER inside snapshot.py.

    Mapping per run:
      config       → serialize_config(SweepConfig)
      backtest_id  → the LEAN run-dir id (the result-JSON stem, e.g. '1230337650') — uniqueness key
      statistics   → the result JSON's `statistics` block
      orders_fetch → read_local_orders(result_path) (ignores the bid arg — local has one result dir)
      env          → 'local'
    """
    from sweeps.archive import persist_run  # local import: keep module import-light

    from sweeps.archive import M2M_LOCAL_PARQUET, M2M_UNAVAILABLE

    now_iso = clock or (lambda: datetime.now(timezone.utc).isoformat())
    daily_root = (data_root or (Path(__file__).resolve().parents[2] / "data")) / "equity" / "usa" / "daily"

    def _m2m_mark(symbol: str, end_of_data: datetime) -> tuple[float | None, str]:
        """Local-daily close at-or-before end_of_data for a position open at the window's end (the
        CENSORED-OPEN provisional mark). RAW/unadjusted (÷10000). Unavailable → null mark, NEVER
        faked. NOTE: local-daily M2M is NOT cloud-faithful on the unrealized leg (vendor delta) —
        fine for candidate-RANKING if consistent within the run; the winner is cloud-validated."""
        import zipfile
        zp = daily_root / f"{symbol.lower()}.zip"
        if not zp.exists():
            return (None, M2M_UNAVAILABLE)
        eod = end_of_data.date() if hasattr(end_of_data, "date") else end_of_data
        best: float | None = None
        try:
            with zipfile.ZipFile(zp) as z:
                for line in z.read(z.namelist()[0]).decode().splitlines():
                    p = line.split(",")
                    d = p[0][:8]
                    dd = datetime(int(d[:4]), int(d[4:6]), int(d[6:8])).date()
                    if dd <= eod:
                        best = float(p[4]) / 10000.0
        except Exception:
            return (None, M2M_UNAVAILABLE)
        return (best, M2M_LOCAL_PARQUET) if best and best > 0 else (None, M2M_UNAVAILABLE)

    def persist(*, config: SweepConfig, result_path: Path, status: RunStatus, window: Window) -> None:
        doc = json.loads(result_path.read_text(encoding="utf-8"))
        bt_id = result_path.stem  # the LEAN <id>.json stem == the run id (the archive's key)
        sy, sm, sd = (int(x) for x in window.end.split("-"))
        end_of_data = datetime(sy, sm, sd)  # the window's END — mark date for CENSORED-OPEN lots
        persist_run(
            config=serialize_config(config),
            config_hash=config.config_hash,
            backtest_id=bt_id,
            status=status,
            statistics=doc.get("statistics", {}) or {},
            commit=commit,
            data_fingerprint=data_fingerprint,
            objective_version=objective_version,
            timestamp=now_iso(),
            env="local",
            orders_fetch=lambda _bid: read_local_orders(result_path),
            dest_root=dest_root,
            end_of_data=end_of_data,  # #325 fix: capture CENSORED-OPEN (positions open at window-end)
            m2m_mark=_m2m_mark,       # local-daily provisional mark (NOT cloud-faithful; winner→cloud-validate)
            # #12: thread the LEAN result's runtimeStatistics → archived result.json. The #303 funnel
            # (funnel.signal_winners→…→orders + funnel._sem legend) RIDES runtimeStatistics; without
            # this the local sweep cells archive funnel=None and the per-run attrition record is lost
            # (the cloud path already passed it; this closes the local-adapter gap, cf the #11 doc).
            runtime_statistics=doc.get("runtimeStatistics") or doc.get("RuntimeStatistics") or None,
        )

    return persist
