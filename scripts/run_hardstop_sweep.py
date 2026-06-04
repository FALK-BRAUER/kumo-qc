"""P1 MANAGEMENT LEVER — S1 champion + asymmetric hard-stop, FY-full sweep (#364 hard_stop_pct).

Entry-feature-selection is exhausted (#349/#371: HOOD==MRVL fundamental). The edge is in MANAGEMENT.
The champion (S1, mainV2 f82809f) is +27.7% ALL-open-paper (HOOD+175/KGC+166) but realized -15.2k
(every CLOSED trade a loser). So: does a hard left-tail stop cut the realized-loser tail (MRVL-37/
UAL-29 type) WITHOUT clipping the runners (HOOD/KGC ran through en-route drawdowns)?

cloud_protective_stop.hard_stop_pct sets a GTC stop floor = max(cloud_bottom, entry_px*(1-X)) — so X
can only RAISE the floor (tighter), never loosen below the cloud. X=0.0 = the pure champion baseline.

THIS WORKTREE = mainV2 champion + ONLY the cherry-picked hard-stop lever (dd0301b) — no #365/#368/#364
contamination. So baseline-0.0 == the TRUE champion → the comparison is clean apples-to-apples.

FY-full first (the let-winners-run headline + runner-survival), 6-window panel on survivors after. NO
cloud. Sequential cap-1 full-warmup (OOM-safe). Grade = the Sharpe/Ret%/DD% trio (never Sharpe alone).

Usage: python3 scripts/run_hardstop_sweep.py
"""
from __future__ import annotations

import csv
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_ROOT), str(_ROOT / "src"), str(_ROOT / "scripts")]
os.environ.setdefault("DOCKER_HOST", "unix:///Users/falk/.docker/run/docker.sock")

from sweeps.adapters.qc_local_prod import make_local_run  # noqa: E402
from sweeps.types import PhaseChoice, SweepConfig, Window  # noqa: E402

FY_FULL = Window(name="fy2025_full", start="2025-01-01", end="2025-12-31")
X_GRID = (0.0, 0.08, 0.12, 0.15, 0.20)  # 0.0 = champion baseline; the rest = -X% hard stops


def cfg_for(x: float) -> SweepConfig:
    """S1 champion choices with cloud_protective_stop.hard_stop_pct = x (0.0 = unchanged baseline)."""
    ps = (("hard_stop_pct", x),) if x else ()
    return SweepConfig(
        choices=(
            PhaseChoice("protective_stop", "cloud_protective_stop", ps, 0),
            PhaseChoice("exit_hard", "cloud_adherence_trail", (), 0),
            PhaseChoice("sizing", "flat_pct_heatcap", (("position_pct", 0.05),), 0),
        ),
        continuous_weekly=True,
    )


def main() -> None:
    # argv = explicit X subset (e.g. "0.0" for the gate cell alone, then "0.08 0.12 0.15 0.20");
    # no argv = the full grid. Lets the orchestrator run baseline-0.0 FIRST for the base-validity gate.
    grid = tuple(float(a) for a in sys.argv[1:]) if len(sys.argv) > 1 else X_GRID
    adapter = make_local_run(warmup_gate=None)  # cap-1 sequential
    out = _ROOT / "results" / "hardstop_sweep_fy.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    # if the CSV exists (a prior subset run), carry its rows so the final table is cumulative
    if out.exists():
        import csv as _csv
        with out.open() as f:
            for r in _csv.DictReader(f):
                rows.append({"X": float(r["X"]), "tag": r["tag"], "config_hash": r["config_hash"],
                             "sharpe": float(r["sharpe"]), "ret_pct": float(r["ret_pct"]),
                             "dd_pct": float(r["dd_pct"]), "orders": int(r["orders"])})
    print(f"=== P1 HARD-STOP FY-full sweep (mainV2 champion + cherry-picked lever) — X={grid} ===",
          flush=True)
    for x in grid:
        rows = [r for r in rows if r["X"] != x]  # replace any stale row for this X
        cfg = cfg_for(x)
        tag = "baseline" if x == 0.0 else f"-{int(x*100)}%"
        print(f"\n--- X={x} ({tag}) hash={cfg.config_hash} FY-full ---", flush=True)
        m = adapter(cfg, FY_FULL)
        row = {"X": x, "tag": tag, "config_hash": cfg.config_hash,
               "sharpe": m.sharpe, "ret_pct": m.ret_pct, "dd_pct": m.dd_pct, "orders": m.orders}
        rows.append(row)
        print(f"  Sharpe={m.sharpe:+.3f}  Net={m.ret_pct:+.1f}%  DD={m.dd_pct:.1f}%  Orders={m.orders}",
              flush=True)
        # rewrite the CSV after EACH cell (durable mid-run; survives a crash on a later X)
        with out.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)

    print(f"\n=== HARD-STOP FY-full SWEEP — trio per X (vs baseline) → {out} ===", flush=True)
    base = next(r for r in rows if r["X"] == 0.0)
    print(f"  {'X':>6} {'Sharpe':>8} {'Net%':>8} {'DD%':>7} {'Orders':>7}   {'ΔSharpe':>8} {'ΔNet':>7} {'ΔDD':>6}")
    for r in rows:
        ds, dn, dd = r["sharpe"] - base["sharpe"], r["ret_pct"] - base["ret_pct"], r["dd_pct"] - base["dd_pct"]
        mark = "  (champion)" if r["X"] == 0.0 else ""
        print(f"  {r['tag']:>6} {r['sharpe']:>+8.3f} {r['ret_pct']:>+8.1f} {r['dd_pct']:>7.1f} "
              f"{r['orders']:>7}   {ds:>+8.3f} {dn:>+7.1f} {dd:>+6.1f}{mark}", flush=True)
    print("\nNEXT: runner-survival (did HOOD/KGC survive each X, or did the stop clip them) + 6-window "
          "panel on the survivor X(s). A hard-stop WINS only if it cuts the loser tail AND keeps the runners.",
          flush=True)


if __name__ == "__main__":
    main()
