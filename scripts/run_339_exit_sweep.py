"""#339 exit-model sweep — the ROTATION-FREE candidates (A/B/C/D/G) on the 4 runnable 2025 quarters.

Per the #339 table, isolating the EXIT lever (all flag-ON / continuous_weekly=True, corrected weekly):
  A = base KijunG3            (4c2fc8e40607 — the control; ALREADY captured by the re-capture)
  B = CloudAdherenceTrail     (a218e97b8d51 — cloud-bottom hold)
  C = CloudBreachExit         (f62732dd1e29 — cloud-top breach)
  D = MultiMetricConfirmExit  (c089756a2bfc — >=2-of-3 confirm)
  G = KijunG3 + weekly        (448e990d275e — cloud_exit + weekly_kijun re-enabled)
Candidates E/F/H (rotation) are DEFERRED — rotation needs cross-phase score plumbing (held-position
decision_scores aren't stored; there's no slot-count cap, only the cash heat-cap) — flagged to HQ.

This runs B/C/D/G (A is reused from its existing archive). archive=True → per-cell trades.jsonl.gz for
the per-quarter trio + trade-behavior analysis. 2026 windows are skipped locally (data gap).

Usage: SWEEP_WORKERS=2 python3 scripts/run_339_exit_sweep.py
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


def _cand(impl=None, params=()):
    choices = () if impl is None else (PhaseChoice("exit_hard", impl, params, 0),)
    return SweepConfig(choices=choices, continuous_weekly=True)


CANDIDATES = {
    "B_cloud_adherence": _cand("cloud_adherence_trail"),
    "C_cloud_breach": _cand("cloud_breach_exit"),
    "D_multi_confirm": _cand("multi_metric_confirm_exit"),
    "G_kijun_weekly": _cand("kijun_g3_exits",
                            (("cloud_exit_enabled", True), ("weekly_kijun_exit_enabled", True))),
}


def main() -> None:
    workers = int(os.environ.get("SWEEP_WORKERS", "2"))
    windows = local_runnable_windows()
    configs = list(CANDIDATES.values())
    print(f"=== #339 EXIT SWEEP (rotation-free): {len(configs)} candidates x {len(windows)} quarters "
          f"(workers={workers}). A=4c2fc8e40607 reused from cache. ===", flush=True)
    for name, sc in CANDIDATES.items():
        print(f"  {name}: {sc.config_hash}")
    gate = WarmupGate() if workers > 1 else None
    adapter = make_local_run(warmup_gate=gate)  # archive=True
    pins = ("run339-exit", "exit-model-sweep", "phase_engine_exit_v1")
    # min_windows = the LOCAL-runnable count (the 2026 windows have no local data, #338-ws3) — still a
    # distribution (4 quarters), not a point estimate; the canonical 6 holds for cloud / full panel.
    outcome = run_sweep(configs, adapter, windows=windows, max_workers=workers, pins=pins,
                        min_windows=len(windows))
    print("\n=== LEADERBOARD ===")
    print(outcome.leaderboard_csv)
    print(f"failures: {[(f.config.config_hash, f.error[:120]) for f in outcome.failures]}")


if __name__ == "__main__":
    main()
