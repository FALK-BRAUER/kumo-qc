"""#336/#338 ws1 GATE + RE-BASELINE — full-FY flag-OFF vs flag-ON on the corrected weekly.

Runs the pure-base champion (SweepConfig(choices=()), config_hash e3b0c44298fc) on FY2025_FULL
TWICE, SERIALLY (same config_hash → same run_dir; serial avoids the lean compile-cache collision):
  1. flag-OFF (the gappy subscription-gated weekly = the current baseline),
  2. flag-ON  (CONTINUOUS_WEEKLY via class-attr injection = the #336 fix).
Captures each run's metrics + traded-symbol set from its timestamped backtest dir, then reports the
RE-BASELINE delta: metric change (Sharpe/Ret/DD/orders) + the order-set cascade (names added/removed
— incl the URBN/PEN flips and the freed-slot downstream shifts).

archive=False both runs (a flag-on run shares config_hash with flag-off → must not pollute the
archive). The gate's 81/81 is established logically by the single-source proof (live weekly == offline
cache, 26/26 exact); this run quantifies how much the correctness fix MOVES the champion.

Usage: python3 scripts/rebaseline_continuous_weekly.py
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

from sweeps.types import SweepConfig, Window  # noqa: E402

FY = Window(name="fy2025_full", start="2025-01-01", end="2025-12-31")


def _symbols(run_dir: str) -> set[str]:
    """Distinct traded symbols from the NEWEST backtest's order-events in run_dir."""
    bts = sorted(glob.glob(f"{run_dir}/backtests/*/"), key=os.path.getmtime)
    if not bts:
        return set()
    oe = glob.glob(f"{bts[-1]}/*order-events.json")
    if not oe:
        return set()
    data = json.loads(Path(oe[0]).read_text())
    items = data if isinstance(data, list) else list(data.values())
    return {str(o.get("symbolValue", "")).split(" ")[0] for o in items if o.get("symbolValue")}


def _run(flag_on: bool) -> tuple[object, set[str]]:
    # fresh adapter per run so the class-attr env is read at build time
    if flag_on:
        os.environ["SWEEP_CLASS_ATTRS"] = json.dumps({"CONTINUOUS_WEEKLY": True})
    else:
        os.environ.pop("SWEEP_CLASS_ATTRS", None)
    from sweeps.adapters.qc_local_prod import make_local_run

    champ = SweepConfig(choices=())
    label = "flag-ON (continuous weekly)" if flag_on else "flag-OFF (gappy baseline)"
    print(f"--- {label}: champion {champ.config_hash} FY2025_FULL ---", flush=True)
    m = make_local_run(archive=False)(champ, FY)
    syms = _symbols(str(_ROOT / "sweeps" / "runs" / champ.config_hash / FY.name))
    print(f"    {label} metrics: {m}")
    print(f"    {label} traded {len(syms)} names")
    return m, syms


def main() -> None:
    off_m, off_s = _run(flag_on=False)
    on_m, on_s = _run(flag_on=True)
    print("\n=== RE-BASELINE DELTA (flag-ON continuous weekly vs flag-OFF gappy baseline) ===")
    print(f"flag-OFF: {off_m}")
    print(f"flag-ON : {on_m}")
    print(f"names ONLY in flag-ON  (entered on corrected weekly): {sorted(on_s - off_s)}")
    print(f"names ONLY in flag-OFF (dropped on corrected weekly): {sorted(off_s - on_s)}")
    print(f"names in BOTH: {len(on_s & off_s)}  | flag-OFF total {len(off_s)} | flag-ON total {len(on_s)}")
    print(f"URBN flag-OFF={'URBN' in off_s} flag-ON={'URBN' in on_s}  |  "
          f"PEN flag-OFF={'PEN' in off_s} flag-ON={'PEN' in on_s}")


if __name__ == "__main__":
    main()
