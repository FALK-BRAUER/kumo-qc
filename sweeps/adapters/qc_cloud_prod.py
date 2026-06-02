"""PROD cloud wiring for CloudLeanRun (#323 — the call-site #214 left as injected callables).

CloudLeanRun is unit-tested with MOCKS; this is the REAL wiring that deploys an arbitrary
SweepConfig to QC and polls a backtest. It composes:
  - build.sweep_build.build_sweep_dist  (SweepConfig → deployable dist, with the sweep-<hash> marker)
  - scripts.qc_v2_cloud                  (the proven /files/update deploy + /backtests poll loop)

SEQUENTIAL-ONLY: the deploy step monkeypatches qc_v2_cloud module globals (DIST / MARKER /
STEP_A_WINDOW) per call — safe because the sweep runs ONE backtest at a time on the single QC
stream (Researcher tier). The runner MUST NOT call this concurrently.

The poll resolves the #326 stats-lag HERE (re-read until Total Orders populates) so the
returned CloudResult.raw carries populated statistics — the adapter's strict assert_cloud_clean
(which raises on null orders with no re-read) then never false-negatives a clean run.

qc_v2_cloud reads the QC keychain creds at import → this module is import-side-effectful and is
NOT imported by the adapter (the adapter takes these as injected functions). Import it only here,
at the prod call-site.
"""
from __future__ import annotations

import tempfile
import time
from pathlib import Path
from typing import Any

from sweeps.adapters.cloud_lean import CloudLeanRun, CloudResult
from sweeps.types import SweepConfig, Window


def _window_str(window: Window) -> str:
    """Window(ISO start,end) → the START_DATE/END_DATE class-attr block qc_v2_cloud bakes into
    the deployed main.py (the v2 BctEngineAlgorithm reads dates from class attrs, not params)."""
    ys, ms, ds = (int(x) for x in window.start.split("-"))
    ye, me, de = (int(x) for x in window.end.split("-"))
    return f"    START_DATE = ({ys}, {ms}, {ds})\n    END_DATE = ({ye}, {me}, {de})\n"


def make_cloud_run(
    *, dist_root: Path | None = None, poll_minutes: int = 30,
    reread_tries: int = 3, reread_delay: float = 6.0,
) -> CloudLeanRun:
    """Build a CloudLeanRun wired to REAL QC. `dist_root` holds per-config dist dirs (temp by
    default). Returns the adapter; the runner calls `.run_result(config, window)`."""
    import qc_v2_cloud as q  # import-side keychain read — prod call-site only

    root = dist_root or Path(tempfile.gettempdir()) / "sweep_dists"
    root.mkdir(parents=True, exist_ok=True)

    def deploy(config: SweepConfig, window: Window) -> str:
        from build.sweep_build import build_sweep_dist
        dist_dir = root / config.config_hash
        build_sweep_dist(config, dist_dir=dist_dir)          # SweepConfig → deployable dist
        q.DIST = dist_dir                                     # point the driver at THIS config's dist
        q.MARKER = f"sweep-{config.config_hash}"              # readback check = the config name
        q.STEP_A_WINDOW = _window_str(window)                 # bake the window into the deployed main.py
        return q.deploy()                                     # /files/update + compile → compileId

    def run_backtest(name: str, compile_id: str) -> CloudResult:
        q._require_pid()
        r = q.post("/backtests/create", {"projectId": q.PID, "compileId": compile_id, "backtestName": name})
        if not r.get("success"):
            return CloudResult(backtest_id="", progress=0.0, error=f"submit failed: {str(r)[:300]}", raw={})
        bid = r.get("backtest", {}).get("backtestId")
        for _ in range(poll_minutes * 6):
            time.sleep(10)
            b = q.post("/backtests/read", {"projectId": q.PID, "backtestId": bid}).get("backtest", {})
            err = b.get("error") or b.get("stacktrace")
            if err:
                return CloudResult(backtest_id=bid, progress=float(b.get("progress", 0) or 0), error=str(err), raw=b)
            if b.get("completed"):
                b = _settle_stats(q, bid, b, reread_tries, reread_delay)  # #326 stats-lag re-read
                return CloudResult(backtest_id=bid, progress=float(b.get("progress", 1) or 1), error=None, raw=b)
        return CloudResult(backtest_id=bid, progress=0.0, error="poll timeout", raw={})

    return CloudLeanRun(deploy=deploy, run_backtest=run_backtest)


def _settle_stats(q: Any, bid: str, b: dict, tries: int, delay: float) -> dict:
    """#326: QC populates statistics a beat AFTER `completed` flips → Total Orders comes back
    null at first read. Re-read until it populates (the adapter's strict assert has no re-read,
    so settle it here) — return the freshest doc either way (the adapter fails loud if still null)."""
    if (b.get("statistics", {}) or {}).get("Total Orders") is not None:
        return b
    for _ in range(max(1, tries)):
        if delay > 0:
            time.sleep(delay)
        fresh = q.post("/backtests/read", {"projectId": q.PID, "backtestId": bid}).get("backtest", {})
        if (fresh.get("statistics", {}) or {}).get("Total Orders") is not None:
            return fresh
        b = fresh or b
    return b
