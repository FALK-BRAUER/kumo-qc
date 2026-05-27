#!/usr/bin/env python3
"""Generate LEAN coarse fundamental files from existing daily OHLCV data."""

import csv
import zipfile
from datetime import date, timedelta
from pathlib import Path
from typing import Optional, Tuple

import pandas as pd


def find_lean_data_dir() -> Path:
    """Locate LEAN equity daily data directory."""
    candidates = [
        Path("data/equity/usa/daily"),
        Path("/Lean/Data/equity/usa/daily"),
        Path(__file__).parent.parent / "data/equity/usa/daily",
    ]
    for d in candidates:
        if d.exists():
            print(f"Found LEAN data directory: {d}")
            return d
    raise FileNotFoundError("LEAN daily data directory not found")


def read_daily_from_zip(zip_path: Path, target_date: date) -> Optional[Tuple[float, float]]:
    """
    Read close price and volume for a specific date from LEAN zip.
    
    LEAN stores data in CSV format:
    date,open,high,low,close,volume
    YYYYMMDD HH:MM,scaled_price,...,scaled_price,...,scaled_price,...,scaled_price,volume
    
    Prices are scaled by 10000 for precision.
    """
    try:
        with zipfile.ZipFile(zip_path) as z:
            csv_name = z.namelist()[0]
            with z.open(csv_name) as f:
                df = pd.read_csv(f, header=None, names=['date', 'open', 'high', 'low', 'close', 'volume'])
                
                # Parse date column (format: YYYYMMDD HH:MM)
                df['date'] = pd.to_datetime(df['date'].astype(str).str[:8], format='%Y%m%d')
                
                # Filter for target date
                row = df[df['date'].dt.date == target_date]
                if row.empty:
                    return None
                
                # LEAN prices are scaled by 10000
                close = float(row['close'].iloc[0]) / 10000
                volume = float(row['volume'].iloc[0])
                
                return close, volume
    except Exception as e:
        return None


def generate_coarse_file(
    data_dir: Path,
    output_dir: Path,
    target_date: date,
    min_price: float = 5.0,
    min_dv: float = 5_000_000,
    top_n: int = 200,
) -> Tuple[int, int, int]:
    """
    Generate one coarse CSV file for a specific date.
    
    Returns: (total_tickers, qualified_tickers, top_n_selected)
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    
    records = []
    total_tickers = 0
    
    for zip_file in data_dir.glob("*.zip"):
        ticker = zip_file.stem.upper()
        total_tickers += 1
        
        result = read_daily_from_zip(zip_file, target_date)
        if result is None:
            continue
        
        close, volume = result
        dollar_volume = close * volume
        
        if close < min_price or dollar_volume < min_dv:
            continue
        
        records.append({
            "Symbol": ticker,
            "Price": f"{close:.2f}",
            "Volume": f"{int(volume)}",
            "DollarVolume": f"{int(dollar_volume)}",
            "HasFundamentalData": "True",
        })
    
    # Sort by dollar volume descending
    records.sort(key=lambda r: float(r["DollarVolume"]), reverse=True)
    
    # Take top N
    top_records = records[:top_n]
    
    output_file = output_dir / f"{target_date.strftime('%Y%m%d')}.csv"
    with open(output_file, 'w', newline='') as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["Symbol", "Price", "Volume", "DollarVolume", "HasFundamentalData"],
        )
        writer.writeheader()
        writer.writerows(top_records)
    
    return total_tickers, len(records), len(top_records)


def main():
    data_dir = find_lean_data_dir()
    output_dir = data_dir.parent / "fundamental" / "coarse"
    
    # Generate for FY2025 period (Jan-Dec 2025)
    # Plus warmup period (~460 trading days before 2025-01-01)
    # Approximate: 460 trading days ~ 650 calendar days
    start_date = date(2023, 3, 15)  # ~460 trading days before 2025-01-01
    end_date = date(2025, 12, 31)
    
    total_files = 0
    total_tickers = 0
    all_qualified = 0
    all_top_n = 0
    
    current = start_date
    while current <= end_date:
        # Skip weekends
        if current.weekday() < 5:
            try:
                t, q, n = generate_coarse_file(
                    data_dir,
                    output_dir,
                    current,
                    min_price=5.0,
                    min_dv=5_000_000,
                    top_n=200,
                )
                if q > 0:
                    total_files += 1
                    if total_tickers == 0:
                        total_tickers = t  # Assume same count each day
                    all_qualified += q
                    all_top_n += n
                    if total_files <= 5 or total_files % 50 == 0:
                        print(f"{current}: {t} total, {q} qualified, {n} top-N")
            except Exception as e:
                print(f"Error on {current}: {e}")
        
        current += timedelta(days=1)
    
    print(f"\nDone: {total_files} coarse files in {output_dir}")
    print(f"Total tickers checked: ~{total_tickers} per day")
    print(f"Average qualified: {all_qualified // max(total_files, 1):.0f} per day")
    print(f"Top-N selected: {all_top_n // max(total_files, 1):.0f} per day")
    
    # Sample DV values
    if total_files > 0:
        sample_file = sorted(output_dir.glob("*.csv"))[-1]
        with open(sample_file) as f:
            reader = csv.DictReader(f)
            rows = list(reader)[:5]
            print(f"\nSample from {sample_file.name}:")
            for row in rows:
                dv = int(row['DollarVolume'])
                print(f"  {row['Symbol']}: ${dv:,.0f} (price ${row['Price']}, vol {row['Volume']})")


if __name__ == "__main__":
    main()
