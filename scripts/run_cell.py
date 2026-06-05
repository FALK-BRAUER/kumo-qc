"""Run ONE tournament cell in its OWN process (the race-free parallel unit). base_module is a
process-global (sb.build_sweep_dist.__kwdefaults__) — so the ONLY safe way to run different modules
concurrently is one PROCESS per cell (each has its own global; no thread-shared-state race). run_fleet
spawns N of these. Identical `lean backtest` to the serial path — only the orchestration is concurrent
(CLAUDE.md §parity: no strategy/data/path change → byte-identical results, asserted by the cap-2 test).

Usage: python3 scripts/run_cell.py <module> <window-key q1|q3|fy> <runs_subdir>
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
from sweeps.windows import SIX_WINDOWS, Window  # noqa: E402
from kpi import report_and_log  # noqa: E402

_FP = "90f2d7e3fb80d0a4d2eb286f6a43199e1519495a3ce9d787a4d7d0dfc70c535c"
TRIM = SweepConfig(choices=(), continuous_weekly=True, warmup_days=320)
_BY = {w.name: w for w in SIX_WINDOWS}
_WIN = {"q1": _BY["w1_2025q1"], "q3": _BY["w3_2025q3"],
        "fy": Window(name="fy2025", start="2025-01-01", end="2025-12-31")}
_ASOF = {"w1_2025q1": _dt.date(2025, 3, 31), "w3_2025q3": _dt.date(2025, 9, 30), "fy2025": _dt.date(2025, 12, 31)}


def main() -> None:
    mod, wkey, runs_sub = sys.argv[1], sys.argv[2], sys.argv[3]
    w = _WIN[wkey]
    runs_root = _ROOT / "sweeps" / f"runs_{runs_sub}"
    # own process → setting the global kwdefault is isolated (no sibling can clobber it). build-time only.
    sb.build_sweep_dist.__kwdefaults__ = {**(sb.build_sweep_dist.__kwdefaults__ or {}),
                                          "base_module": f"strategies.{mod}"}
    adapter = make_local_run(runs_root=runs_root / mod / w.name, warmup_gate=None, ensure_weekly_cache_fp=_FP)
    print(f"[cell] {mod} {w.name} START", flush=True)
    m = adapter(TRIM, w)
    rd = runs_root / mod / w.name / TRIM.config_hash / w.name
    report_and_log(rd, f"#FLEET {mod} {w.name}", sharpe=m.sharpe, net_pct=m.ret_pct, dd_pct=m.dd_pct,
                   fills=m.orders, config_hash=TRIM.config_hash, window=w.name,
                   stamp="2026-06-05", asof=_ASOF.get(w.name, _dt.date(2025, 12, 31)))
    print(f"[cell] {mod} {w.name} DONE Sharpe {m.sharpe:+.3f} net {m.ret_pct:+.1f}% floor-see-leaderboard", flush=True)


if __name__ == "__main__":
    main()
