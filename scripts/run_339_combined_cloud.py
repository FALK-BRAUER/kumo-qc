"""#339 — the REAL 'hold above cloud' test: BOTH stops at cloud-bottom.

Finding: moving ONLY the protective_stop to cloud-bottom is inert — the daily KijunG3 exit_hard
(close<kijun) still fires at the Kijun (ABOVE cloud-bottom), binding first. To actually hold dips
above the cloud, BOTH the protective floor AND the daily exit must be cloud-based:
  protective_stop = CloudProtectiveStop  +  exit_hard = CloudAdherenceTrail   (hash de53399c8125)

Runs FY2025_FULL FIRST (the headline +X% vs the prior-champion bar: G3 +33.33% / E40d +42.40%),
then the 4 runnable quarters (per-quarter Q1/Q4 lift vs A: Q1 -1.60/Q2 +2.74/Q3 +2.64/Q4 -0.88).
flag-ON, archive=True. Usage: SWEEP_WORKERS=2 python3 scripts/run_339_combined_cloud.py
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

COMBO = SweepConfig(
    choices=(
        PhaseChoice("protective_stop", "cloud_protective_stop", (), 0),
        PhaseChoice("exit_hard", "cloud_adherence_trail", (), 0),
    ),
    continuous_weekly=True,
)
FY = Window(name="fy2025_full", start="2025-01-01", end="2025-12-31")


def main() -> None:
    workers = int(os.environ.get("SWEEP_WORKERS", "2"))
    assert COMBO.config_hash == "de53399c8125", COMBO.config_hash
    print(f"=== #339 COMBINED CLOUD STOPS {COMBO.config_hash} (CloudProtectiveStop + CloudAdherenceTrail) ===", flush=True)

    # 1) FY-full HEADLINE (direct adapter call — single window, bypasses the >=2 mandate)
    print("--- FY2025_FULL (headline vs G3 +33.33% / E40d +42.40%) ---", flush=True)
    m = make_local_run(archive=True)(COMBO, FY)
    print(f"    FY-FULL combined-cloud: {m}")

    # 2) 4 quarters (per-quarter Q1/Q4 lift)
    windows = local_runnable_windows()
    print(f"--- {len(windows)} quarters (Q1/Q4 lift vs A) ---", flush=True)
    gate = WarmupGate() if workers > 1 else None
    out = run_sweep([COMBO], make_local_run(warmup_gate=gate), windows=windows,
                    max_workers=workers, pins=("run339-combo", "cloud-both", "phase_engine_combo_v1"),
                    min_windows=len(windows))
    print("\n=== LEADERBOARD ===")
    print(out.leaderboard_csv)
    print(f"failures: {[(f.config.config_hash, f.error[:160]) for f in out.failures]}")


if __name__ == "__main__":
    main()
