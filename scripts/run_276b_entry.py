"""#276b ENTRY-MECHANIC param-sweep — gap_threshold ∈ {0.02,0.03,0.04,0.05} (the primary axis) on the
EXISTING S1 entry stack (no new phase). gt03 == S1 (built-in parity check). trim+cache fast infra.
Window-then-FY: Q1-bear + Q3-bull first (the regime-robustness screen), then the winner → FY.

Judged on the floor-proxy KPI (scripts/kpi.py → leaderboard) same-method vs S1. WIN = a gap_threshold
beats S1's floor-proxy on BOTH windows → escalate to FY/6-window.

Each variant runs in its own runs_root (shared config_hash across base_modules — distinct dirs avoid
collision). Usage: python3 scripts/run_276b_entry.py [gt02 gt03 gt04 gt05] [q1 q3]
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
RUNS = _ROOT / "sweeps" / "runs_276bentry"
TRIM = SweepConfig(choices=(), continuous_weekly=True, warmup_days=320)
_BY = {w.name: w for w in SIX_WINDOWS}
WINDOWS = {"q1": _BY["w1_2025q1"], "q3": _BY["w3_2025q3"]}

VARIANTS = [
    ("gt02", "strategies.entry_gt02", "gap_threshold 0.02 (looser, more gap-ups)"),
    ("gt03", "strategies.entry_gt03", "gap_threshold 0.03 (== S1, parity)"),
    ("gt04", "strategies.entry_gt04", "gap_threshold 0.04 (tighter)"),
    ("gt05", "strategies.entry_gt05", "gap_threshold 0.05 (tightest)"),
]


def main() -> None:
    args = [a.lower() for a in sys.argv[1:]]
    vkeys = [a for a in args if a.startswith("gt")] or [v[0] for v in VARIANTS]
    wkeys = [a for a in args if a in ("q1", "q3")] or ["q1", "q3"]
    sel_w = [(k, WINDOWS[k]) for k in wkeys]
    print(f"=== #276b ENTRY-SWEEP gap_threshold — {vkeys} × {[k for k, _ in sel_w]} (vs S1 floor-proxy) ===", flush=True)
    for vkey, vmod, vlabel in VARIANTS:
        if vkey not in vkeys:
            continue
        sb.build_sweep_dist.__kwdefaults__ = {**(sb.build_sweep_dist.__kwdefaults__ or {}), "base_module": vmod}
        for wk, w in sel_w:
            adapter = make_local_run(runs_root=RUNS / vkey / wk, warmup_gate=None, ensure_weekly_cache_fp=_FP)
            print(f"\n--- {vkey} [{vlabel}] {w.name} ---", flush=True)
            m = adapter(TRIM, w)
            cell = RUNS / vkey / wk / TRIM.config_hash / w.name
            report_and_log(cell, f"#276b {vkey} {w.name}", sharpe=m.sharpe, net_pct=m.ret_pct,
                           dd_pct=m.dd_pct, fills=m.orders, config_hash=TRIM.config_hash,
                           window=w.name, stamp="2026-06-05",
                           asof=_dt.date.fromisoformat(w.end))  # re-mark open @ the WINDOW end, not FY end
    print(f"\nDIRS: {RUNS}/<variant>/<window>/ — leaderboard rows logged (floor-proxy). gt03 should == S1.", flush=True)


if __name__ == "__main__":
    main()
