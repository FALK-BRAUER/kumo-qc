"""#345/#363 ROTATION SCREEN — gain-floored R1/R2 on FY (the floor-proxy is the decisive metric; the
2mo window-screen is INVALID for a let-winners lever — it truncates winners at 60d). trim+cache fast
infra (gate-2-proven). vs S1 floor-proxy +21.13% (config 65c0cf447168).

config_hash is base_module-independent (SweepConfig sees only choices/warmup/continuous_weekly), so
R1/R2 share a hash + would COLLIDE in results/archive. We run SEQUENTIALLY and floor_proxy() IMMEDIATELY
after each run, before the next overwrites the archive cell. Each variant's order-events live in its own
runs_root (sweeps/runs_345rot/<variant>/).

Usage: python3 scripts/run_345_rotation.py [r1|r2 ...]   (default: r1 r2)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_ROOT), str(_ROOT / "src"), str(_ROOT / "scripts")]
os.environ.setdefault("DOCKER_HOST", "unix:///Users/falk/.docker/run/docker.sock")

import build.sweep_build as sb  # noqa: E402
from sweeps.adapters.qc_local_prod import make_local_run  # noqa: E402
from sweeps.types import SweepConfig, Window  # noqa: E402

import floor_proxy as fp  # noqa: E402  (scripts/floor_proxy.py)

_FP = "90f2d7e3fb80d0a4d2eb286f6a43199e1519495a3ce9d787a4d7d0dfc70c535c"
RUNS = _ROOT / "sweeps" / "runs_345rot"
FY = Window(name="fy2025_full", start="2025-01-01", end="2025-12-31")
TRIM = SweepConfig(choices=(), continuous_weekly=True, warmup_days=320)
S1_FLOOR_PCT = 21.13  # S1 (65c0cf447168) FY floor-proxy — the bar to beat

VARIANTS = [
    ("r1", "strategies.screen_r1", "gain-floored evict-on-better-candidate"),
    ("r2", "strategies.screen_r2", "gain-floored lock-the-weakening-gain"),
]


def main() -> None:
    sel = [a.lower() for a in sys.argv[1:]] or ["r1", "r2"]
    rows = []
    print(f"=== #345 ROTATION SCREEN (gain-floored) — {sel} on FY, vs S1 floor-proxy +{S1_FLOOR_PCT}% ===", flush=True)
    for vkey, vmod, vlabel in VARIANTS:
        if vkey not in sel:
            continue
        sb.build_sweep_dist.__kwdefaults__ = {**(sb.build_sweep_dist.__kwdefaults__ or {}), "base_module": vmod}
        adapter = make_local_run(runs_root=RUNS / vkey, warmup_gate=None, ensure_weekly_cache_fp=_FP)
        print(f"\n--- {vkey} [{vlabel}] FY ---", flush=True)
        m = adapter(TRIM, FY)
        # floor-proxy IMMEDIATELY (before the next variant overwrites the shared-hash archive cell)
        try:
            r = fp.floor_proxy(TRIM.config_hash)
            floor_pct = r.get("floor_total", 0.0) / 1000.0  # placeholder if % not provided
            realized = r.get("realized", 0.0)
            m2m = r.get("m2m", 0.0)
            floor_total = r.get("floor_total", 0.0)
            print(f"  {vkey}: trio Sharpe={m.sharpe:+.3f}/{m.ret_pct:+.1f}%/DD{m.dd_pct:.1f}%/{m.orders}ord | "
                  f"FLOOR-PROXY=${floor_total:,.0f} (realized=${realized:,.0f}, m2m=${m2m:,.0f})", flush=True)
            rows.append((vkey, m.sharpe, m.ret_pct, m.dd_pct, m.orders, realized, m2m, floor_total))
        except Exception as exc:  # noqa: BLE001
            print(f"  {vkey}: trio {m.sharpe:+.3f}/{m.ret_pct:+.1f}%/DD{m.dd_pct:.1f}%/{m.orders} | "
                  f"floor_proxy FAILED: {exc!r} (read order-events in {RUNS/vkey})", flush=True)
            rows.append((vkey, m.sharpe, m.ret_pct, m.dd_pct, m.orders, None, None, None))

    print(f"\n=== ROTATION FLOOR-PROXY GRID — vs S1 +{S1_FLOOR_PCT}% (WINNER must BEAT it w/o clipping runners) ===", flush=True)
    for vkey, sh, rt, dd, od, real, m2m, ft in rows:
        fts = f"${ft:,.0f} ({ft/1000.0:+.1f}k)" if ft is not None else "N/A"
        reals = f"${real:,.0f}" if real is not None else "N/A"
        print(f"  {vkey}: {sh:+.3f}/{rt:+.1f}%/DD{dd:.1f}%/{od}ord  floor-proxy={fts}  realized={reals}", flush=True)
    print(f"\nDIRS: {RUNS}/<variant>/ — order-events + ROTATION_<variant> log lines (evicted/freed/redeploy).", flush=True)


if __name__ == "__main__":
    main()
