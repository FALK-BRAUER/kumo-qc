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
from sweeps.provenance import git_commit  # noqa: E402
from sweeps.run_sweep import run_sweep  # noqa: E402
from sweeps.types import PhaseChoice, SweepConfig, Window  # noqa: E402
from sweeps.windows import SIX_WINDOWS  # noqa: E402

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


def main(mode: str) -> None:
    if mode == "smoke":
        caps, windows = [250], (Window(name="w6_2024", start="2024-01-01", end="2024-12-31"),)
    elif mode == "full":
        caps, windows = CAPS, SIX_WINDOWS
    else:
        raise SystemExit("usage: run_dvrank_grid.py smoke|full")

    configs = [cap_config(c) for c in caps]
    print(f"=== DV-rank grid ({mode}): {len(configs)} caps x {len(windows)} windows = "
          f"{len(configs) * len(windows)} cloud BTs, single-stream ===")
    for c, cfg in zip(caps, configs):
        print(f"  cap={c:>10}  config_hash={cfg.config_hash}")

    adapter = make_cloud_run()  # REAL QC; CloudLeanRun is the RunConfig primitive (assert_cloud_clean inside)
    pins = (git_commit(_ROOT), "live-dvrank-grid", "oracle_signal_v1")
    outcome = run_sweep(configs, adapter, windows=windows, max_workers=1,
                        oos_window="w6_2024", stress_window=None, pins=pins)

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"leaderboard_{mode}.csv").write_text(outcome.leaderboard_csv)
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
