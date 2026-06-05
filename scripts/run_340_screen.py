"""#340-C / #363 SIZING SCREEN — V1 Pe (flat $200) / V2 Pe-posfrac / V3 Pe-convstack × Q1(bear) +
Q3(bull), on trim+cache (the #370 fast infra, gate-2-proven byte-identical for the pyramid). SAME
Pe-trigger / max_adds / S1 core across all 3 → isolates SIZING. Sequential (local LEAN is cap-1);
~6min/cell × 6 ≈ 36min.

Each variant runs under its own runs_root subdir (the trim SweepConfig is identical across variants —
only the base_module CONFIG differs — so distinct dirs prevent a hash collision). HQ reads all 6 trios
+ the per-variant add-size / gross-cap-drop / floor instrumentation from the files. settle-before-analyze.

Usage: python3 scripts/run_340_screen.py [v1|v2|v3 ...] [q1|q3]   (default: all 3 × Q1,Q3)
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
from sweeps.types import SweepConfig  # noqa: E402
from sweeps.windows import SIX_WINDOWS  # noqa: E402

_FP = "90f2d7e3fb80d0a4d2eb286f6a43199e1519495a3ce9d787a4d7d0dfc70c535c"
SCREEN_ROOT = _ROOT / "sweeps" / "runs_340screen"
TRIM = SweepConfig(choices=(), continuous_weekly=True, warmup_days=320)   # trim+cache (gate-2-proven)

VARIANTS = [
    ("v1_pe", "strategies.screen_v1_pe", "Pe (flat $200) CONTROL"),
    ("v2_posfrac", "strategies.screen_v2_posfrac", "Pe-posfrac (0.25×posval)"),
    ("v3_convstack", "strategies.screen_v3_convstack", "Pe-convstack (0.25×posval×conviction)"),
]
_BY_NAME = {w.name: w for w in SIX_WINDOWS}
WINDOWS = {"q1": _BY_NAME["w1_2025q1"], "q3": _BY_NAME["w3_2025q3"]}


def main() -> None:
    args = [a.lower() for a in sys.argv[1:]]
    vkeys = [a for a in args if a in {"v1", "v2", "v3"}] or ["v1", "v2", "v3"]
    wkeys = [a for a in args if a in {"q1", "q3"}] or ["q1", "q3"]
    sel_v = [v for v in VARIANTS if v[0].split("_")[0] in vkeys]
    sel_w = [WINDOWS[k] for k in wkeys]
    print(f"=== #340-C SIZING SCREEN — {[v[0] for v in sel_v]} × {[w.name for w in sel_w]} (trim+cache) ===", flush=True)
    grid = []
    for vkey, vmod, vlabel in sel_v:
        sb.build_sweep_dist.__kwdefaults__ = {**(sb.build_sweep_dist.__kwdefaults__ or {}), "base_module": vmod}
        adapter = make_local_run(runs_root=SCREEN_ROOT / vkey, warmup_gate=None, ensure_weekly_cache_fp=_FP)
        for w in sel_w:
            print(f"\n--- {vkey} [{vlabel}] {w.name} ({w.start}..{w.end}) ---", flush=True)
            m = adapter(TRIM, w)
            rd = SCREEN_ROOT / vkey / TRIM.config_hash / w.name
            print(f"  {vkey} {w.name}: Sharpe={m.sharpe:+.3f}  Net={m.ret_pct:+.1f}%  DD={m.dd_pct:.1f}%  "
                  f"Orders={m.orders}  | dir={rd}", flush=True)
            grid.append((vkey, w.name, m.sharpe, m.ret_pct, m.dd_pct, m.orders))
    print("\n=== SCREEN GRID (Sharpe / Net% / DD% / Orders) — vs S1-FY 1.025/+27.7%/DD19.4% ===", flush=True)
    for vkey, wn, sh, rt, dd, od in grid:
        print(f"  {vkey:13} {wn:12} {sh:+.3f} / {rt:+.1f}% / {dd:.1f}% / {od}", flush=True)
    print(f"\nDIRS: {SCREEN_ROOT}/<variant>/{TRIM.config_hash}/<window>/backtests/<ts>/ — order-events + "
          f"PROTECTIVE_STOP_RESIZE / PYRAMID_EVAL / GROSS_CAP_ADDS per variant.", flush=True)


if __name__ == "__main__":
    main()
