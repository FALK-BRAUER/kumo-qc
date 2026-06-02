"""CLI driver for the (B) signal-winner candidate-universe generator (#303 learn-substrate input).

Emits the FULL daily candidate population (every score>=7 signal-winner + its signal-time context)
to a deterministic JSONL artifact the kumo-lab mine joins onto its forward-outcome oracle. The
funnel/scoring core lives in sweeps.archive.candidates (parity-safe — imports the SAME pure scorer
+ floors the live strategy uses). See that module's docstring for the funnel def + parity contract.

Usage:
    # per-year, coarse universe computed live-equivalent from local daily zips (any year):
    PYTHONPATH=src:build python3 scripts/gen_candidate_universe.py --year 2024
    PYTHONPATH=src:build python3 scripts/gen_candidate_universe.py --years 2024 2023 2022 2021 2025

    # FY2025 from the polygon snapshot (the 3c9cb7b8 universe) instead of local-coarse:
    PYTHONPATH=src:build python3 scripts/gen_candidate_universe.py --fy2025-snapshot

    # C1-parity mode (no floors — score the full coarse universe; count matches funnel_signal_count):
    PYTHONPATH=src:build python3 scripts/gen_candidate_universe.py --year 2024 --no-floors

Output: results/archive/candidates/<year>.jsonl  (one header line + one row per signal-winner).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Repo root on sys.path so `sweeps.*` resolves when run as a script (pytest adds it via pythonpath).
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from sweeps.archive.candidates import (
    DEFAULT_MIN_SCORE,
    DEFAULT_PARABOLIC_THRESHOLD,
    generate_window,
    generate_year,
    load_universe,
    write_jsonl,
)

_REPO = Path(__file__).resolve().parent.parent
_OUT_DIR = _REPO / "results" / "archive" / "candidates"


def _run_year(year: int, *, min_score: int, parabolic_threshold: float, floors: bool) -> Path:
    header, rows = generate_year(
        year,
        min_score=min_score,
        parabolic_threshold=parabolic_threshold,
        apply_funnel_floors=floors,
    )
    out = _OUT_DIR / f"{year}.jsonl"
    write_jsonl(header, rows, out)
    n_funnel = sum(
        1 for r in rows if r.passed_prefilter and r.passed_floors and r.passed_parabolic
    )
    print(
        f"FY{year}: {len(rows)} score>={min_score} rows across {header['n_dates']} dates "
        f"({n_funnel} funnel signal_winners) -> {out}"
    )
    return out


def _run_fy2025_snapshot(*, min_score: int, parabolic_threshold: float, floors: bool) -> Path:
    universe = load_universe()
    header, rows = generate_window(
        sorted(universe.keys()),
        universe,
        min_score=min_score,
        parabolic_threshold=parabolic_threshold,
        apply_funnel_floors=floors,
    )
    out = _OUT_DIR / "2025_snapshot.jsonl"
    write_jsonl(header, rows, out)
    print(f"FY2025 (polygon snapshot): {len(rows)} score>={min_score} rows -> {out}")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="(B) signal-winner candidate-universe generator (#303).")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--year", type=int, help="single fiscal year (local-coarse-equivalent universe)")
    g.add_argument("--years", type=int, nargs="+", help="multiple fiscal years")
    g.add_argument(
        "--fy2025-snapshot", action="store_true",
        help="use the polygon_universe_equity200_fy2025.json snapshot (the 3c9cb7b8 universe)",
    )
    ap.add_argument("--min-score", type=int, default=DEFAULT_MIN_SCORE)
    ap.add_argument("--parabolic-threshold", type=float, default=DEFAULT_PARABOLIC_THRESHOLD)
    ap.add_argument(
        "--no-floors", action="store_true",
        help="C1-parity mode: skip prefilter/floors/rank (score full coarse universe)",
    )
    args = ap.parse_args(argv)
    floors = not args.no_floors

    if args.fy2025_snapshot:
        _run_fy2025_snapshot(
            min_score=args.min_score, parabolic_threshold=args.parabolic_threshold, floors=floors
        )
        return 0

    years = [args.year] if args.year is not None else args.years
    for y in years:
        _run_year(
            y, min_score=args.min_score,
            parabolic_threshold=args.parabolic_threshold, floors=floors,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
