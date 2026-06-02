"""C1 — local BCT signal-count harness (settles the "78 orders/FY is too sparse" question).

QUESTION: is the DAILY 8-condition BCT signal flagging ~90 score>=7 winners PER DAY (→ the
sparsity is downstream — a confirm/regime/hold effect or a bug) or ~5-10 per day (→ the signal
itself is selective, 78/FY is legit-George)?

PARITY: this harness does NOT reimplement the 8 conditions. It loads a daily OHLCV frame from
the local LEAN zips, slices it AS-OF the decision date (no look-ahead), and calls
`phases.shared.oracle_helpers.score_from_daily_frame` — the SAME pure scoring core the QC live
path runs (score_symbol → _fetch_ohlcv → score_from_daily_frame). Local-vs-cloud data deltas are
fine for an order-of-magnitude call (90 vs 5-10).

Usage:
    PYTHONPATH=src:build python3 scripts/funnel_signal_count.py [--dates N] [--threshold 7]
    PYTHONPATH=src:build python3 scripts/funnel_signal_count.py --all
"""
from __future__ import annotations

import argparse
import io
import json
import zipfile
from pathlib import Path
from statistics import mean, median

import numpy as np
import pandas as pd

from phases.shared.oracle_helpers import _DAILY_BARS, score_from_daily_frame

_REPO = Path(__file__).resolve().parent.parent
_UNIVERSE_JSON = _REPO / "algorithm" / "performance_bct" / "polygon_universe_equity200_fy2025.json"
_DAILY_DIR = _REPO / "data" / "equity" / "usa" / "daily"
_PRICE_SCALE = 10000.0  # LEAN daily zips store OHLC * 10000


def load_universe(path: Path = _UNIVERSE_JSON) -> dict[str, list[str]]:
    """date (YYYY-MM-DD) -> [tickers active that date]."""
    with path.open() as fh:
        return json.load(fh)


def load_daily_frame(ticker: str, daily_dir: Path = _DAILY_DIR) -> pd.DataFrame | None:
    """Read a LEAN daily zip into an OHLCV DataFrame (DatetimeIndex, prices unscaled).

    Returns None if the zip is missing. Columns: open/high/low/close/volume.
    """
    zip_path = daily_dir / f"{ticker.lower()}.zip"
    if not zip_path.exists():
        return None
    with zipfile.ZipFile(zip_path) as zf:
        name = zf.namelist()[0]
        raw = zf.read(name).decode()
    rows = []
    for line in raw.strip().split("\n"):
        if not line:
            continue
        ts, o, h, lo, c, v = line.split(",")
        rows.append(
            (ts.split(" ")[0], float(o), float(h), float(lo), float(c), float(v))
        )
    if not rows:
        return None
    df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
    df = df.set_index("date").sort_index()
    for col in ("open", "high", "low", "close"):
        df[col] = df[col] / _PRICE_SCALE
    return df[["open", "high", "low", "close", "volume"]]


def slice_as_of(df: pd.DataFrame, as_of: pd.Timestamp, bars: int = _DAILY_BARS) -> pd.DataFrame:
    """Bars with index <= as_of (NO look-ahead), keeping the last `bars` of them.

    Mirrors the LEAN History([sym], 700, DAILY) call the cloud path makes after close on the
    decision date: the most recent `bars` daily bars up to and including `as_of`.
    """
    upto = df[df.index <= as_of]
    return upto.tail(bars)


def score_universe_on_date(
    date_str: str,
    tickers: list[str],
    daily_dir: Path = _DAILY_DIR,
) -> dict[str, int]:
    """Score every ticker active on `date_str` as-of that date. Returns the score histogram
    {score: count} over tickers that scored (None results — missing data / warmup — excluded)."""
    as_of = pd.Timestamp(date_str)
    hist: dict[int, int] = {}
    for ticker in tickers:
        df = load_daily_frame(ticker, daily_dir)
        if df is None:
            continue
        daily = slice_as_of(df, as_of)
        result = score_from_daily_frame(daily)
        if result is None:
            continue
        s = int(result["score"])
        hist[s] = hist.get(s, 0) + 1
    return hist


def _count_at_least(hist: dict[int, int], threshold: int) -> int:
    return sum(c for s, c in hist.items() if s >= threshold)


def sample_dates(all_dates: list[str], n: int) -> list[str]:
    """Evenly spread n dates across the sorted date list (order-of-magnitude sampling)."""
    if n >= len(all_dates):
        return all_dates
    idx = np.linspace(0, len(all_dates) - 1, n).round().astype(int)
    return [all_dates[i] for i in sorted(set(idx))]


def run(num_dates: int, threshold: int, use_all: bool) -> dict[str, object]:
    universe = load_universe()
    all_dates = sorted(universe.keys())
    dates = all_dates if use_all else sample_dates(all_dates, num_dates)

    per_date_winners: list[int] = []
    per_date_at6: list[int] = []
    per_date_at8: list[int] = []
    per_date_scored: list[int] = []
    rows = []

    for d in dates:
        tickers = universe[d]
        hist = score_universe_on_date(d, tickers)
        n_thr = _count_at_least(hist, threshold)
        n6 = _count_at_least(hist, 6)
        n8 = _count_at_least(hist, 8)
        scored = sum(hist.values())
        per_date_winners.append(n_thr)
        per_date_at6.append(n6)
        per_date_at8.append(n8)
        per_date_scored.append(scored)
        rows.append((d, len(tickers), scored, n6, n_thr, n8))
        print(
            f"{d}  universe={len(tickers):>4}  scored={scored:>4}  "
            f">=6:{n6:>4}  >={threshold}:{n_thr:>4}  >=8:{n8:>4}"
        )

    def stats(xs: list[int]) -> dict[str, float]:
        if not xs:
            return {"mean": 0, "median": 0, "min": 0, "max": 0}
        return {"mean": round(mean(xs), 2), "median": median(xs), "min": min(xs), "max": max(xs)}

    summary = {
        "n_dates": len(dates),
        "threshold": threshold,
        "winners_per_day": stats(per_date_winners),
        "ge6_per_day": stats(per_date_at6),
        "ge8_per_day": stats(per_date_at8),
        "scored_per_day": stats(per_date_scored),
    }

    print("\n" + "=" * 70)
    print(f"SAMPLED {len(dates)} trading dates from FY2025 (universe ~200/day)")
    print(f"n(score>={threshold})/day : {summary['winners_per_day']}")
    print(f"n(score>=6)/day  : {summary['ge6_per_day']}")
    print(f"n(score>=8)/day  : {summary['ge8_per_day']}")
    print(f"scored/day (data present): {summary['scored_per_day']}")
    print("=" * 70)
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description="Local BCT daily signal-count harness (C1).")
    ap.add_argument("--dates", type=int, default=24, help="number of dates to sample (default 24)")
    ap.add_argument("--threshold", type=int, default=7, help="winner score threshold (default 7)")
    ap.add_argument("--all", action="store_true", help="score all FY2025 dates (slow)")
    args = ap.parse_args()
    run(args.dates, args.threshold, args.all)


if __name__ == "__main__":
    main()
