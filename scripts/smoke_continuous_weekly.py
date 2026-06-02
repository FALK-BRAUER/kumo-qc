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

# Flag enable via CLASS-ATTR injection (LEAN reads get_parameter from config.json not lean.json, so
# the local lever is class-attr injection — the same mechanism the window dates use).
os.environ["SWEEP_CLASS_ATTRS"] = json.dumps({"CONTINUOUS_WEEKLY": True, "WEEKLY_DUMP_SYMS": "urbn"})
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
    print(f"    SWEEP_CLASS_ATTRS={os.environ['SWEEP_CLASS_ATTRS']}")
    _offline_urbn_scores()
    print("--- launching flag-ON LEAN backtest (archive=False, isolated run_dir) ---", flush=True)
    adapter = make_local_run(archive=False)
    m = adapter(champ, W)
    print("METRICS:", json.dumps(m, default=str)[:3000])

    # SINGLE-SOURCE PROOF: diff the LIVE continuous-weekly scalars (CW_SCALARS log lines) vs the
    # OFFLINE cache for URBN at each decision date. Match → self.history-weekly == zip-weekly == fix.
    _diff_live_vs_offline_urbn()


_WEEKLY_FIELDS = ("w_tenkan", "w_kijun", "w_senkou_a", "w_senkou_b", "w_close_0", "w_close_26")


def _diff_live_vs_offline_urbn() -> None:
    from sweeps.warmup_cache.table_builder import build_ticker_scalars, read_daily_zip

    logs = glob.glob(str(_ROOT / "sweeps" / "runs" / "e3b0c44298fc" / "w2_2025q2" / "**" / "*-log.txt"),
                     recursive=True)
    logs = sorted(logs, key=os.path.getmtime)
    if not logs:
        print("SINGLE-SOURCE: no log file found")
        return
    live: dict[str, dict] = {}
    for line in Path(logs[-1]).read_text().splitlines():
        if "CW_SCALARS|URBN|" in line:
            _, _sym, d, payload = line.split("CW_SCALARS|", 1)[1].split("|", 3)
            live[d] = json.loads(payload)
    zp = _DAILY / "urbn.zip"
    offline = {dd.isoformat(): s for dd, s in build_ticker_scalars(read_daily_zip(zp))} if zp.exists() else {}
    print(f"SINGLE-SOURCE: {len(live)} URBN CW_SCALARS log lines captured")
    # HQ standing rule: POSITIVELY ASSERT THE FLAG IS ENGAGED before the result counts. 0 dump lines
    # = flag never on (the get_parameter-not-local-wired mirage) → NOT a pass, NOT a divergence.
    if not live:
        print("FLAG-ENGAGED CHECK: FAIL — 0 CW_SCALARS lines → CONTINUOUS_WEEKLY never engaged. "
              "The result does NOT count. Diagnose the injection; do NOT proceed to full-FY.")
        return
    print("FLAG-ENGAGED CHECK: PASS — CW_SCALARS present → continuous-weekly path proven active.")
    mismatches = 0
    for d in sorted(live):
        if d not in offline:
            continue
        lw = {k: round(float(live[d][k]), 6) for k in _WEEKLY_FIELDS}
        ow = {k: round(float(offline[d][k]), 6) for k in _WEEKLY_FIELDS}
        if lw != ow:
            mismatches += 1
            print(f"  MISMATCH {d}: live={lw} offline={ow}")
    print(f"SINGLE-SOURCE RESULT: {len(live)} dates, {mismatches} weekly mismatches "
          f"→ {'PROVEN single-sourced (live self.history-weekly == offline zip-weekly)' if mismatches == 0 else 'DIVERGENCE — STOP'}")


if __name__ == "__main__":
    main()
