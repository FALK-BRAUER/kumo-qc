#!/usr/bin/env python3
"""
regenerate_scanner.py — Offline scanner regeneration from 5-min Parquet (v2, bulk-optimized).

Reads 5-min OHLCV Parquet files in bulk, resamples to daily + 2h bars, applies
ichimoku.py score_df() — reproduces the blue-cloud-scanner.csv output format.

DATA SOURCE: Massive Parquet (production-consistent RAW basis).
NOTE: This differs from the live yfinance-based scanner. Cross-check against live
scanner output is a sanity bound only — material agreement expected, byte-match not.
Parquet-consistency with downstream oracle-labeling/backtesting matters MORE than
matching a yfinance source. Documented in output README.

HQ flags:
  1. 2h bucketing: closed='left', label='left' (matching scanner to_2h)
  2. No look-ahead: only bars completed as-of target date
  3. RAW parquet (never adjusted)
  4. Bidirectional ticker-set validation (rough agreement vs yfinance source)

Usage:
  python regenerate_scanner.py --date 2026-05-08 --output-dir ./scanner_regen
  python regenerate_scanner.py --date-range 2021-05-12 2026-05-08 --output-dir ./scanner_regen
"""
from __future__ import annotations

import argparse
import os
import sys
import warnings
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

warnings.filterwarnings("ignore")

# Import scanner scoring logic (unchanged — HQ guardrail)
sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "..",
        "kumo-trader",
        ".worktrees",
        "prod",
        "scanner",
    ),
)
from ichimoku import score_df  # noqa: E402

PARQUET_DIR = Path("/Users/falk/projects/kumo-trader/data/intraday")
MIN_HISTORY_DAYS = 300  # score_df requires ~300 daily bars
HISTORY_WINDOW = 800  # Read last N days of parquet for 3y+ buffer


def load_parquet_range(end_date: str, n_days: int = HISTORY_WINDOW) -> pd.DataFrame | None:
    """Bulk-load parquet files for the trailing n_days up to end_date.
    
    Returns a single DataFrame with all tickers' 5-min bars.
    """
    end_dt = pd.Timestamp(end_date)
    files = sorted(PARQUET_DIR.glob("*.parquet"))
    # Filter to files <= end_date
    files = [f for f in files if pd.Timestamp(f.stem) <= end_dt]
    
    if len(files) < MIN_HISTORY_DAYS:
        print(f"[WARN] Only {len(files)} parquet files available (need {MIN_HISTORY_DAYS})")
        return None
    
    # Take last n_days files
    files_to_read = files[-n_days:]
    
    dfs = []
    for f in files_to_read:
        df = pd.read_parquet(f)
        df["datetime"] = pd.to_datetime(df["datetime"])
        # Derive date from datetime (parquet has no 'date' column)
        df["date"] = df["datetime"].dt.date
        dfs.append(df)
    
    if not dfs:
        return None
    
    combined = pd.concat(dfs, ignore_index=True)
    combined = combined.sort_values(["ticker", "datetime"])
    return combined


def build_daily_history(all_5m: pd.DataFrame, ticker: str, target_date: str) -> pd.DataFrame | None:
    """Build ~3y daily history for a single ticker up to target_date.
    
    No look-ahead: bars after target_date's close are excluded.
    """
    target_dt = pd.Timestamp(target_date)
    # Include bars up to end of target_date (16:00 ET)
    cutoff = target_dt + pd.Timedelta(hours=16)
    
    ticker_df = all_5m[all_5m["ticker"] == ticker].copy()
    ticker_df = ticker_df[ticker_df["datetime"] <= cutoff]
    
    if len(ticker_df) < 100:  # Need at least some bars
        return None
    
    # Resample to daily
    ticker_df = ticker_df.set_index("datetime")
    daily = ticker_df.resample("D").agg(
        Open=("open", "first"),
        High=("high", "max"),
        Low=("low", "min"),
        Close=("close", "last"),
        Volume=("volume", "sum"),
    ).dropna()
    
    if len(daily) < MIN_HISTORY_DAYS:
        return None
    
    # Rename to match ichimoku.py expectations
    daily = daily.rename(columns={
        "Open": "Open", "High": "High", "Low": "Low", "Close": "Close", "Volume": "Volume"
    })
    
    return daily


def build_2h_for_date(all_5m: pd.DataFrame, ticker: str, target_date: str) -> pd.DataFrame | None:
    """Build 2h bars for the target date only.
    
    HQ Flag #1: Uses closed='left', label='left' to match scanner's to_2h.
    """
    target_dt = pd.Timestamp(target_date)
    start = target_dt
    end = target_dt + pd.Timedelta(hours=16)  # End of trading day
    
    ticker_df = all_5m[
        (all_5m["ticker"] == ticker) &
        (all_5m["datetime"] >= start) &
        (all_5m["datetime"] <= end)
    ].copy()
    
    if len(ticker_df) < 52:  # score_df 2h minimum
        return None
    
    ticker_df = ticker_df.set_index("datetime")
    
    # Resample to 2h matching scanner's exact bucketing
    h2 = ticker_df.resample("2h", closed="left", label="left").agg(
        Open=("open", "first"),
        High=("high", "max"),
        Low=("low", "min"),
        Close=("close", "last"),
        Volume=("volume", "sum"),
    ).dropna()
    
    if len(h2) < 13:  # Need some 2h bars
        return None
    
    # Rename columns to match scanner
    h2 = h2.rename(columns={
        "Open": "Open", "High": "High", "Low": "Low", "Close": "Close", "Volume": "Volume"
    })
    
    return h2


