"""#342b SPY-Ichimoku regime gate, T>K-ONLY — the fallback if #342's AND over-blocks Q2/Q3 winners.

Identical to run_342 EXCEPT the gate drops the close>=cloud_bottom condition (require_price_above_
cloud=False). T>K alone blocks the whole Jan 3-14 cohort (SPY T<K the entire window) WITHOUT the
stricter cloud test that risks blocking Q2/Q3 winners where SPY was T>K but briefly dipped toward
cloud (HQ's over-block watch). Run this ONLY if #342 (config 6ee62f5d019a) kills the Jan losers but
also blocks some Q2/Q3 winners (HOOD/KGC/AU/NEM/PAAS/KLAC/GLW/ATI).

config_hash 63fd77710355. Headline same as #342: floor vs +21.13 / realized vs -15.2 / Q1+Q4 panel.
Usage: SWEEP_WORKERS=2 python3 scripts/run_342b_regime_gate_tk_only.py
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

GATE_TK = SweepConfig(
    choices=(
        PhaseChoice("protective_stop", "cloud_protective_stop", (), 0),
        PhaseChoice("exit_hard", "cloud_adherence_trail", (), 0),
        PhaseChoice("sizing", "flat_pct_heatcap", (("position_pct", 0.05),), 0),
        PhaseChoice("regime_ichimoku", "spy_ichimoku_regime",
                    (("enabled", True), ("require_price_above_cloud", False)), 0),
    ),
    continuous_weekly=True,
)
FY = Window(name="fy2025_full", start="2025-01-01", end="2025-12-31")


def main() -> None:
    workers = int(os.environ.get("SWEEP_WORKERS", "2"))
    print(f"=== #342b SPY-Ichimoku T>K-ONLY (S1 base) {GATE_TK.config_hash} ===", flush=True)
    print("--- FY2025_FULL (vs S1 +21.13% floor; vs #342 AND-gate 6ee62f5d019a) ---", flush=True)
    m = make_local_run(archive=True)(GATE_TK, FY)
    print(f"    FY-FULL regime-gate T>K-only: {m}")
    windows = local_runnable_windows()
    print(f"--- {len(windows)} local quarters ---", flush=True)
    gate = WarmupGate() if workers > 1 else None
    out = run_sweep([GATE_TK], make_local_run(warmup_gate=gate), windows=windows, max_workers=workers,
                    pins=("run342b", "spy-ichimoku-tk-only", "phase_engine_regime_gate_v1"),
                    min_windows=len(windows))
    print("\n=== LEADERBOARD ===")
    print(out.leaderboard_csv)
    print(f"failures: {[(f.config.config_hash, f.error[:160]) for f in out.failures]}")


if __name__ == "__main__":
    main()
