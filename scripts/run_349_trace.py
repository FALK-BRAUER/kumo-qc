"""#349 feature-discovery — gather the score-7 DECISIONTRACE on ALL 4 FY2025 quarters at the S1 base.

The grader (run_353_manual.py) needs a per-quarter DECISIONTRACE log under
sweeps/runs/65c0cf447168/<window>/backtests/*/log.txt for Q1(bear), Q2(bull), Q3(bull), Q4(bear).
The score-7 pool is SIGNAL-determined (bct_score_full, before any swept phase) → identical across
configs; gathering them all at ONE consistent base (S1 = 65c0cf447168) removes the old a8c1014476af
Q3 wart and makes the 4 quarters signal-identical.

IDEMPOTENT: a quarter whose latest log already has DECISIONTRACE lines is SKIPPED (so a re-run after a
partial gather only fills the gaps). SEQUENTIAL (cap-1) full-warmup (560) — the canonical signal path,
no trim/cache (the #368 guard fires on a build-vs-runtime gap under trim; #370 reconcile is the fix).

Usage: python3 scripts/run_349_trace.py            (all 4 quarters, fill-missing)
       python3 scripts/run_349_trace.py --force     (re-trace all 4 even if present)
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_ROOT), str(_ROOT / "src"), str(_ROOT / "scripts")]
os.environ.setdefault("DOCKER_HOST", "unix:///Users/falk/.docker/run/docker.sock")

from sweeps.adapters.qc_local_prod import make_local_run  # noqa: E402
from sweeps.types import PhaseChoice, SweepConfig  # noqa: E402
from sweeps.windows import SIX_WINDOWS  # noqa: E402

_S1_BASE = (
    PhaseChoice("protective_stop", "cloud_protective_stop", (), 0),
    PhaseChoice("exit_hard", "cloud_adherence_trail", (), 0),
    PhaseChoice("sizing", "flat_pct_heatcap", (("position_pct", 0.05),), 0),
)
S1 = SweepConfig(choices=_S1_BASE, continuous_weekly=True)
QUARTERS = SIX_WINDOWS[:4]  # w1_2025q1, w2_2025q2, w3_2025q3, w4_2025q4


def _trace_lines(window_name: str) -> int:
    """DECISIONTRACE-line count in the latest log for this window under S1 (0 = needs (re)trace)."""
    bts = _ROOT / "sweeps" / "runs" / S1.config_hash / window_name / "backtests"
    logs = sorted(bts.glob("*/log.txt"), key=lambda p: p.stat().st_mtime, reverse=True) if bts.exists() else []
    if not logs:
        return 0
    return sum(1 for ln in logs[0].read_text(errors="ignore").splitlines() if "DECISIONTRACE|" in ln)


def main() -> None:
    force = "--force" in sys.argv[1:]
    os.environ["SWEEP_CLASS_ATTRS"] = json.dumps({"DECISION_TRACE": True})
    adapter = make_local_run()
    for w in QUARTERS:
        have = _trace_lines(w.name)
        if have and not force:
            print(f"SKIP {w.name}: already {have} DECISIONTRACE lines", flush=True)
            continue
        print(f"\n=== #349 DECISION_TRACE {w.name} ({w.start}..{w.end}) — full warmup ===", flush=True)
        r = adapter.run_result(S1, w)
        n = _trace_lines(w.name)
        print(f"  {w.name}: orders={getattr(r.metrics, 'orders', '?')} DECISIONTRACE-lines={n}", flush=True)
        if n == 0:
            raise SystemExit(f"{w.name}: 0 DECISIONTRACE lines after run — DECISION_TRACE not emitted, refuse")
    print("\nALL 4 quarters traced at S1 (65c0cf447168). NEXT: run_353_manual.py + run_352_composite.py.",
          flush=True)


if __name__ == "__main__":
    main()
