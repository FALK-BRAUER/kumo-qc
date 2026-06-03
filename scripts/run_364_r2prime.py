"""#364 Round-2' VOL-FLOOR tune — the ONE robust lever (#364 robustness gate). On R1-C base, Q1+Q3.

decision_vol = last_bar.volume/mean_vol (the intraday vol-RATIO at the gap-vol confirm) == exactly
what vol_mult gates → vol-floor @ X ≡ vol_mult=X. So the triplet is a pure vol_mult tune (zero new
capability): require a LOUDER open (≥6.5/7.0/7.5× baseline vs the base 1.0×) → cut the low-vol loser
cohort (bottom vol-tercile: 31% win/-7.9% vs mid 58%/+7.1%). gap_threshold stays at the base 0.03
(gap-band was NOT robust — dropped). DECISION_TRACE on (SWEEP_CLASS_ATTRS env) → non-trade ledgers.

Usage: SWEEP_CLASS_ATTRS='{"DECISION_TRACE": true}' SWEEP_WORKERS=4 python3 scripts/run_364_r2prime.py
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

_R1C_BASE = (
    PhaseChoice("protective_stop", "cloud_protective_stop", (), 0),
    PhaseChoice("exit_hard", "cloud_adherence_trail", (), 0),
    PhaseChoice("sizing", "flat_pct_heatcap", (("position_pct", 0.05),), 0),
    PhaseChoice("exit_rotation", "rotation_v2",
                (("evict_select", "momentum"), ("gain_floor_pct", 0.10),
                 ("adx_falling_gate", True), ("no_new_high_days", 10)), 0),
)


def _volfloor(vm: float) -> PhaseChoice:
    return PhaseChoice("entry_selection", "bct_intraday_gap_vol_confirm",
                       (("gap_threshold", 0.03), ("vol_mult", vm), ("window_bars", 6)), 0)


CONFIGS = [(f"R2p-{vm}_volfloor", SweepConfig(choices=_R1C_BASE + (_volfloor(vm),),
                                              continuous_weekly=True)) for vm in (6.5, 7.0, 7.5)]
Q1 = Window(name="w1_2025q1", start="2025-01-01", end="2025-03-31")
Q3 = Window(name="w3_2025q3", start="2025-07-01", end="2025-09-30")


def main() -> None:
    workers = int(os.environ.get("SWEEP_WORKERS", "4"))
    print("=== #364 R2' vol-floor tune (vol_mult 6.5/7.0/7.5 on R1-C base; baseline 9f5ed2fd520a) ===", flush=True)
    for label, cfg in CONFIGS:
        print(f"  {label:20} {cfg.config_hash}", flush=True)
    gate = WarmupGate() if workers > 1 else None
    out = run_sweep([c for _, c in CONFIGS], make_local_run(warmup_gate=gate), windows=[Q1, Q3],
                    max_workers=workers, pins=("run364-r2prime", "vol-floor", "volfloor_v1"),
                    min_windows=2)
    print("\n=== LEADERBOARD ===")
    print(out.leaderboard_csv)
    if out.failures:
        print(f"\nFAILURES: {[(f.config.config_hash, f.error[:300]) for f in out.failures]}")
    print("\nNEXT: floor-proxy + winrate + entry-counts vs R1-C base + DECISIONTRACE| non-trade ledger.")


if __name__ == "__main__":
    main()
