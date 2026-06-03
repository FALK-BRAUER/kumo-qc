"""#339 rotation-v2 RUN — RotationV2 (recycle stalled-green) on the S1 base. ONE lever.

Config = CloudProtectiveStop + CloudAdherenceTrail + FlatPctHeatcap(0.05) + RotationV2 (the corrected
green-flat rotation: evict PnL>0/below-Tenkan/above-Kijun; protect runners+underwater). vs S1 (no
rotation): FLOOR +21.13% / Sharpe 1.025 / 17 open (8 dead-green-flat slot-occupiers). vs RUN R
(rotation v1, weakest-weakening): -22.8% realized (churned dips). Hypothesis: recycling dead-green
ADDS (flips rotation positive) without touching runners or booking dips.

assert-engaged: ROTATION_V2 fires >0 AND every evicted ∈ dead-green-flat (PnL>0/below-Tenkan/above-
Kijun); ZERO underwater/trending rotated. Headline = floor-proxy vs S1 +21.13%. FY-full first.
Usage: SWEEP_WORKERS=2 python3 scripts/run_339_rv2_rotation.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_ROOT), str(_ROOT / "src"), str(_ROOT / "scripts")]

os.environ.setdefault("DOCKER_HOST", "unix:///Users/falk/.docker/run/docker.sock")

from sweeps.adapters.local_lean import WarmupGate  # noqa: E402
from sweeps.adapters.qc_local_prod import make_local_run  # noqa: E402
from sweeps.run_sweep import run_sweep  # noqa: E402
from sweeps.types import PhaseChoice, SweepConfig, Window  # noqa: E402
from sweeps.windows import local_runnable_windows  # noqa: E402

RV2 = SweepConfig(
    choices=(
        PhaseChoice("protective_stop", "cloud_protective_stop", (), 0),
        PhaseChoice("exit_hard", "cloud_adherence_trail", (), 0),
        PhaseChoice("sizing", "flat_pct_heatcap", (("position_pct", 0.05),), 0),
        PhaseChoice("exit_rotation", "rotation_v2", (), 0),
    ),
    continuous_weekly=True,
)
FY = Window(name="fy2025_full", start="2025-01-01", end="2025-12-31")


def main() -> None:
    workers = int(os.environ.get("SWEEP_WORKERS", "2"))
    print(f"=== #339 rotation-v2 RUN (RotationV2 on S1 base) {RV2.config_hash} ===", flush=True)
    print("--- FY2025_FULL (vs S1 FLOOR +21.13%/Sharpe1.025; RUN R rotation-v1 -22.8% realized) ---", flush=True)
    m = make_local_run(archive=True)(RV2, FY)
    print(f"    FY-FULL rotation-v2: {m}")
    windows = local_runnable_windows()
    print(f"--- {len(windows)} quarters ---", flush=True)
    gate = WarmupGate() if workers > 1 else None
    out = run_sweep([RV2], make_local_run(warmup_gate=gate), windows=windows, max_workers=workers,
                    pins=("run339-rv2", "rotation-v2", "phase_engine_rv2_v1"), min_windows=len(windows))
    print("\n=== LEADERBOARD ===")
    print(out.leaderboard_csv)
    print(f"failures: {[(f.config.config_hash, f.error[:160]) for f in out.failures]}")
    print("NEXT: floor_proxy.py + grep ROTATION_V2| in the bt log (assert evicted=dead-green-flat).")


if __name__ == "__main__":
    main()
