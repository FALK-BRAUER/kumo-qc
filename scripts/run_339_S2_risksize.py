"""#339 RUN S2 — RISK-BASED sizing on the combined-cloud base. ONE variable vs S1 (flat 5% → risk).

Config 847e70eb93ea = CloudProtectiveStop + CloudAdherenceTrail + RiskBasedSize($500 risk, cap 10%).
Hypothesis: risk-normalized slots (size = $500 ÷ (entry−cloud_bottom), capped 10%) fit even more names
+ size winners-vs-choppy better → push FLOOR-PROXY past S1's +21.13%. assert: sizes VARY by name.

vs S1 flat-5% (65c0cf447168): M2M +27.69% / realized -15.2% / FLOOR +21.13% / Sharpe 1.025 / 17 open.
FLOOR-PROXY = the headline metric (run scripts/floor_proxy.py after). FY-full first, then 4 quarters.
Usage: SWEEP_WORKERS=2 python3 scripts/run_339_S2_risksize.py
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

S2 = SweepConfig(
    choices=(
        PhaseChoice("protective_stop", "cloud_protective_stop", (), 0),
        PhaseChoice("exit_hard", "cloud_adherence_trail", (), 0),
        PhaseChoice("sizing", "risk_based_size", (), 0),
    ),
    continuous_weekly=True,
)
FY = Window(name="fy2025_full", start="2025-01-01", end="2025-12-31")


def main() -> None:
    workers = int(os.environ.get("SWEEP_WORKERS", "2"))
    assert S2.config_hash == "847e70eb93ea", S2.config_hash
    print(f"=== #339 RUN S2 (risk-based sizing on combined-cloud) {S2.config_hash} ===", flush=True)
    print("--- FY2025_FULL (vs S1 flat-5%: +27.69%M2M/-15.2%real/+21.13%FLOOR/1.025/17open) ---", flush=True)
    m = make_local_run(archive=True)(S2, FY)
    print(f"    FY-FULL run-S2: {m}")
    windows = local_runnable_windows()
    print(f"--- {len(windows)} quarters ---", flush=True)
    gate = WarmupGate() if workers > 1 else None
    out = run_sweep([S2], make_local_run(warmup_gate=gate), windows=windows, max_workers=workers,
                    pins=("run339-S2", "risk-sizing", "phase_engine_S2_v1"), min_windows=len(windows))
    print("\n=== LEADERBOARD ===")
    print(out.leaderboard_csv)
    print(f"failures: {[(f.config.config_hash, f.error[:160]) for f in out.failures]}")
    print("NEXT: python3 scripts/floor_proxy.py (add 847e70eb93ea) for the bankable headline.")


if __name__ == "__main__":
    main()
