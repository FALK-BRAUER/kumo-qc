"""#348 SAMPLE run — S1 champion on w1_2025q1 with DECISION_TRACE on (the instrumentation sample).

Runs the S1 base (CloudProtectiveStop + CloudAdherenceTrail + FlatPctHeatcap 0.05 + CONTINUOUS_WEEKLY
= config_hash 65c0cf447168, NO regime gate) on w1_2025q1 (the bimodal Jan-discrimination window) with
the BCTAlgorithm DECISION_TRACE class-attr ON (via SWEEP_CLASS_ATTRS) → emits DECISIONTRACE log lines
(the NON-TRADES substrate) into the bt log.txt.

Double duty: (1) PARITY — orders must match the prior S1 w1 cell (the feature-capture fix #1 is
metadata-only, trade-identical); (2) the ex-CORE_MISSING names (HOOD/VST/BITX/IBIT in Q1) must now
carry score+conditions; (3) feeds the 3-artifact sample (trades / non-trades / exit-leakage).
Usage: python3 scripts/run_348_sample.py
"""
from __future__ import annotations

import json as _json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_ROOT), str(_ROOT / "src"), str(_ROOT / "scripts")]

os.environ.setdefault("DOCKER_HOST", "unix:///Users/falk/.docker/run/docker.sock")
# enable the #348 decision-trace via the established class-attr injection lever
os.environ["SWEEP_CLASS_ATTRS"] = _json.dumps({"DECISION_TRACE": True})

from sweeps.adapters.qc_local_prod import make_local_run  # noqa: E402
from sweeps.types import PhaseChoice, SweepConfig, Window  # noqa: E402

S1 = SweepConfig(
    choices=(
        PhaseChoice("protective_stop", "cloud_protective_stop", (), 0),
        PhaseChoice("exit_hard", "cloud_adherence_trail", (), 0),
        PhaseChoice("sizing", "flat_pct_heatcap", (("position_pct", 0.05),), 0),
    ),
    continuous_weekly=True,
)
W1 = Window(name="w1_2025q1", start="2025-01-01", end="2025-03-31")


def main() -> None:
    print(f"=== #348 SAMPLE: S1 {S1.config_hash} on {W1.name} (DECISION_TRACE ON) ===", flush=True)
    m = make_local_run(archive=True)(S1, W1)
    print(f"    w1_2025q1 S1 (traced): {m}")
    print("NEXT: instrument_analysis non-trades + exit-leakage on this cell; grep DECISIONTRACE in the"
          " bt log.txt; assert ex-CORE_MISSING names now carry score+conditions.")


if __name__ == "__main__":
    main()
