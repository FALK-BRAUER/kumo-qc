"""#386 2b→2c GATE: the REAL assertion-live run. DIRECT codegen of the m1_arm_parity strategy module
(cp.build's AST import-closure pulls StubArm → arm IS in the dist → _assert_arm_parity fires each daily
decision). The sweep SweepConfig(arm) path DROPS arm (vacuous) — this replaces it.

Gate PASS = the run completes AND stub_arm_v2 markers > 0 (arm actually ran) AND zero DegradedDataError/
ARM-PARITY (the assertion never diverged across ~63 daily decisions) = empirical arm==snapshot proof.

Usage: python3 scripts/run_386_arm_direct.py <q1|fy>
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_ROOT), str(_ROOT / "src"), str(_ROOT / "scripts")]
os.environ.setdefault("DOCKER_HOST", "unix:///Users/falk/.docker/run/docker.sock")

import build.cloud_package as cp  # noqa: E402
from sweeps.adapters.local_lean import _default_find_result, _default_run_lean  # noqa: E402
from sweeps.types import Window  # noqa: E402

WINDOWS = {
    "q1": Window(name="w1_2025q1", start="2025-01-01", end="2025-03-31"),
    "fy": Window(name="fy2025_full", start="2025-01-01", end="2025-12-31"),
}


def main() -> None:
    win = WINDOWS[sys.argv[1] if len(sys.argv) > 1 else "q1"]
    module = sys.argv[2] if len(sys.argv) > 2 else "strategies.m1_arm_parity"
    tag = module.split(".")[-1]
    run = _ROOT / "sweeps" / "runs" / f"direct_{tag}" / win.name
    if run.exists():
        shutil.rmtree(run)
    run.mkdir(parents=True)

    res = cp.build(module, dist_dir=run)
    print(f"=== #386 arm-direct | config_hash={res.config_hash} | win={win.name} ===", flush=True)
    arm_files = [f for f in res.included if "arm" in f.lower()]
    print(f"arm phase in dist: {arm_files}", flush=True)
    assert arm_files, "FAIL: StubArm not codegen'd — abort (would be vacuous)"

    # window inject (the cloud-parity BCTAlgorithm class-attr pattern; m1_arm_parity is continuous_weekly)
    sy, sm, sd = (int(x) for x in win.start.split("-"))
    ey, em, ed = (int(x) for x in win.end.split("-"))
    main_py = run / "main.py"
    s = main_py.read_text()
    inject = (
        "    STRATEGY_CONFIG = STRATEGY_CONFIG\n"
        f"    START_DATE = ({sy}, {sm}, {sd})\n"
        f"    END_DATE = ({ey}, {em}, {ed})\n"
        "    CONTINUOUS_WEEKLY = True\n"
    )
    assert "    STRATEGY_CONFIG = STRATEGY_CONFIG\n" in s, "FAIL: inject anchor missing"
    main_py.write_text(s.replace("    STRATEGY_CONFIG = STRATEGY_CONFIG\n", inject, 1))
    (run / "lean.json").write_text('{ "description": "m1 arm direct", "parameters": {} }\n')
    data = run / "data"
    if not data.exists():
        data.symlink_to(Path("/Users/falk/projects/kumo-qc/data"))

    rc = _default_run_lean(run)
    print(f"lean rc: {rc}", flush=True)
    rp = _default_find_result(run)
    print(f"RESULT: {rp}", flush=True)
    print(f"RUN_DIR: {run}", flush=True)


if __name__ == "__main__":
    main()
