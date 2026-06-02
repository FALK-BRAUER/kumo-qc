"""Champion-on-panel REFERENCE run (HQ diagnostic, 2026-06-02) — the missing robustness reference
for the DV-rank board (4e5b072).

WHAT: the PHASE-ENGINE champion (champion_intraday_gapvol #270 = SweepConfig(choices=()), the pure
BASE_MODULE with NO swept phases) through the SAME 6 FY2025 panels + the SAME gates as the DV-rank
board. Answers: is the champion 4+/6 positive and NOT single-window-carried, or is it ALSO w5-carried?
  - champion passes ①②  → the DV-rank booster is a dead axis, champion stands, board is clean.
  - champion ALSO w5-carried → deeper FY2025-fragility in the whole thesis, reshapes the search.

LINEAGE LABEL (provenance, do not conflate): this is the phase-engine champion, NOT sT10e+R-B-v3 /
pop_sharpe 1.2273. Those are a DIFFERENT, OLDER lineage (minimal_bct, cloud, PROVISIONAL / pending
#182 — design-doc line 332). champion_intraday_gapvol uses Kijun stops + intraday-confirm, NOT
sT10e's ATR+buy_stop. The 1.2273 repro-check is N/A cross-lineage — flagged, see the HQ thread.

RUNTIME: local Docker-LEAN, 6 FY2025 panels only (OOS → cloud, the local backfill can't warm a
FY2024 window — see run_dvrank_grid.py). SWEEP_WORKERS>1 shares a WarmupGate (C) — parallel with the
warmup serialized (the OOM control). This is ALSO the first live (C) validation.

Usage: SWEEP_WORKERS=2 python3 scripts/run_champion_panel.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_ROOT), str(_ROOT / "src"), str(_ROOT / "scripts")]

from sweeps.adapters.local_lean import WarmupGate  # noqa: E402
from sweeps.adapters.qc_local_prod import make_local_run  # noqa: E402
from sweeps.grids.windows_fy2025 import sweep_windows  # noqa: E402
from sweeps.provenance import git_commit  # noqa: E402
from sweeps.run_sweep import run_sweep  # noqa: E402
from sweeps.types import SweepConfig  # noqa: E402

OUT = _ROOT / "results" / "sweeps" / "champion_panel"


def main() -> None:
    champion = SweepConfig(choices=())  # pure phase-engine champion base (no swept phases)
    windows = sweep_windows(include_holdout=False)  # 6 FY2025 panels; OOS → cloud
    workers = int(os.environ.get("SWEEP_WORKERS", "2"))
    gate = WarmupGate() if workers > 1 else None
    adapter = make_local_run(warmup_gate=gate)

    print(f"=== CHAMPION-on-panel (phase-engine champion_intraday_gapvol #270, NOT sT10e/1.2273) ===")
    print(f"    config_hash={champion.config_hash}  {len(windows)} FY2025 panels  "
          f"local Docker-LEAN  workers={workers}{' +WarmupGate' if gate else ''}")

    pins = (git_commit(_ROOT), "champion-on-panel-ref", "phase_engine_champion_v1")
    outcome = run_sweep([champion], adapter, windows=windows, max_workers=workers,
                        oos_window=None, stress_window=None, pins=pins)

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "leaderboard_champion_local.csv").write_text(outcome.leaderboard_csv)
    print(f"\n=== CHAMPION BOARD — {len(outcome.leaderboard)} ranked, {len(outcome.failures)} failed ===")
    print(outcome.leaderboard_csv)
    for sc in outcome.scorecards:
        print(f"  {sc.config.config_hash}: composite={sc.scored.composite:+.3f} "
              f"trade_gate={sc.trade_gate.passed} concentration_gate={sc.concentration_gate.passed}")
    for fl in outcome.failures:
        print(f"  FAILED {fl.config.config_hash}: {fl.error}")


if __name__ == "__main__":
    main()