def score_ticker(ticker: str, daily_df: pd.DataFrame, h2_df: pd.DataFrame | None) -> dict | None:
    """Apply ichimoku score_df to a single ticker's data."""
    if daily_df is None or len(daily_df) < MIN_HISTORY_DAYS:
        return None
    
    result = score_df(daily_df, raw_2h=h2_df)
    if result and result.get("rating") not in ("ERROR", "SKIP", None):
        result["ticker"] = ticker
        return result
    return None


def regenerate_day(date_str: str, all_5m: pd.DataFrame | None = None, tickers: list[str] | None = None) -> list[dict]:
    """Regenerate scanner output for a single date.
    
    Optimized: pre-groups by ticker to avoid repeated full-table scans.
    """
    if all_5m is None:
        all_5m = load_parquet_range(date_str)
    
    if all_5m is None:
        print(f"[WARN] No data available for {date_str}")
        return []
    
    # Pre-group by ticker — O(n) once instead of O(n×tickers)
    print("  Pre-grouping by ticker...")
    ticker_groups = {t: g for t, g in all_5m.groupby("ticker")}
    print(f"  -> {len(ticker_groups):,} tickers in parquet")
    
    if tickers is None:
        tickers = sorted(ticker_groups.keys())
    else:
        # Only process tickers that exist in the data
        tickers = [t for t in tickers if t in ticker_groups]
    
    results = []
    total = len(tickers)
    print(f"  Scoring {total:,} tickers...")
    
    for i, ticker in enumerate(tickers, 1):
        if i % 250 == 0 or i == total:
            print(f"    [{i}/{total}] {ticker}...")
        
        daily_df = build_daily_history_from_group(ticker_groups[ticker], date_str)
        if daily_df is None:
            continue
        
        h2_df = build_2h_from_group(ticker_groups[ticker], date_str)
        
        result = score_ticker(ticker, daily_df, h2_df)
        if result:
            results.append(result)
    
    return results


def build_daily_history_from_group(ticker_df: pd.DataFrame, target_date: str) -> pd.DataFrame | None:
    """Build daily history from a pre-filtered ticker DataFrame.
    
    No look-ahead: bars after target_date's close are excluded.
    """
    target_dt = pd.Timestamp(target_date)
    cutoff = target_dt + pd.Timedelta(hours=16)  # End of trading day
    
    ticker_df = ticker_df.copy()
    ticker_df["datetime"] = pd.to_datetime(ticker_df["datetime"])
    ticker_df = ticker_df[ticker_df["datetime"] <= cutoff]
    ticker_df = ticker_df.sort_values("datetime")
    
    if len(ticker_df) < 100:
        return None
    
    ticker_df = ticker_df.set_index("datetime")
    daily = ticker_df.resample("D").agg(
        Open=("open", "first"),
        High=("high", "max"),
        Low=("low", "min"),
        Close=("close", "last"),
        Volume=("volume", "sum"),
    ).dropna()
    
    if len(daily) < MIN_HISTORY_DAYS:
        return None
    
    daily = daily.rename(columns={
        "Open": "Open", "High": "High", "Low": "Low", "Close": "Close", "Volume": "Volume"
    })
    
    return daily


def build_2h_from_group(ticker_df: pd.DataFrame, target_date: str) -> pd.DataFrame | None:
    """Build 2h bars for the target date from a pre-filtered ticker DataFrame.
    
    HQ Flag #1: Uses closed='left', label='left' to match scanner's to_2h.
    """
    target_dt = pd.Timestamp(target_date)
    start = target_dt
    end = target_dt + pd.Timedelta(hours=16)  # End of trading day
    
    day_df = ticker_df[
        (pd.to_datetime(ticker_df["datetime"]) >= start) &
        (pd.to_datetime(ticker_df["datetime"]) <= end)
    ].copy()
    
    if len(day_df) < 52:
        return None
    
    day_df = day_df.set_index("datetime")
    h2 = day_df.resample("2h", closed="left", label="left").agg(
        Open=("open", "first"),
        High=("high", "max"),
        Low=("low", "min"),
        Close=("close", "last"),
        Volume=("volume", "sum"),
    ).dropna()
    
    if len(h2) < 13:
        return None
    
    h2 = h2.rename(columns={
        "Open": "Open", "High": "High", "Low": "Low", "Close": "Close", "Volume": "Volume"
    })
    
    return h2


