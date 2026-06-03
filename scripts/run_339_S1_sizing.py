"""#339 RUN S1 — SIZING (position 10%→5%) on the combined-cloud base. ONE variable.

Config 65c0cf447168 = CloudProtectiveStop + CloudAdherenceTrail + FlatPctHeatcap(position_pct=0.05).
Hypothesis (research-grounded, HQ): smaller slots (5% → ~20 concurrent) fit more of the 217
cash-blocked entries → more trades + more realized, WITHOUT touching winners (no churn, unlike
rotation which HURT: -22.8% realized). The structural capacity fix.

vs combined-cloud (de53399c8125): -16.9% realized / +23.37% total / 18 trades. vs RUN R rotation:
+16.98% / -22.8% / 38 (churn hurt). vs bar G3 +33% / E40d +42%. assert: trades >> 18.
FY-full first, then 4 quarters. Usage: SWEEP_WORKERS=2 python3 scripts/run_339_S1_sizing.py
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

S1 = SweepConfig(
    choices=(
        PhaseChoice("protective_stop", "cloud_protective_stop", (), 0),
        PhaseChoice("exit_hard", "cloud_adherence_trail", (), 0),
        PhaseChoice("sizing", "flat_pct_heatcap", (("position_pct", 0.05),), 0),
    ),
    continuous_weekly=True,
)
FY = Window(name="fy2025_full", start="2025-01-01", end="2025-12-31")


def main() -> None:
    workers = int(os.environ.get("SWEEP_WORKERS", "2"))
    assert S1.config_hash == "65c0cf447168", S1.config_hash
    print(f"=== #339 RUN S1 (sizing 5% on combined-cloud) {S1.config_hash} ===", flush=True)
    print("--- FY2025_FULL (vs combined-cloud -16.9%/+23.37%/18; rotation +16.98%/-22.8%/38) ---", flush=True)
    m = make_local_run(archive=True)(S1, FY)
    print(f"    FY-FULL run-S1: {m}")
    windows = local_runnable_windows()
    print(f"--- {len(windows)} quarters ---", flush=True)
    gate = WarmupGate() if workers > 1 else None
    out = run_sweep([S1], make_local_run(warmup_gate=gate), windows=windows, max_workers=workers,
                    pins=("run339-S1", "sizing-5pct", "phase_engine_S1_v1"), min_windows=len(windows))
    print("\n=== LEADERBOARD ===")
    print(out.leaderboard_csv)
    print(f"failures: {[(f.config.config_hash, f.error[:160]) for f in out.failures]}")


if __name__ == "__main__":
    main()
