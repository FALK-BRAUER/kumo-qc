"""#364 champion-candidate 6-window validate — the daylight gate. Runs the resolved champion across
the full LOCAL panel (w1-w4 2025 quarters + FY2025; w5/w6 are 2026 cloud-only, deferred).

CHAMPION selector (set CHAMPION at the bottom per the R3 result):
  - "R1C"      = R1-C as-is (rotation both-gates) — the standing champion candidate. Use if no R3
                 variant beats R1-C on BOTH Q1+Q3.
  - "R1C_R3B"  = R1-C + R3-B looser-entry (gap_vol 0.02/0.8/6) — use ONLY if R3-B won BOTH windows.
The validate stress-tests across the panel: a Q1+Q3 win is necessary but not sufficient — looser
breadth (R3-B) gets its dilution-risk tested in Q2/Q4. floor-proxy per window is the gate.

Usage: SWEEP_WORKERS=4 python3 scripts/run_364_validate.py
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

_R1C_BASE = (
    PhaseChoice("protective_stop", "cloud_protective_stop", (), 0),
    PhaseChoice("exit_hard", "cloud_adherence_trail", (), 0),
    PhaseChoice("sizing", "flat_pct_heatcap", (("position_pct", 0.05),), 0),
    PhaseChoice("exit_rotation", "rotation_v2",
                (("evict_select", "momentum"), ("gain_floor_pct", 0.10),
                 ("adx_falling_gate", True), ("no_new_high_days", 10)), 0),
)
_R3B_ENTRY = PhaseChoice("entry_selection", "bct_intraday_gap_vol_confirm",
                         (("gap_threshold", 0.02), ("vol_mult", 0.8), ("window_bars", 6)), 0)

R1C = SweepConfig(choices=_R1C_BASE, continuous_weekly=True)
R1C_R3B = SweepConfig(choices=_R1C_BASE + (_R3B_ENTRY,), continuous_weekly=True)
# S1-ref = no rotation (the R1 baseline, hash 65c0cf447168) — for the PAIRED R1-C-vs-S1 edge table.
# Drop the exit_rotation choice from the base.
_S1REF_BASE = tuple(c for c in _R1C_BASE if c.kind != "exit_rotation")
S1REF = SweepConfig(choices=_S1REF_BASE, continuous_weekly=True)

_CHAMPIONS = {"R1C": R1C, "R1C_R3B": R1C_R3B, "S1REF": S1REF}
CHAMPION = os.environ.get("CHAMPION", "R1C")  # set via env on launch per the R3 result
FY = Window(name="fy2025_full", start="2025-01-01", end="2025-12-31")
# Optional comma-separated window filter (e.g. WINDOWS=w2_2025q2,w4_2025q4,fy2025_full for the
# S1-ref panel — Q1/Q3 S1-ref already exist from R1). Empty = the full local panel + FY.
_WIN_FILTER = {w for w in os.environ.get("WINDOWS", "").split(",") if w}


def main() -> None:
    workers = int(os.environ.get("SWEEP_WORKERS", "4"))
    cfg = _CHAMPIONS[CHAMPION]
    windows = list(local_runnable_windows()) + [FY]
    if _WIN_FILTER:
        windows = [w for w in windows if w.name in _WIN_FILTER]
    print(f"=== #364 VALIDATE champion={CHAMPION} {cfg.config_hash} over {len(windows)} windows ===", flush=True)
    for w in windows:
        print(f"  {w.name} {w.start}..{w.end}", flush=True)
    gate = WarmupGate() if workers > 1 else None
    out = run_sweep([cfg], make_local_run(warmup_gate=gate), windows=windows, max_workers=workers,
                    pins=("run364-validate", CHAMPION, "validate_v1"), min_windows=len(windows))
    print("\n=== LEADERBOARD ===")
    print(out.leaderboard_csv)
    if out.failures:
        print(f"\nFAILURES: {[(f.config.config_hash, f.error[:300]) for f in out.failures]}")
    print(f"\nNEXT: windowed floor-proxy {cfg.config_hash} across all panel windows (the validate gate).")


if __name__ == "__main__":
    main()
