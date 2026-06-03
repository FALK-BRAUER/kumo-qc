"""#364 R3 entry-confirm tournament — on the R1-C base (the champion candidate). Q1+Q3 2025.

R1 winner R1-C (rotation, both gates). R2 = profit-take CAPS the per-quarter floor (R1-C stands).
R3 turns to the ENTRY-CONFIRM family — the only live entry lever — which changes the TRADE SET
(better entries → higher floor; NO floor-capping issue, unlike profit-take). George's known alpha is
the gap-UP asymmetry (BCT). Bracket/swap the base BctIntradayGapVolConfirm(gap_threshold=0.03,
vol_mult=1.0, window_bars=6):
  - R3-A STRICTER : gap_threshold 0.05, vol_mult 1.5 — only strong gap-ups on loud volume.
  - R3-B LOOSER   : gap_threshold 0.02, vol_mult 0.8 — more entries (brackets the base).
  - R3-C SWAP     : bct_intraday_hold_confirm (vol_mult 1.5, window_bars 24) — hold-ABOVE-Tenkan +
                    rising-vol instead of the gap-up gate (the meaningful swap; the reclaim-CROSS
                    algo fires ~0 on gap-ups).
floor-proxy decides vs R1-C base (9f5ed2fd520a); > on BOTH windows → champion candidate → 6-window.

Usage: SWEEP_WORKERS=4 python3 scripts/run_364_r3_tournament.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_ROOT), str(_ROOT / "src"), str(_ROOT / "scripts")]
os.environ.setdefault("DOCKER_HOST", "unix:///Users/falk/.docker/run/docker.sock")

from sweeps.adapters.local_lean import WarmupGate  # noqa: E402
from sweeps.adapters.qc_local_prod import make_local_run  # noqa: E402
from sweeps.run_sweep import run_sweep  # noqa: E402
from sweeps.types import PhaseChoice, SweepConfig, Window  # noqa: E402

# R1-C base (the champion candidate): S1 base + the winning rotation (both gates, momentum-select).
_R1C_BASE = (
    PhaseChoice("protective_stop", "cloud_protective_stop", (), 0),
    PhaseChoice("exit_hard", "cloud_adherence_trail", (), 0),
    PhaseChoice("sizing", "flat_pct_heatcap", (("position_pct", 0.05),), 0),
    PhaseChoice("exit_rotation", "rotation_v2",
                (("evict_select", "momentum"), ("gain_floor_pct", 0.10),
                 ("adx_falling_gate", True), ("no_new_high_days", 10)), 0),
)


def _entry(impl: str, params: tuple) -> PhaseChoice:
    # entry_selection codegen preserves the PreFlightStaleness guard + replaces the ALGO slot.
    return PhaseChoice("entry_selection", impl, params, 0)


R3_A = SweepConfig(choices=_R1C_BASE + (_entry("bct_intraday_gap_vol_confirm",
                   (("gap_threshold", 0.05), ("vol_mult", 1.5), ("window_bars", 6))),),
                   continuous_weekly=True)
R3_B = SweepConfig(choices=_R1C_BASE + (_entry("bct_intraday_gap_vol_confirm",
                   (("gap_threshold", 0.02), ("vol_mult", 0.8), ("window_bars", 6))),),
                   continuous_weekly=True)
R3_C = SweepConfig(choices=_R1C_BASE + (_entry("bct_intraday_hold_confirm",
                   (("vol_mult", 1.5), ("window_bars", 24))),),
                   continuous_weekly=True)
CONFIGS = [("R3-A_gap_strict", R3_A), ("R3-B_gap_loose", R3_B), ("R3-C_hold_swap", R3_C)]
Q1 = Window(name="w1_2025q1", start="2025-01-01", end="2025-03-31")
Q3 = Window(name="w3_2025q3", start="2025-07-01", end="2025-09-30")


def main() -> None:
    workers = int(os.environ.get("SWEEP_WORKERS", "4"))
    print("=== #364 R3 entry-confirm tournament (on R1-C base; baseline 9f5ed2fd520a) ===", flush=True)
    for label, cfg in CONFIGS:
        print(f"  {label:18} {cfg.config_hash}", flush=True)
    gate = WarmupGate() if workers > 1 else None
    out = run_sweep([c for _, c in CONFIGS], make_local_run(warmup_gate=gate), windows=[Q1, Q3],
                    max_workers=workers, pins=("run364-r3", "entry-confirm", "ec_tourney_v1"),
                    min_windows=2)
    print("\n=== LEADERBOARD ===")
    print(out.leaderboard_csv)
    if out.failures:
        print(f"\nFAILURES: {[(f.config.config_hash, f.error[:300]) for f in out.failures]}")
    print("\nNEXT: windowed floor-proxy per config_hash vs R1-C base + entry-confirm fire counts.")


if __name__ == "__main__":
    main()
