#!/usr/bin/env python3
"""Precompute the v2 dynamic universe: point-in-time top-N by trailing dollar volume.

ARCH2-U / #220. NO snapshot, NO fixed list — a per-trading-date ranking computed
ONLY from bars dated <= that date (no hindsight, survivorship-clean: delisted
tickers vanish after their last bar, newly-listed appear once they have history).

Substrate: data/equity/usa/daily/<ticker>.zip, each a single CSV with rows
    YYYYMMDD 00:00,Open,High,Low,Close,Volume
OHLC are in DECI-CENTS (price$ = field / 10_000); Volume is shares.
    dollar_volume$ = (Close / 10_000) * Volume

Eligibility AS OF a date D (using only bars with date <= D):
  (a) latest close (the bar at-or-before D, i.e. the most recent) >= price_floor, AND
  (b) trailing dv_window-day mean dollar-volume >= dv_floor,
and the ticker must have at least dv_window bars up to and incl D.
Eligible tickers are ranked by that trailing-mean DV (desc) and the top N kept.

Output: data/universe/<auto>.json  -> {"YYYY-MM-DD": [tickers sorted], ..., "_universe_meta": {...}}
Sibling: data/universe/<auto>.meta.json -> params + content-hash fingerprint of the
date->set mapping (deterministic: same substrate + same params => same hash).

NO timestamp is emitted (Date.now is blocked in this environment) — the content hash
is the provenance handle.

This is a one-time precompute over ~19k zips. Vectorized per-ticker with pandas
rolling means. Use --limit-tickers K for fast tests.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

DECI_CENTS_PER_DOLLAR = 10_000.0


def _ticker_from_zip(zip_path: Path) -> str:
    """Ticker = zip stem, lowercased to match LEAN's on-disk convention."""
    return zip_path.stem.lower()


def load_ticker_frame(zip_path: Path) -> pd.DataFrame | None:
    """Load one daily zip into a DataFrame indexed by date with a single
    `dollar_volume` column and a `close` column (both in $). Returns None if empty.

    Columns parsed: the CSV has no header; the inner file is <ticker>.csv with rows
    'YYYYMMDD 00:00,O,H,L,C,V'. Close + Volume are all we need.
    """
    try:
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            if not names:
                return None
            with zf.open(names[0]) as fh:
                df = pd.read_csv(
                    fh,
                    header=None,
                    usecols=[0, 4, 5],
                    names=["dt", "close_dc", "volume"],
                    dtype={"close_dc": "float64", "volume": "float64"},
                )
    except (zipfile.BadZipFile, OSError, ValueError):
        return None

    if df.empty:
        return None

    # 'YYYYMMDD 00:00' -> date. Take the YYYYMMDD prefix (first 8 chars) to avoid
    # locale/time parsing overhead.
    date_str = df["dt"].astype(str).str.slice(0, 8)
    df = df.assign(date=pd.to_datetime(date_str, format="%Y%m%d", errors="coerce"))
    df = df.dropna(subset=["date"])
    if df.empty:
        return None

    df["close"] = df["close_dc"] / DECI_CENTS_PER_DOLLAR
    df["dollar_volume"] = df["close"] * df["volume"]
    df = df.set_index("date").sort_index()
    # Defend against duplicate dates within one file (keep last bar of the day).
    df = df[~df.index.duplicated(keep="last")]
    return df[["close", "dollar_volume"]]


