"""#352 — generate the Q2 + Q4 panel data: S1 base on w2_2025q2 + w4_2025q4 with DECISION_TRACE on.

Completes the 4-quarter set (Q1+Q3 already traced) so the regime-conditional composite gets WITHIN-
regime OOS holdout (HQ #352): BEAR pair Q1+Q4, BULL pair Q2+Q3 → fit one, test the OTHER same-regime
window. S1 config (65c0cf447168), trace emits the scored candidates (entered + non-entered).
Usage: SWEEP_WORKERS=2 python3 scripts/run_348_q2q4_trace.py
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

S1 = SweepConfig(
    choices=(
        PhaseChoice("protective_stop", "cloud_protective_stop", (), 0),
        PhaseChoice("exit_hard", "cloud_adherence_trail", (), 0),
        PhaseChoice("sizing", "flat_pct_heatcap", (("position_pct", 0.05),), 0),
    ),
    continuous_weekly=True,
)
WINDOWS = (
    Window(name="w2_2025q2", start="2025-04-01", end="2025-06-30"),
    Window(name="w4_2025q4", start="2025-10-01", end="2025-12-31"),
)


def main() -> None:
    workers = int(os.environ.get("SWEEP_WORKERS", "2"))
    print(f"=== #352 Q2+Q4 trace: S1 {S1.config_hash} (DECISION_TRACE ON) ===", flush=True)
    gate = WarmupGate() if workers > 1 else None
    out = run_sweep([S1], make_local_run(archive=True, warmup_gate=gate), windows=WINDOWS,
                    max_workers=workers, pins=("run348-q2q4", "trace", "phase_engine_q2q4_trace"),
                    min_windows=len(WINDOWS))
    print("\n=== LEADERBOARD ===")
    print(out.leaderboard_csv)
    print(f"failures: {[(f.config.config_hash, f.error[:160]) for f in out.failures]}")
    print("NEXT: within-regime OOS — fit-Q1->test-Q4 + fit-Q4->test-Q1 (bear); fit-Q2->test-Q3 +"
          " fit-Q3->test-Q2 (bull). DECISIONTRACE in the w2/w4 bt logs.")


if __name__ == "__main__":
    main()
