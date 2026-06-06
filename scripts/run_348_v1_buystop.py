"""#348 batch-1 V1 — BuyStopBreakoutConfirm on the S1 base, the 2 screen windows (Q1 bear + Q3 bull).

V1 = S1 (CloudProtectiveStop + CloudAdherenceTrail + FlatPctHeatcap 0.05 + CONTINUOUS_WEEKLY) with the
entry_selection ALGO swapped to buy_stop_breakout_confirm (+0.75% buy-stop, full-session window). ONE
variable vs S1. DECISION_TRACE ON → trace + non-trades for the name-level read.

Screen windows: w1_2025q1 (BEAR, S1 floor baseline -8.1% Sharpe -0.999) + w3_2025q3 (BULL). Headline =
floor-proxy per window vs S1. assert ENGAGED: buy-stop FIRES > 0 (else inert). Name-level: HOOD fires
(breakout), MRVL drops (chop); does the entered set's floor beat S1 on the SAME signal pool?
Usage: SWEEP_WORKERS=2 python3 scripts/run_348_v1_buystop.py
"""
from __future__ import annotations

import json as _json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_ROOT), str(_ROOT / "src"), str(_ROOT / "scripts")]

os.environ.setdefault("DOCKER_HOST", "unix:///Users/falk/.docker/run/docker.sock")
os.environ["SWEEP_CLASS_ATTRS"] = _json.dumps({"DECISION_TRACE": True})

from sweeps.adapters.local_lean import WarmupGate  # noqa: E402
from sweeps.adapters.qc_local_prod import make_local_run  # noqa: E402
from sweeps.run_sweep import run_sweep  # noqa: E402
from sweeps.types import PhaseChoice, SweepConfig, Window  # noqa: E402

V1 = SweepConfig(
    choices=(
        PhaseChoice("protective_stop", "cloud_protective_stop", (), 0),
        PhaseChoice("exit_hard", "cloud_adherence_trail", (), 0),
        PhaseChoice("sizing", "flat_pct_heatcap", (("position_pct", 0.05),), 0),
        PhaseChoice("entry_selection", "buy_stop_breakout_confirm", (), 0),
    ),
    continuous_weekly=True,
)
SCREEN = (
    Window(name="w1_2025q1", start="2025-01-01", end="2025-03-31"),
    Window(name="w3_2025q3", start="2025-07-01", end="2025-09-30"),
)


def main() -> None:
    workers = int(os.environ.get("SWEEP_WORKERS", "2"))
    print(f"=== #348 V1 BuyStopBreakoutConfirm {V1.config_hash} on Q1+Q3 (DECISION_TRACE ON) ===", flush=True)
    gate = WarmupGate() if workers > 1 else None
    out = run_sweep([V1], make_local_run(archive=True, warmup_gate=gate), windows=SCREEN,
                    max_workers=workers, pins=("run348-v1", "buystop", "phase_engine_v1_buystop"),
                    min_windows=len(SCREEN))
    print("\n=== LEADERBOARD ===")
    print(out.leaderboard_csv)
    print(f"failures: {[(f.config.config_hash, f.error[:160]) for f in out.failures]}")
    print("NEXT: floor_proxy (add V1 hash) per window vs S1; grep buy_stop confirm fires;"
          " instrument_analysis non-trades — did HOOD fire / MRVL drop / win-rate beat S1?")


if __name__ == "__main__":
    main()
