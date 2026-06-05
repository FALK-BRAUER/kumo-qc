"""Variation tournament WAVE 1 (Falk's test-lab grant) — the LOCALLY-TESTABLE levers. window-then-FY:
Q1+Q3 gate first, leaders escalate to FY. floor-proxy + SHARPE vs S1 (1.025 / net 27.7 / DD 19.4).

Cells (all leave monsters un-perturbed — the pattern: every winner-PERTURBING mechanic dies):
  profit_t1/t2/t3 : #379 prover-gated fader trim (exempts monsters, can't skip a KGC) — the loser-side lever
  score_s6/s8     : BCT min_score {6,8} — signal SUPPLY (more/fewer shots from the SAME 326 universe).
                    The locally-testable proxy for universe-expansion (cloud-only: local data caps at 326).

NOTE universe-expansion {545,1000,1500} is NOT here — locally untestable (local polygon data = 326
unique tickers; dv_rank/COARSE_MAX beyond 326 = no-op). It is a CLOUD-only experiment (full universe in
ObjectStore). Flagged to HQ; score-threshold is the local "more shots" proxy.

Usage: python3 scripts/run_tourney_w1.py [cell ...] [q1 q3]
"""
from __future__ import annotations

import datetime as _dt
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_ROOT), str(_ROOT / "src"), str(_ROOT / "scripts")]
os.environ.setdefault("DOCKER_HOST", "unix:///Users/falk/.docker/run/docker.sock")

import build.sweep_build as sb  # noqa: E402
from sweeps.adapters.qc_local_prod import make_local_run  # noqa: E402
from sweeps.types import SweepConfig  # noqa: E402
from sweeps.windows import SIX_WINDOWS  # noqa: E402
from kpi import report_and_log  # noqa: E402

_FP = "90f2d7e3fb80d0a4d2eb286f6a43199e1519495a3ce9d787a4d7d0dfc70c535c"
RUNS = _ROOT / "sweeps" / "runs_tourney_w1"
TRIM = SweepConfig(choices=(), continuous_weekly=True, warmup_days=320)
_BY = {w.name: w for w in SIX_WINDOWS}
WINDOWS = {"q1": _BY["w1_2025q1"], "q3": _BY["w3_2025q3"]}
CELLS = [
    ("profit_t1", "#379 T1 age-gated fader trim"),
    ("profit_t2", "#379 T2 stalled-below-Tenkan fader trim"),
    ("profit_t3", "#379 T3 candidate-driven fader trim"),
    ("score_s6", "BCT min_score=6 (MORE shots)"),
    ("score_s8", "BCT min_score=8 (fewer, higher-conviction)"),
]


def main() -> None:
    args = [a.lower() for a in sys.argv[1:]]
    ck = [a for a in args if a.startswith(("profit_", "score_"))] or [c for c, _ in CELLS]
    wk = [a for a in args if a in ("q1", "q3")] or ["q1", "q3"]
    print(f"=== TOURNAMENT WAVE 1 — {ck} × {wk} (window-then-FY; vs S1 1.025/27.7/19.4) ===", flush=True)
    for cell, label in CELLS:
        if cell not in ck:
            continue
        sb.build_sweep_dist.__kwdefaults__ = {**(sb.build_sweep_dist.__kwdefaults__ or {}),
                                              "base_module": f"strategies.{cell}"}
        for w in [WINDOWS[k] for k in wk]:
            adapter = make_local_run(runs_root=RUNS / cell / w.name, warmup_gate=None, ensure_weekly_cache_fp=_FP)
            print(f"\n--- {cell} [{label}] {w.name} ---", flush=True)
            m = adapter(TRIM, w)
            rd = RUNS / cell / w.name / TRIM.config_hash / w.name
            report_and_log(rd, f"#TW1 {cell} {w.name}", sharpe=m.sharpe, net_pct=m.ret_pct, dd_pct=m.dd_pct,
                           fills=m.orders, config_hash=TRIM.config_hash, window=w.name,
                           stamp="2026-06-05", asof=_dt.date.fromisoformat(w.end))


if __name__ == "__main__":
    main()
