#!/usr/bin/env python3
"""Daily universe refresh — fetch top-200 US equity by dollar volume from Polygon."""

import argparse
import json
import os
import subprocess
import sys
from datetime import date, timedelta
from typing import List, Set

import requests


def get_polygon_api_key() -> str:
    """Read from macOS keychain service 'polygon-api-key'."""
    try:
        return subprocess.check_output(
            ["security", "find-generic-password", "-s", "polygon-api-key", "-w"],
            text=True,
        ).strip()
    except subprocess.CalledProcessError:
        print("ERROR: No polygon-api-key found in macOS keychain")
        print("Add with: security add-generic-password -s polygon-api-key -w YOUR_KEY")
        sys.exit(1)


def fetch_grouped_daily(date_str: str, api_key: str) -> List[dict]:
    """
    Fetch daily aggregates from Polygon grouped by ticker.
    
    API: GET /v2/aggs/grouped/locale/us/market/stocks/{date}
    """
    url = f"https://api.polygon.io/v2/aggs/grouped/locale/us/market/stocks/{date_str}"
    params = {"apiKey": api_key, "adjusted": "true"}
    
    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    data = response.json()
    
    if data.get("status") != "OK":
        raise RuntimeError(f"Polygon API error: {data.get('status')}")
    
    return data.get("results", [])


def fetch_top_equity_universe(
    api_key: str,
    trade_date: date = None,
    limit: int = 200,
    min_price: float = 5.0,
    min_dv: float = 5_000_000,
) -> List[str]:
    """
    Fetch top-N US equity tickers by dollar volume from Polygon.
    
    Uses grouped daily aggregates API for previous trading day.
    
    Filter: US equity, active, price > min_price, dollar_volume > min_dv.
    Sort by dollar_volume descending.
    Return top `limit` tickers.
    """
    if trade_date is None:
        trade_date = date.today() - timedelta(days=1)
    
    date_str = trade_date.strftime("%Y-%m-%d")
    print(f"Fetching grouped daily data for {date_str}...")
    
    results = fetch_grouped_daily(date_str, api_key)
    
    if not results:
        print(f"WARNING: No data returned for {date_str}")
        return []
    
    # Filter and calculate dollar volume
    tickers = []
    for result in results:
        ticker = result.get("T", "")
        vwap = result.get("vw", 0)  # Volume-weighted average price
        volume = result.get("v", 0)
        dollar_volume = vwap * volume
        
        # Skip if missing data
        if not ticker or vwap <= 0 or volume <= 0:
            continue
        
        # Apply filters
        if vwap < min_price:
            continue
        if dollar_volume < min_dv:
            continue
        
        tickers.append({
            "ticker": ticker,
            "price": vwap,
            "volume": volume,
            "dollar_volume": dollar_volume,
        })
    
    # Sort by dollar volume descending
    tickers.sort(key=lambda x: x["dollar_volume"], reverse=True)
    
    # Return top N ticker symbols
    top_tickers = [t["ticker"] for t in tickers[:limit]]
    
    print(f"Filtered {len(results)} → {len(tickers)} tickers → top {len(top_tickers)}")
    if top_tickers:
        print(f"Top 5: {top_tickers[:5]}")
    
    return top_tickers


def write_universe_json(tickers: List[str], output_path: str, trade_date: date = None):
    """Write universe in same format as polygon_universe_equity200_fy2025.json."""
    if trade_date is None:
        trade_date = date.today()
    
    date_str = trade_date.strftime("%Y-%m-%d")
    data = {date_str: tickers}
    
    # Check if file exists and append to it (date-keyed format)
    if os.path.exists(output_path):
        with open(output_path, 'r') as f:
            existing_data = json.load(f)
        existing_data[date_str] = tickers
        data = existing_data
    
    with open(output_path, 'w') as f:
        json.dump(data, f, indent=2)
    
    print(f"Wrote {len(tickers)} tickers to {output_path} for {date_str}")


def upload_to_qc(json_path: str, project_id: str = "32033824"):
    """Call upload_universe.py to push to QC project."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(script_dir)
    upload_script = os.path.join(repo_root, "scripts", "upload_universe.py")
    
    if not os.path.exists(upload_script):
        print(f"WARNING: upload_universe.py not found at {upload_script}")
        print("Skipping QC upload (manual upload required)")
        return False
    
    result = subprocess.run(
        [sys.executable, upload_script, "--json-path", json_path, "--project-id", project_id],
        capture_output=True,
        text=True,
    )
    
    if result.returncode != 0:
        print(f"Upload failed: {result.stderr}")
        return False
    
    print(result.stdout)
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Daily universe refresh from Polygon API"
    )
    parser.add_argument(
        "--output",
        default="data/universe_live.json",
        help="Output JSON path (date-keyed format)"
    )
    parser.add_argument(
        "--date",
        type=lambda d: date.fromisoformat(d),
        default=None,
        help="Trade date to fetch (YYYY-MM-DD, default: yesterday)"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=200,
        help="Number of tickers to select"
    )
    parser.add_argument(
        "--min-price",
        type=float,
        default=5.0,
        help="Minimum price filter ($)"
    )
    parser.add_argument(
        "--min-dv",
        type=float,
        default=5_000_000,
        help="Minimum dollar volume filter ($)"
    )
    parser.add_argument(
        "--project-id",
        default="32033824",
        help="QC project ID for upload"
    )
    parser.add_argument(
        "--skip-upload",
        action="store_true",
        help="Write JSON only, skip QC upload"
    )
    args = parser.parse_args()
    
    # Read API key from keychain
    api_key = get_polygon_api_key()
    
    # Determine trade date (yesterday if not specified)
    trade_date = args.date
    if trade_date is None:
        trade_date = date.today() - timedelta(days=1)
    
    print(f"Refreshing universe for trade date: {trade_date}")
    print(f"Parameters: limit={args.limit}, min_price=${args.min_price}, min_dv=${args.min_dv:,.0f}")
    
    # Fetch tickers from Polygon
    try:
        tickers = fetch_top_equity_universe(
            api_key,
            trade_date,
            args.limit,
            args.min_price,
            args.min_dv
        )
    except requests.exceptions.HTTPError as e:
        print(f"ERROR: Polygon API request failed: {e}")
        if e.response.status_code == 401:
            print("Check your Polygon API key in macOS keychain")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: Failed to fetch universe: {e}")
        sys.exit(1)
    
    if not tickers:
        print("ERROR: No tickers returned from Polygon")
        sys.exit(1)
    
    # Resolve output path
    output_path = args.output
    if not os.path.isabs(output_path):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        repo_root = os.path.dirname(script_dir)
        output_path = os.path.join(repo_root, output_path)
    
    # Ensure output directory exists
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    # Write to JSON
    write_universe_json(tickers, output_path, trade_date)
    
    # Upload to QC if requested
    if not args.skip_upload:
        print("\nUploading to QC...")
        upload_to_qc(output_path, args.project_id)
    
    print(f"\n✓ Done: {len(tickers)} tickers refreshed for {trade_date}")


if __name__ == "__main__":
    main()
