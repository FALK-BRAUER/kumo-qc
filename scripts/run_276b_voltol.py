"""#276b entry-sweep — vol_mult × gap_up_tolerance axes (around gap_threshold=0.03=optimum), for
COMPLETENESS (expected null — 2nd-order knobs; >1.5 vol kills winners, looser tol = gt02-style bear
crater). Non-blocking. vm10_tol10 == S1 (already in the gt03 cell). trim+cache, floor-proxy leaderboard.

Usage: python3 scripts/run_276b_voltol.py
"""
from __future__ import annotations

import datetime as _dt
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_ROOT), str(_ROOT / "src"), str(_ROOT / "scripts")]
os.environ.setdefault("DOCKER_HOST", "unix:///Users/falk/.docker/run/docker.sock")

import build.sweep_build as sb  # noqa: E402
from sweeps.adapters.qc_local_prod import make_local_run  # noqa: E402
from sweeps.types import SweepConfig  # noqa: E402
from sweeps.windows import SIX_WINDOWS  # noqa: E402
from kpi import report_and_log  # noqa: E402

_FP = "90f2d7e3fb80d0a4d2eb286f6a43199e1519495a3ce9d787a4d7d0dfc70c535c"
RUNS = _ROOT / "sweeps" / "runs_276bvoltol"
TRIM = SweepConfig(choices=(), continuous_weekly=True, warmup_days=320)
_BY = {w.name: w for w in SIX_WINDOWS}
WINDOWS = {"q1": _BY["w1_2025q1"], "q3": _BY["w3_2025q3"]}
VARIANTS = [
    ("vm125_tol10", "strategies.entry_vm125_tol10", "vol_mult 1.25, tol 0.10"),
    ("vm10_tol15", "strategies.entry_vm10_tol15", "vol_mult 1.0, tol 0.15"),
    ("vm125_tol15", "strategies.entry_vm125_tol15", "vol_mult 1.25, tol 0.15"),
]


def main() -> None:
    print("=== #276b vol/tol sweep (completeness, gap=0.03) — vs S1 floor-proxy ===", flush=True)
    for vkey, vmod, vlabel in VARIANTS:
        sb.build_sweep_dist.__kwdefaults__ = {**(sb.build_sweep_dist.__kwdefaults__ or {}), "base_module": vmod}
        for wk, w in WINDOWS.items():
            adapter = make_local_run(runs_root=RUNS / vkey / wk, warmup_gate=None, ensure_weekly_cache_fp=_FP)
            print(f"\n--- {vkey} [{vlabel}] {w.name} ---", flush=True)
            m = adapter(TRIM, w)
            cell = RUNS / vkey / wk / TRIM.config_hash / w.name
            report_and_log(cell, f"#276b {vkey} {w.name}", sharpe=m.sharpe, net_pct=m.ret_pct,
                           dd_pct=m.dd_pct, fills=m.orders, config_hash=TRIM.config_hash,
                           window=w.name, stamp="2026-06-05", asof=_dt.date.fromisoformat(w.end))


if __name__ == "__main__":
    main()
