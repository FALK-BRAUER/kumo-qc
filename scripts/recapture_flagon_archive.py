"""#336/#338 — re-capture the champion FLAG-ON under its own identity (4c2fc8e40607) + archive.

Runs SweepConfig(choices=(), continuous_weekly=True) across the 6 canonical quarterly panels with
archive=True. The config's continuous_weekly field is authoritative — local_dist_builder injects
CONTINUOUS_WEEKLY=True from it, driving BOTH the corrected-weekly behavior AND the distinct
config_hash (4c2fc8e40607 ≠ canonical e3b0c44298fc, which stays untouched).

This run is dual-purpose (HQ): (1) the flag-ON archive the end-to-end gate validates against
(offline-cache vs flag-ON live decisions → 81/81), (2) #339's control candidate A = the corrected
champion's 6-window ROBUSTNESS distribution (answers the 're-baseline was one window' caveat).

Usage: SWEEP_WORKERS=2 python3 scripts/recapture_flagon_archive.py
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
from sweeps.types import SweepConfig  # noqa: E402
from sweeps.windows import SIX_WINDOWS  # noqa: E402


def main() -> None:
    workers = int(os.environ.get("SWEEP_WORKERS", "2"))
    champ = SweepConfig(choices=(), continuous_weekly=True)
    assert champ.config_hash != "e3b0c44298fc", "flag-ON must NOT collide with canonical"
    print(f"=== RE-CAPTURE champion FLAG-ON {champ.config_hash} over {len(SIX_WINDOWS)} quarterly "
          f"panels (archive=True, workers={workers}) ===", flush=True)
    gate = WarmupGate() if workers > 1 else None
    adapter = make_local_run(warmup_gate=gate)  # archive=True default → persists to archive/<hash>/
    pins = ("recapture-flagon", "continuous-weekly-champion", "phase_engine_champion_cw_v1")
    outcome = run_sweep([champ], adapter, windows=SIX_WINDOWS, max_workers=workers, pins=pins)
    print("OUTCOME:", outcome)


if __name__ == "__main__":
    main()
