"""First LIVE sweep through the proven runner (#214/#320-C/#322) — the DV-rank cap grid.

Drives the DV-rank booster validation THROUGH the sweep machine (not hand-fired BTs): the cap axis
{100, 250, 500, uncapped} as 4 SweepConfigs, each = the champion_intraday_gapvol base with ONLY the
signal swapped to OracleSignal(DvRankPredictor(rank_cap=cap)). The runner (sweeps.run_sweep) fans
them over the validation windows via the REAL cloud adapter (make_cloud_run, assert_cloud_clean per
run), scores + gates + ranks into the first real leaderboard. uncapped (rank_cap huge) fires all
score≥7 == the baseline champion → gate-④ (uncapped-doesn't-collapse) falls out of the same grid.

SINGLE-STREAM (max_workers=1) — no parallel cloud (the 160GB/node-budget lesson). The proving run.

Usage:
  python3 scripts/run_dvrank_grid.py smoke   # 1 cap (250) x 1 window — confirm the live path
  python3 scripts/run_dvrank_grid.py full    # 4 caps x 6 windows — the first real leaderboard
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_ROOT), str(_ROOT / "src"), str(_ROOT / "scripts")]

from phases.signal.oracle_signal.oracle_signal import DvRankPredictor  # noqa: E402
from sweeps.adapters.qc_cloud_prod import make_cloud_run  # noqa: E402
from sweeps.grids.windows_fy2025 import FY2024_OOS, sweep_windows  # noqa: E402  the DEFINED panel + OOS
from sweeps.provenance import git_commit  # noqa: E402
from sweeps.run_sweep import run_sweep  # noqa: E402
from sweeps.types import PhaseChoice, SweepConfig, Window  # noqa: E402

UNCAPPED = 10**9  # rank_cap so large all score≥7 fire == the baseline champion (gate-④ anchor)
CAPS = [100, 250, 500, UNCAPPED]
OUT = _ROOT / "results" / "sweeps" / "dvrank_grid"


def cap_config(cap: int) -> SweepConfig:
    """One grid point: the champion base with signal → OracleSignal(DvRankPredictor(rank_cap=cap)).
    Only the signal choice is carried — sweep_to_strategy_config leaves every other kind = base."""
    pred = DvRankPredictor(min_score=7, rank_cap=cap)
    params = tuple(sorted(
        [("min_score", 7), ("parabolic_threshold", 0.25), ("predictor", pred)], key=lambda kv: kv[0]
    ))
    return SweepConfig(choices=(
        PhaseChoice(kind="signal", impl_name="oracle_signal", params=params, free_params=2),
    ))


def smoke() -> None:
    """Deploy-health check: ONE config, ONE window, DIRECT through the adapter (bypasses run_pool's
    mandatory 6-window panel gate — a smoke is a deploy-health probe, not a robustness result).
    Confirms the regen config Initializes CLEAN on cloud (the codegen-fix proof) + the adapter's
    deploy→run→assert_cloud_clean→parse path works live. Returns ResultMetrics on success."""
    cfg = cap_config(250)
    # SHORT window — a smoke proves cloud-Initialize only; the window is irrelevant to that (don't
    # burn a full-FY BT to prove deploy-health). §Parity gate-0 2-week window.
    w = Window(name="smoke_2wk", start="2025-01-01", end="2025-01-15")
    print(f"=== SMOKE: cap=250 ({cfg.config_hash}) x {w.name} — DIRECT adapter deploy-health ===")
    adapter = make_cloud_run()
    metrics = adapter(cfg, w)  # CloudLeanRun.__call__ → ResultMetrics (assert_cloud_clean inside; raises on dirty)
    print(f"✅ SMOKE CLEAN — config Initialized + ran clean on cloud: Sharpe={metrics.sharpe} "
          f"Ret%={metrics.ret_pct} DD%={metrics.dd_pct} orders={metrics.orders}")
    print("   → codegen fix confirmed on cloud; the live grid path (run_sweep + adapter) is proven.")


def main(mode: str) -> None:
    if mode == "smoke":
        return smoke()
    # MINIMAL-first (HQ throughput): prove the full chain end-to-end on the smallest meaningful grid
    # — the booster (cap=250) vs the baseline (uncapped == all score≥7) over the 6-window panel
    # (12 BTs ~80min serial), enough to produce + prove the first real leaderboard. `full` scales to
    # all 4 caps; parallelize there (max_workers up to QC's concurrent-BT cap), not on this first proof.
    # the DEFINED validation set (NO arbitrary years): 6 FY2025 bi-monthly panel windows (gates ①②)
    # + the FY2024 OOS holdout (gate ③). sweep_windows(include_holdout=True) = the 7-window set.
    #
    # OOS IS A CLOUD GATE, NOT A LOCAL ONE (verified 2026-06-02): the FY2024 window's 750-day warmup
    # reaches back to 2022, which the local intraday/universe backfill (#325, 2024-2025) does NOT
    # cover → the strategy's #261-5 empty-coarse-feed guard fires (correctly) and the run aborts with
    # 0 data points. The 6 FY2025 panels' warmup starts ~2023-06 (verified: w1 warmup begins
    # 2023-06-21), which IS covered, so they run locally. So: the LOCAL candidate-ranking pass uses
    # the 6 panels ONLY; the OOS holdout (gate-③) is validated on CLOUD, where the warmup data exists.
    # This matches windows_fy2025.sweep_windows' own contract ("holdout = final-validation phase only").
    if mode == "min":
        caps, workers, adapter = [250, UNCAPPED], 1, make_cloud_run()
        windows, oos = sweep_windows(include_holdout=True), FY2024_OOS.name
    elif mode == "full":
        caps, workers, adapter = CAPS, 1, make_cloud_run()
        windows, oos = sweep_windows(include_holdout=True), FY2024_OOS.name
    elif mode.startswith("local"):
        # LOCAL sweep (#325) — runs through `lean backtest` on the local intraday backfill,
        # max_workers from the EMPIRICAL RAM cap (env SWEEP_WORKERS, default conservative 3). The
        # local leaderboard is a CANDIDATE RANKING; the winner is cloud-validated for the final number.
        # 6 PANELS ONLY (OOS → cloud, see above). NOTE: the warmup PEAK (96-99%) is memory-heavy and
        # can OOM a cell at >1 concurrency (the w5 race, 2026-06-02) — set SWEEP_WORKERS=1 for a
        # guaranteed-clean board until #332 (warmup-cache) removes the warmup cost.
        import os as _os
        from sweeps.adapters.local_lean import WarmupGate
        from sweeps.adapters.qc_local_prod import make_local_run
        caps = [250, UNCAPPED] if mode == "local" else CAPS  # 'local' = min grid, 'localfull' = 4-cap
        workers = int(_os.environ.get("SWEEP_WORKERS", "3"))
        # (C) WARMUP-SEMAPHORE: at >1 concurrency, share ONE WarmupGate so only one cell warms at a
        # time (the OOM control) while execution runs parallel. workers=1 → ungated (serial, no need).
        gate = WarmupGate() if workers > 1 else None
        adapter = make_local_run(warmup_gate=gate)
        windows, oos = sweep_windows(include_holdout=False), None  # 6 FY2025 panels; OOS→cloud
    else:
        raise SystemExit("usage: run_dvrank_grid.py smoke|min|full|local|localfull")

    configs = [cap_config(c) for c in caps]
    runtime = "local Docker-LEAN" if mode.startswith("local") else "cloud single-stream"
    print(f"=== DV-rank grid ({mode}): {len(configs)} caps x {len(windows)} windows = "
          f"{len(configs) * len(windows)} BTs, {runtime}, workers={workers} ===")
    for c, cfg in zip(caps, configs):
        print(f"  cap={c:>10}  config_hash={cfg.config_hash}")

    pins = (git_commit(_ROOT), "live-dvrank-grid", "oracle_signal_v1")
    outcome = run_sweep(configs, adapter, windows=windows, max_workers=workers,
                        oos_window=oos, stress_window=None, pins=pins)

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"leaderboard_{mode}.csv").write_text(outcome.leaderboard_csv)
    # #10: worktree-local sweep index in bt-results.csv format (single-writer-on-main → merge via
    # scripts/merge_sweep_index.py on demand; never append to bt-results.csv from a worktree).
    if outcome.ledger:
        from datetime import datetime, timezone
        from sweeps.provenance import git_branch
        from sweeps.sweep_index import sweep_index_rows, to_index_csv
        env = "local" if mode.startswith("local") else "cloud"
        rows = sweep_index_rows(
            outcome.ledger, windows={w.name: w for w in windows}, branch=git_branch(_ROOT),
            env=env, grid=f"dvrank_{mode}", date_run=datetime.now(timezone.utc).isoformat(),
        )
        (OUT / f"sweep_index_{mode}.csv").write_text(to_index_csv(rows))
        print(f"  sweep_index_{mode}.csv: {len(rows)} rows (merge on main: "
              f"python3 scripts/merge_sweep_index.py)")
    print(f"\n=== LEADERBOARD ({mode}) — {len(outcome.leaderboard)} ranked, {len(outcome.failures)} failed ===")
    print(outcome.leaderboard_csv)
    for sc in outcome.scorecards:
        ch = sc.config.config_hash
        print(f"  {ch}: composite={sc.scored.composite:+.3f} trade_gate={sc.trade_gate.passed} "
              f"concentration_gate={sc.concentration_gate.passed}")
    for fl in outcome.failures:
        print(f"  FAILED {fl.config.config_hash}: {fl.error}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "smoke")
