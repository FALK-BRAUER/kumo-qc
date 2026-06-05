"""Period-sweep launcher (the one untested mechanism the oracle did NOT kill — faster tenkan separates
Jan monsters from losers). Runs the PARITY cell (9/26/52) FIRST and SERIALLY, asserts it reproduces S1
(-10.4 Q1 / -5.5 Q3) — the plumbing-correctness gate (HQ): if parity != S1, the threading changed
behaviour, STOP. Only then fan out the tenkan cells (3-wide — full-warmup ~4.3GB/cell, 16/4.3≈3 safe).

Process-per-cell (run_period_cell.py) → each its own SWEEP_CLASS_ATTRS env (race-free). FULL warmup
(periods break the 9/26/52 weekly-cache). Priority axis = TENKAN {7,9,12} (where the oracle shows signal).

Usage: python3 scripts/run_periods.py [q1 q3 ...]   (default q1 q3)
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_CELL = _ROOT / "scripts" / "run_period_cell.py"
RUNS = "periods"
# (tenkan, kijun, senkou_b) — parity FIRST, then the oracle's faster-tenkan separators.
PARITY = (9, 26, 52)
SWEEP = [(7, 26, 52), (12, 26, 52), (7, 22, 52)]

# S1 known floors (matrix_sz050_off) — the parity target.
S1 = {"w1_2025q1": -10.4, "w3_2025q3": -5.5}


def _floor(runs_sub, t, k, sb, wname):
    import csv
    bd = _ROOT / "results" / "leaderboard.csv"
    if not bd.exists():
        return None
    label = f"#PERIOD t{t}k{k}s{sb} {wname}"
    rows = [r for r in csv.DictReader(bd.open()) if r["label"] == label]
    return float(rows[-1]["floor_pct"]) if rows else None


def main() -> None:
    wkeys = [a for a in sys.argv[1:] if a in ("q1", "q3", "fy")] or ["q1", "q3"]
    wname = {"q1": "w1_2025q1", "q3": "w3_2025q3", "fy": "fy2025"}

    # ── PARITY GATE: 9/26/52 serial, must == S1 ──
    print("=== PARITY GATE: t9/k26/s52 must reproduce S1 ===", flush=True)
    ok = True
    for wk in wkeys:
        rc = subprocess.run([sys.executable, str(_CELL), "9", "26", "52", wk, RUNS]).returncode
        if rc != 0:
            print(f"  parity cell {wk} FAILED rc={rc}", flush=True); ok = False; continue
        fl = _floor(RUNS, 9, 26, 52, wname[wk]); tgt = S1.get(wname[wk])
        match = fl is not None and abs(fl - tgt) <= 0.2
        print(f"  parity {wk}: floor {fl} vs S1 {tgt} → {'MATCH ✓' if match else 'MISMATCH ✗ — plumbing bug'}", flush=True)
        ok = ok and match
    if not ok:
        print("=== PARITY FAILED — plumbing changed behaviour. STOP, do not trust period cells. ===", flush=True)
        sys.exit(1)
    print("=== PARITY PASSED — plumbing correct, fanning out the tenkan sweep 3-wide ===", flush=True)

    # ── SWEEP: tenkan cells, 3-wide ──
    queue = [(t, k, sb, wk) for (t, k, sb) in SWEEP for wk in wkeys]
    running, done, failed = [], [], []
    qi = 0
    while qi < len(queue) or running:
        while len(running) < 2 and qi < len(queue):  # 2-wide: full-warmup 4.3GB ea; leaves room for a concurrent cached FY run
            t, k, sb, wk = queue[qi]; qi += 1
            p = subprocess.Popen([sys.executable, str(_CELL), str(t), str(k), str(sb), wk, RUNS])
            running.append((p, (t, k, sb, wk)))
            print(f"  + t{t}k{k}s{sb} {wk}", flush=True)
            time.sleep(2)
        still = []
        for p, c in running:
            rc = p.poll()
            if rc is None:
                still.append((p, c))
            else:
                (done if rc == 0 else failed).append((c, rc))
        running = still
        if running:
            time.sleep(5)
    print(f"=== period sweep done: {len(done)} ok, {len(failed)} failed {failed if failed else ''} ===", flush=True)
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
