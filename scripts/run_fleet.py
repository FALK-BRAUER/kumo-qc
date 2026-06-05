"""N-WIDE PARALLEL fleet launcher (the speed unlock — Falk: serial on 14-core/64GB is indefensible).

Process-level parallelism (NOT threads): spawns one `run_cell.py` SUBPROCESS per (module, window) and
keeps at most --workers in flight. Each cell-process has its OWN base_module global → no shared-state
race (the thread-version bug). Unique lean container names + distinct runs_root per cell → no collision.
The leaderboard append is flock-guarded (kpi.append_leaderboard). The --workers cap IS the OOM gate:
set it to floor(DockerRAM / warmup-PEAK-RSS) — NOT steady-state (warmup peaks higher; measure it).

  Docker 7.75GiB today → ~3-wide safe (verify warmup-peak first). After Falk bumps to 16GB → 6-wide.
  Also caps at min(workers, cores-4) to leave host headroom.

Usage: python3 scripts/run_fleet.py --workers N --runs <subdir> --windows q1,q3[,fy] mod1 mod2 ...
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_CELL = _ROOT / "scripts" / "run_cell.py"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--runs", default="fleet")
    ap.add_argument("--windows", default="q1,q3")
    ap.add_argument("mods", nargs="+")
    a = ap.parse_args()

    cores = os.cpu_count() or 8
    # NOTE the OOM gate is RAM, not cores: the operator must set --workers = floor(DockerRAM /
    # warmup-PEAK-RSS) (measured at the cap-2 test). cores-4 is only a host-headroom guard on top.
    workers = max(1, min(a.workers, cores - 4))
    wkeys = a.windows.split(",")
    queue = [(mod, wk) for mod in a.mods for wk in wkeys]
    print(f"=== FLEET — {len(queue)} cells, {workers}-wide (req {a.workers}, cores {cores}) runs_{a.runs} ===", flush=True)

    running: list[tuple[subprocess.Popen, tuple[str, str]]] = []
    done, failed = [], []
    qi = 0

    # CACHE-STAMPEDE GUARD (review bug 2): ensure_weekly_cache runs inside every cell; if the weekly
    # cache is COLD, N cells launched together all build it concurrently → non-atomic key writes race.
    # So run the FIRST cell SYNCHRONOUSLY (it warms the cache if cold) BEFORE any parallel fan-out;
    # the cache is then complete()==True for every sibling → they all hit the no-op skip. Costs one
    # cell's wall-time (paid anyway). The first cell's result is recorded like any other.
    if queue:
        mod, wk = queue[qi]; qi += 1
        print(f"  · warm/first cell SERIAL {mod} {wk} (cache-stampede guard)", flush=True)
        rc = subprocess.run([sys.executable, str(_CELL), mod, wk, a.runs]).returncode
        (done if rc == 0 else failed).append((mod, wk) if rc == 0 else ((mod, wk), rc))

    while qi < len(queue) or running:
        # fill up to `workers`
        while len(running) < workers and qi < len(queue):
            mod, wk = queue[qi]; qi += 1
            p = subprocess.Popen([sys.executable, str(_CELL), mod, wk, a.runs])
            running.append((p, (mod, wk)))
            print(f"  + launched {mod} {wk}  ({len(running)} in flight)", flush=True)
            time.sleep(2)  # stagger launches so warmups don't all peak in lockstep
        # reap finished
        still = []
        for p, cell in running:
            rc = p.poll()
            if rc is None:
                still.append((p, cell))
            elif rc == 0:
                done.append(cell); print(f"  ✓ {cell[0]} {cell[1]}  ({len(done)} done)", flush=True)
            else:
                failed.append((cell, rc)); print(f"  ✗ {cell[0]} {cell[1]} rc={rc}", flush=True)
        running = still
        if running:
            time.sleep(5)
    # FAIL-LOUD (review bug 1): a crashed cell writes NO leaderboard row → partial results look
    # complete + the ranker would crown a winner from survivors. Exit non-zero so the caller knows
    # the grid is incomplete; never let a silent drop pass as done.
    if failed:
        print(f"=== FLEET INCOMPLETE: {len(done)} ok, {len(failed)} FAILED {failed} — "
              f"grid is MISSING rows, do NOT rank until re-run ===", flush=True)
        sys.exit(1)
    print(f"=== FLEET done: {len(done)} ok, 0 failed ({len(queue)} cells) ===", flush=True)


if __name__ == "__main__":
    main()
