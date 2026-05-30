#!/usr/bin/env python3
"""Build ETF LEAN data + universe JSON from kumo-trader Parquet files.

Steps:
1. Aggregate 5-min Parquet → daily OHLCV for each ETF
2. Write LEAN zip files to data/equity/usa/daily/<etf>.zip
3. Generate etf_universe_fy2025.json (date -> [ETF list]) for algorithm use
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).parent.parent
PARQUET_DIR = REPO_ROOT.parent / "kumo-trader" / "data" / "intraday"
DATA_DIR = REPO_ROOT / "data" / "equity" / "usa" / "daily"
ALGO_DIR = REPO_ROOT / "algorithm" / "performance_bct"

ETFS = [
    "SMH", "SOXX", "QQQ", "SPY",
    "XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLB", "XLU", "XLRE", "XLC",
    "CIBR", "HACK", "GLD", "SLV", "GDX",
    "XBI", "IBB", "OIH",
    "TLT", "HYG",
    "ARKK", "KWEB", "EEM", "EWJ",
    "TAN",
    # ETF-1: Additional tickers for two-pool system
    "DBB", "IYZ", "HDV", "SCHD",
]

# FY2025 + FY2026-YTD range
DATE_START = "2025-01-01"
DATE_END   = "2026-04-30"


def to_lean_row(dt: str, o: float, h: float, lo: float, c: float, v: int) -> str:
    date_part = dt.replace("-", "")
    return f"{date_part} 00:00,{int(o*10000)},{int(h*10000)},{int(lo*10000)},{int(c*10000)},{v}"


def write_lean_zip(zip_path: Path, ticker: str, daily_df: pd.DataFrame) -> None:
    lean = ticker.lower()
    csv_name = f"{lean}.csv"

    existing_rows: list[str] = []
    existing_last = ""
    if zip_path.exists():
        with zipfile.ZipFile(zip_path) as z:
            try:
                content = z.read(csv_name).decode()
                existing_rows = [l for l in content.strip().split("\n") if l]
                existing_last = existing_rows[-1][:8] if existing_rows else ""
            except Exception:
                pass

    new_rows = []
    for _, row in daily_df.iterrows():
        date_str = str(row["date"])
        lean_date = date_str.replace("-", "")
        if lean_date <= existing_last:
            continue
        new_rows.append(to_lean_row(
            date_str, row["open"], row["high"], row["low"], row["close"], int(row["volume"])
        ))

    if not new_rows:
        return

    all_rows = existing_rows + new_rows
    combined = "\n".join(all_rows) + "\n"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr(csv_name, combined)
    zip_path.write_bytes(buf.getvalue())
    print(f"  {ticker}: +{len(new_rows)} rows → {zip_path.name}")


def build_daily_from_parquet(etfs: list[str]) -> dict[str, pd.DataFrame]:
    """Read all Parquet files, aggregate to daily OHLCV per ETF."""
    parquet_files = sorted(PARQUET_DIR.glob("*.parquet"))
    etf_set = set(etfs)

    all_bars: list[pd.DataFrame] = []
    for pf in parquet_files:
        date_str = pf.stem  # YYYY-MM-DD
        if date_str < DATE_START or date_str > DATE_END:
            continue
        try:
            df = pd.read_parquet(pf, columns=["ticker", "open", "high", "low", "close", "volume"])
            df = df[df["ticker"].isin(etf_set)]
            if df.empty:
                continue
            # Aggregate to daily
            daily = df.groupby("ticker").agg(
                open=("open", "first"),
                high=("high", "max"),
                low=("low", "min"),
                close=("close", "last"),
                volume=("volume", "sum"),
            ).reset_index()
            daily["date"] = date_str
            all_bars.append(daily)
        except Exception as e:
            print(f"  WARN {pf.name}: {e}")

    if not all_bars:
        return {}

    combined = pd.concat(all_bars, ignore_index=True)
    result = {}
    for ticker, grp in combined.groupby("ticker"):
        result[ticker] = grp.sort_values("date").reset_index(drop=True)
    return result


def build_universe_json(daily_by_ticker: dict[str, pd.DataFrame]) -> dict[str, list[str]]:
    """Build {date: [tickers_with_data_on_that_date]} mapping."""
    date_map: dict[str, list[str]] = {}
    for ticker, df in daily_by_ticker.items():
        for date_str in df["date"]:
            date_map.setdefault(date_str, []).append(ticker)
    # Sort tickers per date for determinism
    return {d: sorted(tickers) for d, tickers in sorted(date_map.items())}


def main():
    print(f"Reading Parquet from: {PARQUET_DIR}")
    print(f"ETFs: {ETFS}")
    print(f"Range: {DATE_START} → {DATE_END}")
    print()

    print("Step 1: Aggregating Parquet → daily OHLCV...")
    daily_by_ticker = build_daily_from_parquet(ETFS)
    found = sorted(daily_by_ticker.keys())
    missing = [e for e in ETFS if e not in daily_by_ticker]
    print(f"  Found: {found}")
    if missing:
        print(f"  Missing from Parquet: {missing}")

    print("\nStep 2: Writing LEAN zip files...")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for ticker, df in daily_by_ticker.items():
        zip_path = DATA_DIR / f"{ticker.lower()}.zip"
        write_lean_zip(zip_path, ticker, df)

    print("\nStep 3: Building etf_universe_fy2025.json...")
    universe = build_universe_json(daily_by_ticker)
    out_path = ALGO_DIR / "etf_universe_fy2025.json"
    with open(out_path, "w") as f:
        json.dump(universe, f, separators=(",", ":"))
    print(f"  Written: {out_path}")
    print(f"  Dates: {min(universe)} → {max(universe)}")
    print(f"  Sample ({min(universe)}): {universe[min(universe)]}")

    print("\nDone.")


if __name__ == "__main__":
    main()
