#!/usr/bin/env python3
"""Precompute the v2 dynamic universe: full liquid substrate via tradeability FLOORS only.

ARCH2-U2 / #220 (re-grounded). NO snapshot, NO fixed list, NO top-N, NO DV-ranking,
NO cap. A per-trading-date eligible SET computed ONLY from bars dated <= that date
(no hindsight, survivorship-clean: delisted tickers vanish after their last bar,
newly-listed appear once they have history). Variable-size daily set.

MODEL (Falk, re-grounded): the universe gates TRADEABILITY, never selects. EVERY name
that clears the floors that day is in. SELECTION is the signal phase's job
(bct_score_full, George's 8-condition, score>=7). Floor in, rate after — no liquidity/DV
logic leaks into selection. If compute ever forces a reduction, RAISE the liquidity floor
and document it as a perf limit — NEVER reintroduce a top-N.

Substrate: data/equity/usa/daily/<ticker>.zip, each a single CSV with rows
    YYYYMMDD 00:00,Open,High,Low,Close,Volume
OHLC are in DECI-CENTS (price$ = field / 10_000); Volume is shares.
    dollar_volume$ = (Close / 10_000) * Volume

Eligibility AS OF a date D (using only bars with date <= D) — the ONLY universe gate:
  (a) latest close (the bar at-or-before D, i.e. the most recent) >= min_price, AND
  (b) trailing adv_window-day mean dollar-volume >= min_avg_dollar_volume,
and the ticker must have at least adv_window bars up to and incl D.
Every eligible ticker is kept (sorted, for determinism). No rank, no cut.

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
    min_price: float,
    min_avg_dollar_volume: float,
    adv_window: int,
    limit_tickers: int | None = None,
) -> dict[str, list[str]]:
    """Return {date_str -> [eligible tickers sorted]} for the floors-only liquid substrate.

    Implementation: build two wide frames (close, trailing-mean DV) indexed by the
    union of all trading dates, columns = tickers. A ticker's value is NaN on dates
    where it has < adv_window bars up to and incl that date (point-in-time guard).
    Then per date, keep EVERY ticker that clears both floors. No rank, no cut.
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
        # Trailing adv_window mean: min_periods=adv_window => NaN until enough history.
        # This enforces "only appears once it has >= adv_window bars up to and incl D".
        dvmean = frame["dollar_volume"].rolling(window=adv_window, min_periods=adv_window).mean()
        close_cols[ticker] = frame["close"]
        dvmean_cols[ticker] = dvmean

    if not dvmean_cols:
        return {}

    close_df = pd.DataFrame(close_cols).sort_index()
    dvmean_df = pd.DataFrame(dvmean_cols).reindex(close_df.index)

    # Eligibility mask = the ONLY universe gate. Have a trailing-mean (>= adv_window
    # bars), close >= min_price, dv_mean >= min_avg_dollar_volume. A NaN close (ticker
    # not yet/no longer listed on that date) or NaN dvmean fails the comparison
    # (NaN >= x is False) -> excluded. Good.
    eligible = (
        dvmean_df.notna()
        & (close_df >= min_price)
        & (dvmean_df >= min_avg_dollar_volume)
    )

    universe: dict[str, list[str]] = {}
    columns = list(eligible.columns)

    for date, elig_row in eligible.iterrows():
        # EVERY substrate trading date (= the de-facto calendar) gets a key, even if
        # zero-eligible (empty list). Completeness-by-construction: a consumer's "missing
        # date" then unambiguously means a NON-trading day, NOT a silent precompute gap
        # (#182's other trap).
        date_key = date.strftime("%Y-%m-%d")
        mask = elig_row.to_numpy(dtype=bool)
        if not mask.any():
            universe[date_key] = []
            continue
        universe[date_key] = sorted(columns[i] for i in range(len(columns)) if mask[i])

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


def auto_out_name(min_price: float, min_avg_dollar_volume: float, adv_window: int) -> str:
    return (
        f"liquid_p{int(min_price)}"
        f"_adv{int(min_avg_dollar_volume)}_w{adv_window}"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--min-price", type=float, default=5.0, help="min latest close, $ (tradeability floor)")
    ap.add_argument("--min-avg-dollar-volume", type=float, default=5_000_000.0,
                    help="min trailing-mean dollar volume, $ (tradeability floor)")
    ap.add_argument("--adv-window", type=int, default=20, help="trailing trading-day window for ADV mean")
    ap.add_argument("--data-dir", type=Path, default=Path("data/equity/usa/daily"))
    ap.add_argument("--out", type=Path, default=None, help="output JSON path (auto under data/universe if omitted)")
    ap.add_argument("--limit-tickers", type=int, default=None, help="cap tickers (for fast tests)")
    args = ap.parse_args(argv)

    universe = build_universe(
        data_dir=args.data_dir,
        min_price=args.min_price,
        min_avg_dollar_volume=args.min_avg_dollar_volume,
        adv_window=args.adv_window,
        limit_tickers=args.limit_tickers,
    )

    fingerprint = content_hash(universe)
    params: dict[str, Any] = {
        "min_price": args.min_price,
        "min_avg_dollar_volume": args.min_avg_dollar_volume,
        "adv_window": args.adv_window,
        "data_dir": str(args.data_dir),
        "limit_tickers": args.limit_tickers,
    }

    out_path = args.out
    if out_path is None:
        out_path = Path("data/universe") / (
            auto_out_name(args.min_price, args.min_avg_dollar_volume, args.adv_window) + ".json"
        )
    out_path.parent.mkdir(parents=True, exist_ok=True)

    meta_block = {
        "model": "floors-only (tradeability gate, no top-N/rank/cap; selection lives in signal phase)",
        "params": params,
        "min_price": args.min_price,
        "min_avg_dollar_volume": args.min_avg_dollar_volume,
        "adv_window": args.adv_window,
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
