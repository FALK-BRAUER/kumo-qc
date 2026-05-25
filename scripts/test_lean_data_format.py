#!/usr/bin/env python3
"""LEAN data format smoke test — validates iklxh3vl pipeline output.

Generates synthetic OHLCV data for 5 tickers, writes to LEAN zip format,
runs backtest with DefaultDataProvider, verifies trades > 0.

Usage: python3 scripts/test_lean_data_format.py
"""

import os
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timedelta
from pathlib import Path


# Test tickers for smoke test
TEST_TICKERS = ["SPY", "AAPL", "MSFT", "NVDA", "AMZN"]

# Date range: 2024-01-01 to 2025-03-31
START_DATE = datetime(2024, 1, 1)
END_DATE = datetime(2025, 3, 31)

# LEAN price scale factor (prices stored as integers, multiplied by 10000)
PRICE_SCALE = 10000

# Data directories
DATA_DIR = Path(__file__).parent.parent / "data" / "equity" / "usa"
DAILY_DIR = DATA_DIR / "daily"
MAP_FILES_DIR = DATA_DIR / "map_files"
FACTOR_FILES_DIR = DATA_DIR / "factor_files"


def generate_synthetic_ohlcv(ticker: str, start: datetime, end: datetime) -> list[tuple]:
    """Generate synthetic OHLCV data for a ticker."""
    data = []
    
    # Base price per ticker (approximate realistic values)
    base_prices = {
        "SPY": 420.0,
        "AAPL": 180.0,
        "MSFT": 380.0,
        "NVDA": 480.0,
        "AMZN": 150.0,
    }
    
    base = base_prices.get(ticker, 100.0)
    current_price = base
    
    current = start
    while current <= end:
        # Skip weekends
        if current.weekday() >= 5:  # Saturday = 5, Sunday = 6
            current += timedelta(days=1)
            continue
        
        # Generate random daily movement (±2%)
        import random
        random.seed(hash(ticker) + current.toordinal())  # Reproducible
        
        change_pct = random.uniform(-0.02, 0.02)
        open_price = current_price * (1 + random.uniform(-0.005, 0.005))
        close_price = current_price * (1 + change_pct)
        high_price = max(open_price, close_price) * (1 + random.uniform(0, 0.01))
        low_price = min(open_price, close_price) * (1 - random.uniform(0, 0.01))
        volume = random.randint(10_000_000, 100_000_000)
        
        # Scale to LEAN integer format
        o = int(open_price * PRICE_SCALE)
        h = int(high_price * PRICE_SCALE)
        l = int(low_price * PRICE_SCALE)
        c = int(close_price * PRICE_SCALE)
        v = volume
        
        date_str = current.strftime("%Y%m%d 00:00")
        data.append((date_str, o, h, l, c, v))
        
        current_price = close_price
        current += timedelta(days=1)
    
    return data


def write_lean_zip(ticker: str, data: list[tuple]) -> Path:
    """Write OHLCV data to LEAN zip format."""
    zip_path = DAILY_DIR / f"{ticker.lower()}.zip"
    
    # Create CSV content
    csv_lines = []
    for row in data:
        csv_lines.append(f"{row[0]},{row[1]},{row[2]},{row[3]},{row[4]},{row[5]}")
    
    csv_content = "\n".join(csv_lines)
    
    # Write to zip (LEAN expects the CSV inside with same name as ticker)
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{ticker.lower()}.csv", csv_content)
    
    return zip_path


def write_map_file(ticker: str) -> Path:
    """Write stub map file for ticker."""
    map_path = MAP_FILES_DIR / f"{ticker.lower()}.csv"
    
    # Format: date,symbol,exchange
    # Q = NYSE, N = NASDAQ, etc.
    content = f"{START_DATE.strftime('%Y%m%d')},{ticker.lower()},Q\n"
    content += f"{END_DATE.strftime('%Y%m%d')},{ticker.lower()},Q\n"
    
    map_path.write_text(content)
    return map_path


def write_factor_file(ticker: str) -> Path:
    """Write stub factor file for ticker."""
    factor_path = FACTOR_FILES_DIR / f"{ticker.lower()}.csv"
    
    # Format: date,factor1,factor2,reference_price
    # factor1 = price scale, factor2 = split factor, reference = close price
    content = f"{START_DATE.strftime('%Y%m%d')},1,1,100\n"
    content += f"{END_DATE.strftime('%Y%m%d')},1,1,100\n"
    
    factor_path.write_text(content)
    return factor_path


