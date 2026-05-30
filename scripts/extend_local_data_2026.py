#!/usr/bin/env python3
"""
Extend local LEAN daily data from 2025-12-31 to 2026-05-20.
Downloads from yfinance for all tickers in equity-200 JSON.
Appends to existing zip files in data/equity/usa/daily/.
"""
import json
import zipfile
import io
from pathlib import Path
from datetime import datetime, date

import yfinance as yf
import pandas as pd

REPO_ROOT = Path(__file__).parent.parent
DATA_DIR = REPO_ROOT / "data" / "equity" / "usa" / "daily"
UNIVERSE_JSON = REPO_ROOT / "algorithm" / "performance_bct" / "polygon_universe_equity200_fy2025.json"

START = "2026-01-01"
END = "2026-05-20"


def to_lean_row(dt: date, open_: float, high: float, low: float, close: float, volume: int) -> str:
    ts = dt.strftime("%Y%m%d") + " 00:00"
    return f"{ts},{int(open_*10000)},{int(high*10000)},{int(low*10000)},{int(close*10000)},{volume}"


def get_existing_last_date(zip_path: Path) -> str | None:
    if not zip_path.exists():
        return None
    try:
        with zipfile.ZipFile(zip_path) as z:
            name = z.namelist()[0]
            content = z.read(name).decode()
            last = content.strip().split("\n")[-1]
            return last[:8]  # YYYYMMDD
    except Exception:
        return None


def append_to_zip(zip_path: Path, new_rows: list[str]) -> None:
    if not zip_path.exists():
        return
    ticker = zip_path.stem.lower()
    csv_name = f"{ticker}.csv"
    with zipfile.ZipFile(zip_path, "r") as z:
        orig = z.read(csv_name).decode()
    combined = orig.rstrip("\n") + "\n" + "\n".join(new_rows) + "\n"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr(csv_name, combined)
    zip_path.write_bytes(buf.getvalue())


def main():
    with open(UNIVERSE_JSON) as f:
        universe = json.load(f)

    tickers = set()
    for v in universe.values():
        tickers.update(v)
    tickers = sorted(tickers)
    print(f"Downloading 2026 data for {len(tickers)} tickers: {START} → {END}")

    ok, skip, fail = 0, 0, 0
    for i, ticker in enumerate(tickers):
        zip_path = DATA_DIR / f"{ticker.lower()}.zip"
        if not zip_path.exists():
            skip += 1
            continue

        last = get_existing_last_date(zip_path)
        if last and last >= "20260501":
            print(f"  [{i+1}/{len(tickers)}] {ticker}: already has 2026 data, skipping")
            skip += 1
            continue

        try:
            df = yf.download(ticker, start=START, end=END, auto_adjust=True, progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            if df.empty:
                print(f"  [{i+1}/{len(tickers)}] {ticker}: no data")
                fail += 1
                continue

            rows = []
            for dt, row in df.iterrows():
                if hasattr(dt, "date"):
                    dt = dt.date()
                rows.append(to_lean_row(dt, row["Open"], row["High"], row["Low"], row["Close"], int(row["Volume"])))

            if not rows:
                skip += 1
                continue

            append_to_zip(zip_path, rows)
            print(f"  [{i+1}/{len(tickers)}] {ticker}: +{len(rows)} rows")
            ok += 1

        except Exception as e:
            print(f"  [{i+1}/{len(tickers)}] {ticker}: ERROR {e}")
            fail += 1

    print(f"\nDone. ok={ok} skip={skip} fail={fail}")


if __name__ == "__main__":
    main()
