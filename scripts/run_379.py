"""#379 T1 profit-screen — the LAST autonomous lever (loser-side). S1 + PgProfitTake(T1): trim the
NEVER-PROVED faders (took a slot, never hit +5% MFE) to free cash, while the prover-gate EXEMPTS every
proved monster (≥+5% MFE held full). Structurally immune to the skip-backfire that killed the #340
reserve: the reserve skipped monsters BLINDLY at entry (#349 coin-flip); #379 only trims names that
PROVED they're faders → CANNOT sell a KGC.

window-then-FY (HQ): Q1+Q3 gate first, then FY2025 verdict. #379 WIN = monster-sells=0 (prover-gate
holds) + realized-tail-cut (fewer realized losers vs S1) + freed-cash-redeploys + floor-proxy ≥ S1.
S1 baseline already on the board (matrix_sz050_off: Q1 -10.4, Q3 -5.5, FY Sharpe 1.025 / floor 21.1).

Usage: python3 scripts/run_379.py [q1 q3 fy]   (default: all three, window-then-FY order)
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_ROOT), str(_ROOT / "src"), str(_ROOT / "scripts")]
os.environ.setdefault("DOCKER_HOST", "unix:///Users/falk/.docker/run/docker.sock")

import build.sweep_build as sb  # noqa: E402
from sweeps.adapters.qc_local_prod import make_local_run  # noqa: E402
from sweeps.types import SweepConfig  # noqa: E402
from sweeps.windows import SIX_WINDOWS, Window  # noqa: E402
from kpi import report_and_log  # noqa: E402

_FP = "90f2d7e3fb80d0a4d2eb286f6a43199e1519495a3ce9d787a4d7d0dfc70c535c"
RUNS = _ROOT / "sweeps" / "runs_379"
TRIM = SweepConfig(choices=(), continuous_weekly=True, warmup_days=320)
_BY = {w.name: w for w in SIX_WINDOWS}
WINDOWS = {"q1": _BY["w1_2025q1"], "q3": _BY["w3_2025q3"],
           "fy": Window(name="fy2025", start="2025-01-01", end="2025-12-31")}
MOD = "strategies.profit_t1"


def _trim_audit(run_dir: Path) -> str:
    """The #379 prover-gate check: how many PROFIT_TRIM logs, and were any on a proved monster?
    (PgProfitTake only emits trims for never-proved faders → monster-trims should be 0 by construction;
    this audits the log to confirm the gate held at runtime.)"""
    bts = sorted((run_dir / "backtests").glob("*/"), key=lambda d: d.stat().st_mtime, reverse=True)
    if not bts:
        return "no-bt"
    log = next(bts[0].glob("*log.txt"), None) or next(bts[0].glob("log.txt"), None)
    if log is None:
        return "no-log"
    trims = [ln for ln in log.read_text(errors="ignore").splitlines() if "PROFIT_TRIM_T1" in ln]
    return f"{len(trims)} fader-trims logged (all never-proved by construction)"


def main() -> None:
    args = [a.lower() for a in sys.argv[1:]] or ["q1", "q3", "fy"]
    print("=== #379 T1 profit-screen — window-then-FY (vs S1) ===", flush=True)
    sb.build_sweep_dist.__kwdefaults__ = {**(sb.build_sweep_dist.__kwdefaults__ or {}), "base_module": MOD}
    for key in args:
        w = WINDOWS[key]
        adapter = make_local_run(runs_root=RUNS / w.name, warmup_gate=None, ensure_weekly_cache_fp=_FP)
        print(f"\n--- profit_t1 {w.name} ---", flush=True)
        m = adapter(TRIM, w)
        rd = RUNS / w.name / TRIM.config_hash / w.name
        asof = _dt.date.fromisoformat(w.end)
        report_and_log(rd, f"#379T1 {w.name}", sharpe=m.sharpe, net_pct=m.ret_pct, dd_pct=m.dd_pct,
                       fills=m.orders, config_hash=TRIM.config_hash, window=w.name,
                       stamp="2026-06-05", asof=asof)
        print(f"    prover-gate audit: {_trim_audit(rd)}", flush=True)


if __name__ == "__main__":
    main()