def build_universe(
    data_dir: Path,
    n: int,
    price_floor: float,
    dv_floor: float,
    dv_window: int,
    limit_tickers: int | None = None,
) -> dict[str, list[str]]:
    """Return {date_str -> [tickers sorted]} for the point-in-time top-N universe.

    Implementation: build two wide frames (close, trailing-mean DV) indexed by the
    union of all trading dates, columns = tickers. A ticker's value is NaN on dates
    where it has < dv_window bars up to and incl that date (point-in-time guard).
    Then per date, mask by floors and rank by trailing-mean DV desc, take top N.
    """
    zips = sorted(data_dir.glob("*.zip"))
    if limit_tickers is not None:
        zips = zips[:limit_tickers]
    if not zips:
        raise SystemExit(f"no .zip files found in {data_dir}")

    close_cols: dict[str, pd.Series] = {}
    dvmean_cols: dict[str, pd.Series] = {}

    for zp in zips:
        ticker = _ticker_from_zip(zp)
        frame = load_ticker_frame(zp)
        if frame is None or frame.empty:
            continue
        # Trailing dv_window mean: min_periods=dv_window => NaN until enough history.
        # This enforces "only appears once it has >= dv_window bars up to and incl D".
        dvmean = frame["dollar_volume"].rolling(window=dv_window, min_periods=dv_window).mean()
        close_cols[ticker] = frame["close"]
        dvmean_cols[ticker] = dvmean

    if not dvmean_cols:
        return {}

    close_df = pd.DataFrame(close_cols).sort_index()
    dvmean_df = pd.DataFrame(dvmean_cols).reindex(close_df.index)

    # Eligibility mask: have a trailing-mean (>= dv_window bars), close >= price_floor,
    # dv_mean >= dv_floor. A NaN close (ticker not yet/no longer listed on that date)
    # or NaN dvmean fails the comparison (NaN >= x is False) -> excluded. Good.
    eligible = (
        dvmean_df.notna()
        & (close_df >= price_floor)
        & (dvmean_df >= dv_floor)
    )

    # Rank only where eligible; everything else -> -inf so it never makes the top N.
    ranked_dv = dvmean_df.where(eligible, other=-np.inf)

    universe: dict[str, list[str]] = {}
    tickers = np.array(ranked_dv.columns)

    for date, row in ranked_dv.iterrows():
        elig_row = eligible.loc[date]
        if not bool(elig_row.any()):
            # No eligible ticker that day -> omit the date entirely (matches "ticker
            # only appears on dates it qualifies"; an empty list would be misleading).
            continue
        vals = row.to_numpy(dtype="float64")
        # Candidates = finite (eligible) entries.
        cand_idx = np.where(np.isfinite(vals))[0]
        if cand_idx.size == 0:
            continue
        cand_vals = vals[cand_idx]
        # Top N by DV desc. argsort ascending then take the tail; stable for ties.
        order = cand_idx[np.argsort(cand_vals, kind="stable")][::-1]
        top = order[:n]
        chosen = sorted(str(t) for t in tickers[top])
        date_key = date.strftime("%Y-%m-%d")
        universe[date_key] = chosen

    return universe


def content_hash(universe: dict[str, list[str]]) -> str:
    """Deterministic SHA-256 over the date->set mapping. Independent of dict insertion
    order: dates sorted, tickers sorted within each date.
    """
    h = hashlib.sha256()
    for date in sorted(universe):
        h.update(date.encode("utf-8"))
        h.update(b":")
        h.update(",".join(sorted(universe[date])).encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def auto_out_name(n: int, price_floor: float, dv_floor: float, dv_window: int) -> str:
    return (
        f"dynamic_dv_n{n}_p{int(price_floor)}"
        f"_dv{int(dv_floor)}_w{dv_window}"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=1500, help="top-N by trailing DV (universe breadth)")
    ap.add_argument("--price-floor", type=float, default=10.0, help="min latest close, $")
    ap.add_argument("--dv-floor", type=float, default=5_000_000.0, help="min trailing-mean dollar volume, $")
    ap.add_argument("--dv-window", type=int, default=20, help="trailing trading-day window for DV mean")
    ap.add_argument("--data-dir", type=Path, default=Path("data/equity/usa/daily"))
    ap.add_argument("--out", type=Path, default=None, help="output JSON path (auto under data/universe if omitted)")
    ap.add_argument("--limit-tickers", type=int, default=None, help="cap tickers (for fast tests)")
    args = ap.parse_args(argv)

    universe = build_universe(
        data_dir=args.data_dir,
        n=args.n,
        price_floor=args.price_floor,
        dv_floor=args.dv_floor,
        dv_window=args.dv_window,
        limit_tickers=args.limit_tickers,
    )

    fingerprint = content_hash(universe)
    params: dict[str, Any] = {
        "n": args.n,
        "price_floor": args.price_floor,
        "dv_floor": args.dv_floor,
        "dv_window": args.dv_window,
        "data_dir": str(args.data_dir),
        "limit_tickers": args.limit_tickers,
    }

    out_path = args.out
    if out_path is None:
        out_path = Path("data/universe") / (auto_out_name(args.n, args.price_floor, args.dv_floor, args.dv_window) + ".json")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    meta_block = {
        "params": params,
        "n": args.n,
        "price_floor": args.price_floor,
        "dv_floor": args.dv_floor,
        "dv_window": args.dv_window,
        "substrate_fingerprint": "see data/MANIFEST.json",
        "universe_fingerprint": fingerprint,
        "num_dates": len(universe),
    }

    payload: dict[str, Any] = {date: universe[date] for date in sorted(universe)}
    payload["_universe_meta"] = meta_block

    out_path.write_text(json.dumps(payload, separators=(",", ":"), sort_keys=False))

    meta_path = out_path.with_suffix(".meta.json")
    meta_path.write_text(json.dumps(meta_block, indent=2, sort_keys=True))

    print(f"wrote {out_path} ({len(universe)} trading dates)")
    print(f"wrote {meta_path}")
    print(f"universe_fingerprint: {fingerprint}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
