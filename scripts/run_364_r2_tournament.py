"""#364 R2 profit-take tournament — layered on the R1-C base (the floor winner). Q1+Q3 2025.

R1 winner R1-C = rotation_v2(evict_select=momentum, gain_floor 0.10, adx_falling, no_new_high_10d) —
protects runners, recycles only truly-dead. R2 adds the OTHER half: bank the protected BULL runners
at/near the peak (the #270 pure-let-run champion never booked → realized-negative). Synthesis =
protect-the-runner (R1-C) AND realize-it-at-top (R2 trailing profit-take).

3 modes (one-lever-diff), all on the R1-C base; baseline-to-beat = R1-C itself (9f5ed2fd520a):
  - R2-A partial_trim     : ½ at +20%, rest trails Kijun.
  - R2-B tenkan_ratchet   : ratcheting trail (Tenkan tight → Kijun post-cross, never lower).
  - R2-C scale_out_ladder : ⅓ +20% / ⅓ +40% / ⅓ on Kijun-break.
floor-proxy decides (≥ R1-C base on both windows = R2 lever adds).

Usage: SWEEP_WORKERS=4 python3 scripts/run_364_r2_tournament.py
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

# R1-C base = S1 base + the winning rotation (both gates, momentum-select, gain-floor).
_R1C_BASE = (
    PhaseChoice("protective_stop", "cloud_protective_stop", (), 0),
    PhaseChoice("exit_hard", "cloud_adherence_trail", (), 0),
    PhaseChoice("sizing", "flat_pct_heatcap", (("position_pct", 0.05),), 0),
    PhaseChoice("exit_rotation", "rotation_v2",
                (("evict_select", "momentum"), ("gain_floor_pct", 0.10),
                 ("adx_falling_gate", True), ("no_new_high_days", 10)), 0),
)


def _pt(mode: str) -> PhaseChoice:
    return PhaseChoice("exit_target", "profit_take", (("mode", mode), ("enabled", True)), 0)


R2_A = SweepConfig(choices=_R1C_BASE + (_pt("partial_trim"),), continuous_weekly=True)
R2_B = SweepConfig(choices=_R1C_BASE + (_pt("tenkan_ratchet"),), continuous_weekly=True)
R2_C = SweepConfig(choices=_R1C_BASE + (_pt("scale_out_ladder"),), continuous_weekly=True)
CONFIGS = [("R2-A_partial_trim", R2_A), ("R2-B_tenkan_ratchet", R2_B), ("R2-C_scale_ladder", R2_C)]
Q1 = Window(name="w1_2025q1", start="2025-01-01", end="2025-03-31")
Q3 = Window(name="w3_2025q3", start="2025-07-01", end="2025-09-30")


def main() -> None:
    workers = int(os.environ.get("SWEEP_WORKERS", "4"))
    print("=== #364 R2 profit-take tournament (on R1-C base; baseline 9f5ed2fd520a) ===", flush=True)
    for label, cfg in CONFIGS:
        print(f"  {label:20} {cfg.config_hash}", flush=True)
    gate = WarmupGate() if workers > 1 else None
    out = run_sweep([c for _, c in CONFIGS], make_local_run(warmup_gate=gate), windows=[Q1, Q3],
                    max_workers=workers, pins=("run364-r2", "profit-take", "pt_tourney_v1"),
                    min_windows=2)
    print("\n=== LEADERBOARD ===")
    print(out.leaderboard_csv)
    if out.failures:
        print(f"\nFAILURES: {[(f.config.config_hash, f.error[:300]) for f in out.failures]}")
    print("\nNEXT: windowed floor-proxy per config_hash vs R1-C base + grep PROFIT_TAKE| ledgers.")


if __name__ == "__main__":
    main()
