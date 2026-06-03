"""#342 SPY-Ichimoku regime gate RUN — S1 base + SpyIchimokuRegime. ONE variable.

Config = CloudProtectiveStop + CloudAdherenceTrail + FlatPctHeatcap(0.05) + CONTINUOUS_WEEKLY (= the
S1 champion) PLUS regime_ichimoku spy_ichimoku_regime (Tenkan>Kijun AND price>=cloud_bottom on SPY).
vs S1 (no extra regime gate): FLOOR +21.13% / Sharpe 1.025 / REALIZED -15.2% / 36 trades.

Target (#346 January massacre): 17/19 S1 closed losers entered Jan 3-14 2025 — SPY T<K the whole
window. The gate must SUPPRESS those entries (Q1 lift) WITHOUT blocking the Q2/Q3 winners (SPY T>K
from Jan 27 on). Headline: floor-proxy vs +21.13, REALIZED vs -15.2 (killing Jan losers should LIFT
realized), and the WINDOW PANEL — Q1 (was -1.60) / Q4 (was -0.88) lift; gate clears at >=4/6 positive.

Scope: LOCAL (4 runnable 2025 quarters + FY-FULL). w5/w6 (2026) are cloud-deferred.
assert-engaged: count entries BLOCKED in the Jan-chop window (target most of the 17); confirm Q2/Q3
winners still enter. FY-FULL first.
Usage: SWEEP_WORKERS=2 python3 scripts/run_342_regime_gate.py
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

GATE = SweepConfig(
    choices=(
        PhaseChoice("protective_stop", "cloud_protective_stop", (), 0),
        PhaseChoice("exit_hard", "cloud_adherence_trail", (), 0),
        PhaseChoice("sizing", "flat_pct_heatcap", (("position_pct", 0.05),), 0),
        PhaseChoice("regime_ichimoku", "spy_ichimoku_regime", (("enabled", True),), 0),
    ),
    continuous_weekly=True,
)
FY = Window(name="fy2025_full", start="2025-01-01", end="2025-12-31")


def main() -> None:
    workers = int(os.environ.get("SWEEP_WORKERS", "2"))
    print(f"=== #342 SPY-Ichimoku regime gate RUN (S1 base + SpyIchimokuRegime) {GATE.config_hash} ===", flush=True)
    print("--- FY2025_FULL (vs S1 FLOOR +21.13% / Sharpe 1.025 / REALIZED -15.2% / 36T) ---", flush=True)
    m = make_local_run(archive=True)(GATE, FY)
    print(f"    FY-FULL regime-gate: {m}")
    windows = local_runnable_windows()
    print(f"--- {len(windows)} local quarters (Q1 was -1.60, Q4 was -0.88 — the gate's targets) ---", flush=True)
    gate = WarmupGate() if workers > 1 else None
    out = run_sweep([GATE], make_local_run(warmup_gate=gate), windows=windows, max_workers=workers,
                    pins=("run342", "spy-ichimoku-regime", "phase_engine_regime_gate_v1"),
                    min_windows=len(windows))
    print("\n=== LEADERBOARD ===")
    print(out.leaderboard_csv)
    print(f"failures: {[(f.config.config_hash, f.error[:160]) for f in out.failures]}")
    print("NEXT: floor_proxy.py (add 6ee62f5d019a); grep 'spy_ichimoku' bt log for blocked-Jan count;"
          " export_ledgers (add gate) → did Jan losers vanish + Q2/Q3 winners survive.")


if __name__ == "__main__":
    main()
