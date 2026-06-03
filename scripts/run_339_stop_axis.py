"""#339 (re-scoped) — the PROTECTIVE-STOP axis: the champion's BINDING exit.

The #339 finding: the daily exit_hard is inert; the binding exit is the protective GTC stop_market.
So the real lever is the STOP LEVEL. This runs the cloud-bottom stop variant vs the Kijun base:
  A = KijunProtectiveStop  (4c2fc8e40607 — base, ALREADY captured: Q1 -1.60/Q2 +2.74/Q3 +2.64/Q4 -0.88)
  S = CloudProtectiveStop  (3af57b1f5d7d — GTC stop at cloud-bottom; the G3-winning CloudBottomStop)
THE test: does the cloud-bottom stop HOLD the Q1/Q4 dips the Kijun stop realizes → lift Q1/Q4?

Runs S only (A reused from cache) on the 4 runnable 2025 quarters, flag-ON, archive=True.
Usage: SWEEP_WORKERS=2 python3 scripts/run_339_stop_axis.py
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
from sweeps.types import PhaseChoice, SweepConfig  # noqa: E402
from sweeps.windows import local_runnable_windows  # noqa: E402

CLOUD_STOP = SweepConfig(
    choices=(PhaseChoice("protective_stop", "cloud_protective_stop", (), 0),),
    continuous_weekly=True,
)


def main() -> None:
    workers = int(os.environ.get("SWEEP_WORKERS", "2"))
    windows = local_runnable_windows()
    assert CLOUD_STOP.config_hash == "3af57b1f5d7d", CLOUD_STOP.config_hash
    print(f"=== #339 STOP-AXIS: CloudProtectiveStop {CLOUD_STOP.config_hash} x {len(windows)} quarters "
          f"(workers={workers}). A=4c2fc8e40607 (Kijun stop) reused. ===", flush=True)
    gate = WarmupGate() if workers > 1 else None
    adapter = make_local_run(warmup_gate=gate)  # archive=True
    pins = ("run339-stopaxis", "cloud-protective-stop", "phase_engine_stop_v1")
    outcome = run_sweep([CLOUD_STOP], adapter, windows=windows, max_workers=workers, pins=pins,
                        min_windows=len(windows))
    print("\n=== LEADERBOARD ===")
    print(outcome.leaderboard_csv)
    print(f"failures: {[(f.config.config_hash, f.error[:160]) for f in outcome.failures]}")


if __name__ == "__main__":
    main()
