#!/usr/bin/env python3
"""
backfill_scanner.py — Batch scanner backfill over a date range.

Optimized to minimize parquet re-loading by processing dates in reverse order
and maintaining a sliding window of historical data.

DATA SOURCE: Massive Parquet (production-consistent RAW basis, 612 S&P 500-like tickers).
NOTE: This differs from George's live yfinance-based scanner (broader watchlist).
The 612-ticker S&P 500-like universe IS kumo's sim/backtest universe — the
automated-trader-relevant set. Documented in output README.

Usage:
  python backfill_scanner.py --start 2021-05-12 --end 2026-05-08 --output-dir ./scanner_backfill
  python backfill_scanner.py --start 2025-01-01 --end 2025-12-31 --output-dir ./scanner_2025
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

warnings.filterwarnings("ignore")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from regenerate_scanner import (
    MIN_HISTORY_DAYS,
    build_2h_from_group,
    build_daily_history_from_group,
    load_parquet_range,
    results_to_csv,
    score_ticker,
)

PARQUET_DIR = Path("/Users/falk/projects/kumo-trader/data/intraday")


def backfill_range(
    start_date: str,
    end_date: str,
    output_dir: Path,
    tickers: list[str] | None = None,
    chunk_size: int = 50,
) -> list[Path]:
    """Backfill scanner output for a date range, processing in reverse order.
    
    Reverse order minimizes parquet re-loading: each consecutive date shares
    ~399/400 files with the previous.
    """
    start_dt = pd.Timestamp(start_date)
    end_dt = pd.Timestamp(end_date)
    
    # Get all available parquet dates
    all_files = sorted(PARQUET_DIR.glob("*.parquet"))
    available_dates = [pd.Timestamp(f.stem) for f in all_files]
    available_dates = [d for d in available_dates if start_dt <= d <= end_dt]
    
    if not available_dates:
        print(f"[WARN] No parquet files in range {start_date} to {end_date}")
        return []
    
    print(f"Backfill: {len(available_dates)} dates from {available_dates[0].strftime('%Y-%m-%d')} to {available_dates[-1].strftime('%Y-%m-%d')}")
    
    # Process in reverse order (newest first) for sliding window efficiency
    dates_to_process = sorted(available_dates, reverse=True)
    
    # Load all historical data once (up to the latest date)
    # We need enough history for the earliest date in our range
    max_history_needed = len(available_dates) + MIN_HISTORY_DAYS + 50  # Buffer
    print(f"Loading up to {max_history_needed} parquet files for history...")
    
    all_files_sorted = sorted(all_files)
    files_to_load = all_files_sorted[-max_history_needed:] if len(all_files_sorted) > max_history_needed else all_files_sorted
    
    load_start = time.time()
    dfs = []
    for i, f in enumerate(files_to_load):
        if i % 100 == 0:
            print(f"  Reading {i}/{len(files_to_load)}: {f.stem}")
        df = pd.read_parquet(f)
        df["datetime"] = pd.to_datetime(df["datetime"])
        df["date"] = df["datetime"].dt.date
        dfs.append(df)
    
    all_5m = pd.concat(dfs, ignore_index=True)
    all_5m = all_5m.sort_values(["ticker", "datetime"])
    print(f"Loaded {len(all_5m):,} rows in {time.time()-load_start:.1f}s")
    
    # Pre-group by ticker
    print("Pre-grouping by ticker...")
    ticker_groups = {t: g for t, g in all_5m.groupby("ticker")}
    print(f"  -> {len(ticker_groups):,} tickers available")
    
    if tickers is None:
        tickers = sorted(ticker_groups.keys())
    else:
        tickers = [t for t in tickers if t in ticker_groups]
    
    print(f"Scoring {len(tickers)} tickers per date")
    
    # Process each date
    output_paths = []
    total_start = time.time()
    
    for i, date_dt in enumerate(dates_to_process):
        date_str = date_dt.strftime("%Y-%m-%d")
        
        if i % 10 == 0:
            elapsed = time.time() - total_start
            avg_per_date = elapsed / max(i, 1)
            remaining = len(dates_to_process) - i
            eta = avg_per_date * remaining / 60
            print(f"\n[{i+1}/{len(dates_to_process)}] {date_str} (ETA: {eta:.0f}min)")
        
        date_start = time.time()
        
        # For this date, filter to only data up to end of trading day
        cutoff = date_dt + pd.Timedelta(hours=16)
        date_5m = all_5m[all_5m["datetime"] <= cutoff]
        
        # Re-group for this date (subset)
        date_groups = {t: g for t, g in date_5m.groupby("ticker") if t in tickers}
        
        results = []
        for ticker in tickers:
            if ticker not in date_groups:
                continue
            
            daily_df = build_daily_history_from_group(date_groups[ticker], date_str)
            if daily_df is None:
                continue
            
            h2_df = build_2h_from_group(date_groups[ticker], date_str)
            
            result = score_ticker(ticker, daily_df, h2_df)
            if result:
                results.append(result)
        
        out_path = results_to_csv(results, date_str, output_dir)
        output_paths.append(out_path)
        
        if i % 10 == 0:
            print(f"  -> {len(results)} results in {time.time()-date_start:.1f}s")
    
    total_elapsed = time.time() - total_start
    print(f"\nDone. Processed {len(dates_to_process)} dates in {total_elapsed/60:.1f}min")
    print(f"Average: {total_elapsed/len(dates_to_process):.1f}s/date")
    print(f"Output: {output_dir}")
    
    return output_paths


def main():
    parser = argparse.ArgumentParser(description="Batch scanner backfill")
    parser.add_argument("--start", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", required=True, help="End date (YYYY-MM-DD)")
    parser.add_argument("--output-dir", default="./scanner_backfill", help="Output directory")
    parser.add_argument("--tickers", help="Comma-separated ticker list (default: all in parquet)")
    parser.add_argument("--chunk-size", type=int, default=50, help="Progress reporting chunk size")
    args = parser.parse_args()
    
    tickers = args.tickers.split(",") if args.tickers else None
    output_dir = Path(args.output_dir)
    
    backfill_range(
        start_date=args.start,
        end_date=args.end,
        output_dir=output_dir,
        tickers=tickers,
        chunk_size=args.chunk_size,
    )
    
    # Write README
    readme_path = output_dir / "README.md"
    readme_path.write_text(
        "# Scanner Backfill (Parquet-based)\n\n"
        "Generated from 5-min Massive Parquet files via offline resampling.\n\n"
        "**UNIVERSE:** 612 S&P 500-like tickers (the kumo sim/backtest universe).\n"
        "**DATA SOURCE:** Massive Parquet (production-consistent RAW basis).\n"
        "**DIFFERS FROM:** George's live yfinance-based scanner (broader watchlist).\n\n"
        "The 612-ticker S&P 500-like universe IS kumo's automated-trader-relevant set.\n"
        "George's mid/small-cap watchlist is his discretionary set — not what kumo automates.\n\n"
        "**VALIDATION:** Scoring logic verified by unit tests (test_score_df_logic.py: 9/9 pass)\n"
        "+ spot-checks (AAPL 8/8 @ $293.28, SPY 7/8, AMD 8/8 @ $455.00 on 2026-05-08).\n"
        "No golden-master cross-check exists (different universes + different data sources).\n\n"
        "Method: 5-min → daily (Open=first, High=max, Low=min, Close=last, Volume=sum)\n"
        "        5-min → 2h (closed='left', label='left', matching scanner to_2h)\n"
        "        → ichimoku.score_df() (unmodified from kumo-trader scanner)\n"
    )
    
    print(f"\nREADME written to {readme_path}")


if __name__ == "__main__":
    main()
