"""#364 R1 rotation tournament — gain-floor vs quality-gate vs both, on the S1 base, Q1+Q3 2025.

HQ-reshaped R1 (the no-floor rotation_v2 is the known #345 floor-loser +10.18% vs S1 +21.13% — don't
re-run it). All 3 variants DEPART from no-floor; shared core = positive-but-flat candidate, protect
≥Tenkan + underwater, trigger cash-exhausted + fresh-score-edge, evict_select=momentum:
  - R1-A = GAIN-FLOOR only (unrealized gain% >= +10%; the never-built "v2b").
  - R1-B = QUALITY-GATE only (ADX-falling AND no-new-high-10d).
  - R1-C = BOTH (gain-floor + quality-gate).
  - S1-REF = no rotation (the baseline bar to beat; same-window floor-proxy).
WIN = a variant's floor-proxy >= S1-REF on BOTH Q1 AND Q3 → rotation finally viable.

Usage: SWEEP_WORKERS=4 python3 scripts/run_364_r1_tournament.py
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

# Shared S1 base: cloud protective-stop + cloud-adherence trail + flat 5% heatcap, continuous-weekly.
_BASE = (
    PhaseChoice("protective_stop", "cloud_protective_stop", (), 0),
    PhaseChoice("exit_hard", "cloud_adherence_trail", (), 0),
    PhaseChoice("sizing", "flat_pct_heatcap", (("position_pct", 0.05),), 0),
)


def _rot(params: tuple) -> PhaseChoice:
    return PhaseChoice("exit_rotation", "rotation_v2", params, 0)


# evict_select=momentum on all rotation variants (HQ R1 spec).
R1_A = SweepConfig(choices=_BASE + (_rot((("evict_select", "momentum"), ("gain_floor_pct", 0.10))),),
                   continuous_weekly=True)
R1_B = SweepConfig(choices=_BASE + (_rot((("evict_select", "momentum"), ("adx_falling_gate", True),
                                          ("no_new_high_days", 10))),), continuous_weekly=True)
R1_C = SweepConfig(choices=_BASE + (_rot((("evict_select", "momentum"), ("gain_floor_pct", 0.10),
                                          ("adx_falling_gate", True), ("no_new_high_days", 10))),),
                   continuous_weekly=True)
S1_REF = SweepConfig(choices=_BASE, continuous_weekly=True)  # no rotation = the baseline

CONFIGS = [("R1-A_gainfloor", R1_A), ("R1-B_qualitygate", R1_B), ("R1-C_both", R1_C), ("S1-ref", S1_REF)]
Q1 = Window(name="w1_2025q1", start="2025-01-01", end="2025-03-31")
Q3 = Window(name="w3_2025q3", start="2025-07-01", end="2025-09-30")


def main() -> None:
    workers = int(os.environ.get("SWEEP_WORKERS", "4"))
    print("=== #364 R1 rotation tournament (gain-floor vs quality-gate vs both vs S1-ref) ===", flush=True)
    for label, cfg in CONFIGS:
        print(f"  {label:18} {cfg.config_hash}", flush=True)
    gate = WarmupGate() if workers > 1 else None
    out = run_sweep([c for _, c in CONFIGS], make_local_run(warmup_gate=gate), windows=[Q1, Q3],
                    max_workers=workers, pins=("run364-r1", "rotation-tournament", "rv2_tourney_v1"),
                    min_windows=2)
    print("\n=== LEADERBOARD (per-window trio) ===")
    print(out.leaderboard_csv)
    if out.failures:
        print(f"\nFAILURES: {[(f.config.config_hash, f.error[:200]) for f in out.failures]}")
    print("\nNEXT: floor_proxy.py per config_hash (Q1+Q3) + export_ledgers + grep ROTATION_V2| "
          "(which evicted / gain banked / did any evicted then run = false-stall diagnostic).")


if __name__ == "__main__":
    main()
