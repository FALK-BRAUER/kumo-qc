"""#386 exit-parity proof runner. Runs the champion (choices=() = champion_intraday_gapvol, the sweep
BASE) on a window via the local LEAN harness, then dumps the EXIT FILLS (filled sells: time/symbol/
price/qty) from the LEAN order-events + the metrics. Run the SAME invocation in two trees:
  REFERENCE  = worktree @ d60eab3~1 (pre-delete-1, exits fire market_on_open)
  CANDIDATE  = HEAD + local exit "market" stamps
Byte-identical exit fills + P&L → "market" reproduces the daily-clock MOO fills → SAFE to commit.

Usage: python3 scripts/run_386_exit_parity.py <q1|fy> [arm]
  arm → adds the StubArm phase (m1-arm-parity equiv): the live _assert_arm_parity fires each daily
        decision; the run COMPLETING (no DegradedDataError) == entry arm-parity proven.
"""
from __future__ import annotations

import glob
import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_ROOT), str(_ROOT / "src"), str(_ROOT / "scripts")]
os.environ.setdefault("DOCKER_HOST", "unix:///Users/falk/.docker/run/docker.sock")

from sweeps.adapters.qc_local_prod import make_local_run  # noqa: E402
from sweeps.types import PhaseChoice, SweepConfig, Window  # noqa: E402

WINDOWS = {
    "q1": Window(name="w1_2025q1", start="2025-01-01", end="2025-03-31"),
    "fy": Window(name="fy2025_full", start="2025-01-01", end="2025-12-31"),
}


def _exit_fills(order_events_path: Path) -> list[tuple]:
    evs = json.loads(order_events_path.read_text())
    if isinstance(evs, dict):
        evs = evs.get("orderEvents") or list(evs.values())
    fills: list[tuple] = []
    for ev in evs:
        if not isinstance(ev, dict):
            continue
        if str(ev.get("status", "")).lower() != "filled":
            continue
        if str(ev.get("direction", "")).lower() != "sell":
            continue
        fills.append((
            ev.get("time") or ev.get("utcTime") or ev.get("lastFillTime"),
            ev.get("symbolValue") or ev.get("symbol"),
            round(float(ev.get("fillPrice") or 0.0), 4),
            abs(float(ev.get("fillQuantity") or ev.get("quantity") or 0.0)),
        ))
    fills.sort(key=lambda f: (str(f[0]), str(f[1])))
    return fills


def main() -> None:
    win = WINDOWS[sys.argv[1] if len(sys.argv) > 1 else "q1"]
    arm = len(sys.argv) > 2 and sys.argv[2] == "arm"
    choices = (PhaseChoice("arm", "stub_arm", (), 0),) if arm else ()
    cfg = SweepConfig(choices=choices, continuous_weekly=True)
    print(f"=== #386 exit-parity | config_hash={cfg.config_hash} | arm={arm} | win={win.name} ===", flush=True)
    metrics = make_local_run(archive=False)(cfg, win)
    print(f"METRICS: {metrics}", flush=True)
    oes = sorted(
        glob.glob(str(_ROOT / "sweeps" / "runs" / "**" / "*order-events*.json"), recursive=True),
        key=os.path.getmtime,
    )
    if not oes:
        print("NO order-events found under sweeps/runs/", flush=True)
        return
    oe = Path(oes[-1])
    fills = _exit_fills(oe)
    print(f"ORDER-EVENTS: {oe}", flush=True)
    print(f"EXIT FILLS ({len(fills)}) [time, symbol, fillPrice, qty]:", flush=True)
    for f in fills:
        print(f"  {f}", flush=True)


if __name__ == "__main__":
    main()
