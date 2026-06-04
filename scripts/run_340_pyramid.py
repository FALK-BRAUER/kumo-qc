"""#340-B BT — champion_pyramid (S1 + StagedRiskPyramid / Pe-rampup) vs the S1 control. FY + the
6-window panel. FULL-WARMUP (correct + simple for the first money result; the #370 trim+cache 6×
speedup is a later rebase onto the merged mainV2). Builds champion_pyramid by overriding the dist's
base_module; runs in a DISTINCT runs_root (no hash collision with the S1 control runs).

S1 CONTROL is the existing champion (champion_intraday_gapvol) FY = Sharpe 1.025 / +27.7% / DD 19.4%
/ 55 fills (hash 65c0cf447168). This runs the PYRAMID; HQ reads the trio + the per-window trade
ledger (the survival-ledger: monster-amplification Σ open-paper HOOD/KGC ↑, realized-loser tail, DD)
from the result files. Produce the artifact + point to it — do NOT analyze.

Usage: python3 scripts/run_340_pyramid.py [fy|all]   (default: all — FY then the 6 windows)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_ROOT), str(_ROOT / "src"), str(_ROOT / "scripts")]
os.environ.setdefault("DOCKER_HOST", "unix:///Users/falk/.docker/run/docker.sock")

import build.sweep_build as sb  # noqa: E402

# build_sweep_dist's `base_module` default was bound at DEF-time (= champion_intraday_gapvol), so
# reassigning sb.BASE_MODULE is too late. local_dist_builder calls build_sweep_dist WITHOUT base_module
# → it uses that bound default. Patch the function's keyword default so the dist flattens
# champion_pyramid (S1 + the StagedRiskPyramid adds slot) instead.
sb.build_sweep_dist.__kwdefaults__ = {**(sb.build_sweep_dist.__kwdefaults__ or {}),
                                      "base_module": "strategies.champion_pyramid"}
_PYRAMID_BASE = "strategies.champion_pyramid"

from sweeps.adapters.qc_local_prod import make_local_run  # noqa: E402
from sweeps.types import SweepConfig, Window  # noqa: E402
from sweeps.windows import SIX_WINDOWS  # noqa: E402

PYRAMID = SweepConfig(choices=(), continuous_weekly=True)  # empty → base_module fully defines the strategy
FY = Window(name="fy2025_full", start="2025-01-01", end="2025-12-31")
RUNS = _ROOT / "sweeps" / "runs_340pyramid"


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    windows = [FY] if mode == "fy" else [FY, *SIX_WINDOWS]
    adapter = make_local_run(runs_root=RUNS)
    print(f"=== #340-B champion_pyramid BT (full-warmup) — {[w.name for w in windows]} ===", flush=True)
    print(f"    config_hash={PYRAMID.config_hash} base_module={_PYRAMID_BASE} runs_root={RUNS}", flush=True)
    for w in windows:
        print(f"\n--- champion_pyramid {w.name} ({w.start}..{w.end}) ---", flush=True)
        m = adapter(PYRAMID, w)
        rd = RUNS / PYRAMID.config_hash / w.name
        print(f"  {w.name}: Sharpe={m.sharpe:+.3f}  Net={m.ret_pct:+.1f}%  DD={m.dd_pct:.1f}%  "
              f"Orders={m.orders}  | dir={rd}", flush=True)
    print(f"\nRESULT DIRS: {RUNS}/{PYRAMID.config_hash}/<window>/backtests/<ts>/ — order-events + "
          f"the archived trade ledger for the survival-ledger. S1 CONTROL = 65c0cf447168 FY "
          f"(Sharpe 1.025 / +27.7% / DD 19.4% / 55 fills).", flush=True)


if __name__ == "__main__":
    main()