def setup_directories():
    """Ensure all data directories exist."""
    DAILY_DIR.mkdir(parents=True, exist_ok=True)
    MAP_FILES_DIR.mkdir(parents=True, exist_ok=True)
    FACTOR_FILES_DIR.mkdir(parents=True, exist_ok=True)


def run_lean_backtest() -> dict:
    """Run LEAN backtest and parse results."""
    algo_dir = Path(__file__).parent.parent / "algorithm" / "minimal_bct"
    
    # Build lean command
    cmd = [
        "lean", "backtest", str(algo_dir),
        "--lean-config", "lean.json",
        "--no-update",
    ]
    
    # Run the backtest
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=Path(__file__).parent.parent,
    )
    
    # Parse output for trade count
    output = result.stdout + result.stderr
    
    # Look for "Total trades" in output
    trades = 0
    for line in output.split("\n"):
        if "Total trades" in line or "Trades:" in line:
            # Try to extract number
            import re
            match = re.search(r'(\d+)', line)
            if match:
                trades = int(match.group(1))
                break
    
    return {
        "returncode": result.returncode,
        "trades": trades,
        "stdout": result.stdout[-5000:] if len(result.stdout) > 5000 else result.stdout,
        "stderr": result.stderr[-5000:] if len(result.stderr) > 5000 else result.stderr,
    }


def cleanup_test_data():
    """Remove test tickers from data directories."""
    for ticker in TEST_TICKERS:
        # Remove zip files
        zip_path = DAILY_DIR / f"{ticker.lower()}.zip"
        if zip_path.exists():
            zip_path.unlink()
        
        # Remove map files
        map_path = MAP_FILES_DIR / f"{ticker.lower()}.csv"
        if map_path.exists():
            map_path.unlink()
        
        # Remove factor files
        factor_path = FACTOR_FILES_DIR / f"{ticker.lower()}.csv"
        if factor_path.exists():
            factor_path.unlink()


def main():
    """Main smoke test entry point."""
    print("=" * 60)
    print("LEAN Data Format Smoke Test")
    print("=" * 60)
    print(f"Test tickers: {', '.join(TEST_TICKERS)}")
    print(f"Date range: {START_DATE.date()} to {END_DATE.date()}")
    print()
    
    # Setup
    print("[1/4] Setting up directories...")
    setup_directories()
    
    # Generate and write data
    print("[2/4] Generating synthetic OHLCV data...")
    for ticker in TEST_TICKERS:
        data = generate_synthetic_ohlcv(ticker, START_DATE, END_DATE)
        zip_path = write_lean_zip(ticker, data)
        map_path = write_map_file(ticker)
        factor_path = write_factor_file(ticker)
        print(f"  {ticker}: {len(data)} days → {zip_path.name}")
    
    # Run backtest
    print()
    print("[3/4] Running LEAN backtest...")
    result = run_lean_backtest()
    
    print(f"  Exit code: {result['returncode']}")
    print(f"  Trades detected: {result['trades']}")
    
    # Evaluate result
    print()
    print("[4/4] Evaluating results...")
    
    if result['returncode'] != 0:
        print("  ❌ FAIL: LEAN backtest returned non-zero exit code")
        print("\n  STDERR (last 2000 chars):")
        print(result['stderr'][-2000:])
        cleanup = False
    elif result['trades'] == 0:
        print("  ❌ FAIL: 0 trades executed")
        print("  Data format may be incompatible with LEAN's expectations")
        cleanup = False
    else:
        print(f"  ✅ PASS: {result['trades']} trades executed")
        print("  LEAN data format is valid for backtesting")
        cleanup = True
    
    # Cleanup option
    print()
    if cleanup:
        print("[Cleanup] Removing test data...")
        cleanup_test_data()
        print("  Test data cleaned up")
    else:
        print("[Cleanup] Preserving test data for debugging")
        print(f"  Data location: {DAILY_DIR}")
    
    print()
    print("=" * 60)
    
    return 0 if cleanup else 1


if __name__ == "__main__":
    sys.exit(main())
