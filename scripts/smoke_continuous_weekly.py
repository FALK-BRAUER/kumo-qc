"""#336/#338 ws1 SMOKE — flag-ON one-window local LEAN BT (HQ's gate-1 guard).

Runs the pure-base champion (SweepConfig(choices=()), config_hash fd8248b34265) on ONE window
(w2_2025q2, which contains URBN's 2025-05-30 champion entry) with CONTINUOUS_WEEKLY enabled via the
LEAN `continuous-weekly` parameter (threaded through SWEEP_LEAN_PARAMS → local_dist_builder).

PURPOSE (HQ): de-risk the full-FY run BEFORE committing to it —
  1. the flag-ON BT COMPLETES with no container hang (the ~200 self.history calls/decision-day),
  2. it produces trades (the continuous-weekly path scores names),
  3. eyeball URBN's flag-ON live decision vs the OFFLINE cache (single-source check).

archive=False on purpose: a flag-ON run shares config_hash fd8248b34265 with the flag-OFF champion
(the flag is not part of StrategyConfig) → persisting it would CONFLATE two behaviors under one hash.
The smoke reads the raw LEAN backtest output from the isolated run_dir instead.

Usage: python3 scripts/smoke_continuous_weekly.py
"""
from __future__ import annotations

import glob
import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_ROOT), str(_ROOT / "src"), str(_ROOT / "scripts")]

os.environ["SWEEP_LEAN_PARAMS"] = json.dumps({"continuous-weekly": "1"})
os.environ.setdefault("DOCKER_HOST", "unix:///Users/falk/.docker/run/docker.sock")

from sweeps.adapters.qc_local_prod import make_local_run  # noqa: E402
from sweeps.types import SweepConfig, Window  # noqa: E402

_DAILY = Path("/Users/falk/projects/kumo-qc/data/equity/usa/daily")
W = Window(name="w2_2025q2", start="2025-04-01", end="2025-06-30")


def _offline_urbn_scores() -> None:
    """Independent OFFLINE-cache scores for URBN across the window (the continuous-weekly reference
    the live flag-ON path should match). Prints score + cond per late-May date."""
    from phases.shared.oracle_helpers import score_symbol_cached
    from sweeps.warmup_cache.table_builder import build_ticker_scalars, read_daily_zip

    zp = _DAILY / "urbn.zip"
    if not zp.exists():
        print("  (urbn.zip not present — skipping offline reference)")
        return
    rows = {d: s for d, s in build_ticker_scalars(read_daily_zip(zp))}
    print("OFFLINE-CACHE URBN scores (continuous weekly), late-May 2025:")
    for d in sorted(rows):
        if d.isoformat() < "2025-05-20" or d.isoformat() > "2025-06-05":
            continue
        sc = score_symbol_cached(rows[d])
        cond = "".join("1" if c else "0" for c in sc["conditions"])
        print(f"  {d}  score={sc['score']}  cond={cond}")


def main() -> None:
    champ = SweepConfig(choices=())
    print(f"=== SMOKE continuous-weekly flag-ON: champion base {champ.config_hash}, window {W.name} ===")
    print(f"    SWEEP_LEAN_PARAMS={os.environ['SWEEP_LEAN_PARAMS']}")
    _offline_urbn_scores()
    print("--- launching flag-ON LEAN backtest (archive=False, isolated run_dir) ---", flush=True)
    adapter = make_local_run(archive=False)
    m = adapter(champ, W)
    print("METRICS:", json.dumps(m, default=str)[:3000])

    # locate the most-recent run_dir + grep its order events for URBN
    runs = sorted(glob.glob(str(_ROOT / "sweeps" / "runs" / "*")), key=os.path.getmtime)
    if runs:
        rd = runs[-1]
        print(f"run_dir: {rd}")
        orders = glob.glob(f"{rd}/**/*order-events*.json", recursive=True) + \
            glob.glob(f"{rd}/**/orders/*.json", recursive=True)
        print(f"order-event files: {orders[:3]}")
        for of in orders[:1]:
            try:
                data = json.loads(Path(of).read_text())
                urbn = [o for o in (data if isinstance(data, list) else data.values())
                        if isinstance(o, dict) and "URBN" in str(o.get("symbol", o.get("Symbol", "")))]
                print(f"  URBN order events: {len(urbn)}")
                for o in urbn[:4]:
                    print("   ", json.dumps(o, default=str)[:300])
            except Exception as e:  # noqa: BLE001
                print(f"  (could not parse {of}: {e})")


if __name__ == "__main__":
    main()