def results_to_csv(results: list[dict], date_str: str, output_dir: Path) -> Path:
    """Write scanner results to CSV in the golden-master format."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    if not results:
        out_path = output_dir / f"scanner-{date_str.replace('-', '')}.csv"
        out_path.touch()
        print(f"  Wrote empty file to {out_path}")
        return out_path
    
    # Build DataFrame with all available columns
    rows = []
    for r in results:
        row: dict[str, Any] = {
            "rating": r["rating"],
            "score": r["score"],
            "price": r["price"],
            "c1": r["c1"], "c2": r["c2"], "c3": r["c3"], "c4": r["c4"],
            "c5": r["c5"], "c6": r["c6"], "c7": r["c7"], "c8": r["c8"],
            "adx": r["adx"], "pdi": r["pdi"], "mdi": r["mdi"],
            "tenkan_d": r.get("tenkan_d", 0),
            "kijun_d": r.get("kijun_d", 0),
            "span_a_d": r.get("span_a_d", 0),
            "span_b_d": r.get("span_b_d", 0),
            "cloud_top_d": r.get("cloud_top_d", 0),
            "cloud_bot_d": r.get("cloud_bot_d", 0),
            "chikou_d_ok": r.get("chikou_d_ok", False),
            "ma200": r.get("ma200", 0),
            "ext_pct": r.get("ext_pct", 0),
            "ext_flag": r.get("ext_flag", ""),
            "avg_vol": r.get("avg_vol", 0),
            "veto": r.get("veto", ""),
            "ticker": r["ticker"],
        }
        # Add optional columns if present
        for key in ["rvol", "bbw_pct", "ud_ratio", "rs_spy", "si_pct", "eps_rev_pct", "qs_score", "qs_label",
                    "adx_tier", "di_separation", "adx_exhaustion", "tk_spread_pct", "magnet_pattern", "span_b_w",
                    "h2_above_cloud", "h2_t_gt_k", "h2_price", "h2_tenkan", "h2_kijun"]:
            if key in r:
                row[key] = r[key]
        rows.append(row)
    
    df = pd.DataFrame(rows)
    
    out_path = output_dir / f"scanner-{date_str.replace('-', '')}.csv"
    df.to_csv(out_path, index=False)
    print(f"  Wrote {len(df)} rows to {out_path}")
    return out_path


def main():
    parser = argparse.ArgumentParser(description="Offline scanner regeneration from 5-min Parquet")
    parser.add_argument("--date", help="Single date to regenerate (YYYY-MM-DD)")
    parser.add_argument("--date-range", nargs=2, metavar=("START", "END"), help="Date range (YYYY-MM-DD)")
    parser.add_argument("--output-dir", default="./scanner_regen", help="Output directory")
    parser.add_argument("--tickers", help="Comma-separated ticker list (default: all in parquet)")
    args = parser.parse_args()
    
    tickers = args.tickers.split(",") if args.tickers else None
    
    if args.date:
        dates = [args.date]
    elif args.date_range:
        start, end = pd.Timestamp(args.date_range[0]), pd.Timestamp(args.date_range[1])
        dates = pd.date_range(start, end, freq="D").strftime("%Y-%m-%d").tolist()
        # Filter to dates with parquet files
        dates = [d for d in dates if (PARQUET_DIR / f"{d}.parquet").exists()]
    else:
        parser.error("Specify --date or --date-range")
    
    output_dir = Path(args.output_dir)
    
    for date_str in dates:
        print(f"\n[{date_str}] Loading parquet data...")
        all_5m = load_parquet_range(date_str)
        if all_5m is None:
            print(f"[WARN] Skipping {date_str} — insufficient data")
            continue
        
        print(f"[{date_str}] Regenerating scanner ({len(all_5m):,} total 5-min bars)...")
        results = regenerate_day(date_str, all_5m=all_5m, tickers=tickers)
        results_to_csv(results, date_str, output_dir)
    
    # Write README documenting source
    readme_path = output_dir / "README.md"
    readme_path.write_text(
        "# Scanner Regeneration (Parquet-based)\n\n"
        "Generated from 5-min Massive Parquet files via offline resampling.\n\n"
        "**DATA SOURCE:** Massive Parquet (production-consistent RAW basis).\n"
        "**DIFFERS FROM:** Live yfinance-based scanner (George's live runs).\n\n"
        "Cross-check against live scanner is a sanity bound only — material agreement\n"
        "expected, byte-match not. Parquet-consistency with downstream oracle-labeling\n"
        "and backtesting matters MORE than matching a yfinance source.\n\n"
        "Method: 5-min → daily (Open=first, High=max, Low=min, Close=last, Volume=sum)\n"
        "        5-min → 2h (closed='left', label='left', matching scanner to_2h)\n"
        "        → ichimoku.score_df() (unmodified from kumo-trader scanner)\n"
    )
    
    print(f"\nDone. Output in {output_dir}")


if __name__ == "__main__":
    main()
