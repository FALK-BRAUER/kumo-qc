"""#339 RUN R — ROTATION only, on the combined-cloud base (clean attribution: one lever).

Config 6432fc649c54 = CloudProtectiveStop + CloudAdherenceTrail (the combined-cloud let-winners base)
+ Rotation. NO profit-take. Question: does freeing cash-locked slots (the 217 blocked entries) fix
the 18-trade lockup + lift the realized edge? vs combined-cloud (-16.9% realized / +23.37% total /
18 trades). assert-engaged: rotation count > 0 (else inert → investigate). Success = trades >> 18 +
realized up.

FY2025_FULL first (the headline), then 4 quarters. Usage: SWEEP_WORKERS=2 python3 scripts/run_339_R_rotation.py
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

RUN_R = SweepConfig(
    choices=(
        PhaseChoice("protective_stop", "cloud_protective_stop", (), 0),
        PhaseChoice("exit_hard", "cloud_adherence_trail", (), 0),
        PhaseChoice("exit_rotation", "rotation", (), 0),
    ),
    continuous_weekly=True,
)
FY = Window(name="fy2025_full", start="2025-01-01", end="2025-12-31")


def main() -> None:
    workers = int(os.environ.get("SWEEP_WORKERS", "2"))
    assert RUN_R.config_hash == "6432fc649c54", RUN_R.config_hash
    print(f"=== #339 RUN R (rotation on combined-cloud) {RUN_R.config_hash} ===", flush=True)
    print("--- FY2025_FULL (headline vs combined-cloud: -16.9% realized/+23.37% total/18 trades) ---", flush=True)
    m = make_local_run(archive=True)(RUN_R, FY)
    print(f"    FY-FULL run-R: {m}")
    windows = local_runnable_windows()
    print(f"--- {len(windows)} quarters ---", flush=True)
    gate = WarmupGate() if workers > 1 else None
    out = run_sweep([RUN_R], make_local_run(warmup_gate=gate), windows=windows, max_workers=workers,
                    pins=("run339-R", "rotation-only", "phase_engine_R_v1"), min_windows=len(windows))
    print("\n=== LEADERBOARD ===")
    print(out.leaderboard_csv)
    print(f"failures: {[(f.config.config_hash, f.error[:160]) for f in out.failures]}")


if __name__ == "__main__":
    main()
