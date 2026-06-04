"""#364 round-3 HARD-STOP sweep — on the S1 CHAMPION base (no rotation), FY-graded.

S1 (no-rotation, mainV2 f82809f) is the FY champion: Sharpe 1.025 / +27.70% / DD 19.4% / floor +21.13k.
The hard-stop cuts S1's left tail (MRVL−37/UAL−29/BITX−28/AR−23 = the 19.4%-DD drivers) via a static
−X% floor (max(cloud_bottom, entry×(1−X))) while CloudAdherenceTrail lets the +175% winner run. THE
TEST: beat S1 FY — LIFT Sharpe + CUT the 19.4% DD while keeping return ≈+27%. Graded on FY-FULL (the
per-quarter floor is the artifact that mis-ranked rotation; FY is truth). +Q1+Q3 screen.

Usage: SWEEP_CLASS_ATTRS='{"DECISION_TRACE": true}' SWEEP_WORKERS=4 python3 scripts/run_364_r3hardstop.py
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

# S1 base = no rotation, no entry override (= mainV2 champion 65c0cf447168).
_S1_BASE = (
    PhaseChoice("exit_hard", "cloud_adherence_trail", (), 0),
    PhaseChoice("sizing", "flat_pct_heatcap", (("position_pct", 0.05),), 0),
)


def _stop(x: float) -> PhaseChoice:
    return PhaseChoice("protective_stop", "cloud_protective_stop", (("hard_stop_pct", x),), 0)


CONFIGS = [(f"R3hs-{x}", SweepConfig(choices=_S1_BASE + (_stop(x),), continuous_weekly=True))
           for x in (0.08, 0.12, 0.16)]
FY = Window(name="fy2025_full", start="2025-01-01", end="2025-12-31")
Q1 = Window(name="w1_2025q1", start="2025-01-01", end="2025-03-31")
Q3 = Window(name="w3_2025q3", start="2025-07-01", end="2025-09-30")


def main() -> None:
    workers = int(os.environ.get("SWEEP_WORKERS", "4"))
    print("=== #364 round-3 HARD-STOP on S1 base (FY-graded; S1 FY base 65c0cf447168) ===", flush=True)
    for label, cfg in CONFIGS:
        print(f"  {label:10} {cfg.config_hash}", flush=True)
    gate = WarmupGate() if workers > 1 else None
    out = run_sweep([c for _, c in CONFIGS], make_local_run(warmup_gate=gate), windows=[FY, Q1, Q3],
                    max_workers=workers, pins=("run364-r3hs", "hard-stop-S1", "hardstop_v1"),
                    min_windows=3)
    print("\n=== LEADERBOARD ===")
    print(out.leaderboard_csv)
    if out.failures:
        print(f"\nFAILURES: {[(f.config.config_hash, f.error[:300]) for f in out.failures]}")
    print("\nNEXT: FY Sharpe/DD/return + floor per variant vs S1 FY (Sh1.025/+27.70%/DD19.4%/+21.13k) + tail decomp.")


if __name__ == "__main__":
    main()
