#!/usr/bin/env python3
"""Rebuild LEAN daily equity zips from RAW intraday parquet (not back-adjusted SQLite).

Root cause this fixes: the old LEAN daily zips were built from kumo-trader
kumo-prod.db `ohlcv`, which is BACK-ADJUSTED → corrupts Ichimoku math
(ABT 2025-02-04 = $123.34 adjusted vs ~$126 raw). This sources from raw 5-min
parquet and aggregates Regular Trading Hours (09:30-16:00 ET) → daily OHLCV.

Parquet layout: kumo-trader/data/intraday/<YYYY-MM-DD>.parquet (one day, all
tickers). Columns: ticker, datetime, open, high, low, close, volume, date.
Range available: 2021-05-12 .. 2026-05-08.

Output (overwrites): data/equity/usa/daily/<lean>.zip + map_files + factor_files.
LEAN daily csv line: "YYYYMMDD 00:00,O*10000,H*10000,L*10000,C*10000,Vol".
"""
from __future__ import annotations
import glob, os, sys, zipfile
from collections import defaultdict
from pathlib import Path
import pandas as pd

PARQ = "/Users/falk/projects/kumo-trader/data/intraday"
OUT = Path("/Users/falk/projects/kumo-qc/data/equity/usa")
RTH_START = 9 * 60 + 30   # 570
RTH_END = 16 * 60         # 960  (bar-open times; last RTH 5-min bar opens 15:55)

def lean_name(t: str) -> str:
    return str(t).lower().replace("-", ".")

def pi(v: float) -> int:
    return int(round(float(v) * 10000))

def main() -> None:
    files = sorted(glob.glob(f"{PARQ}/*.parquet"))
    if not files:
        print("NO PARQUET FILES", file=sys.stderr); sys.exit(1)
    print(f"parquet files: {len(files)} ({os.path.basename(files[0])} .. {os.path.basename(files[-1])})", flush=True)

    # acc[ticker] -> list of (ymd, o, h, l, c, v); each parquet is one day so one row per ticker/file
    acc: dict[str, list[tuple]] = defaultdict(list)
    n = len(files)
    for i, f in enumerate(files):
        df = pd.read_parquet(f, columns=["ticker", "datetime", "open", "high", "low", "close", "volume"])
        dt = pd.to_datetime(df["datetime"])
        tmin = dt.dt.hour * 60 + dt.dt.minute
        mask = (tmin >= RTH_START) & (tmin < RTH_END)
        df = df.loc[mask].copy()
        if df.empty:
            continue
        df["_dt"] = dt.loc[mask].values
        df = df.sort_values("_dt")  # ensure first=open, last=close by time
        ymd = pd.to_datetime(df["_dt"].iloc[0]).strftime("%Y%m%d")
        g = df.groupby("ticker").agg(
            o=("open", "first"), h=("high", "max"),
            l=("low", "min"), c=("close", "last"), v=("volume", "sum"),
        )
        for ticker, r in g.iterrows():
            acc[ticker].append((ymd, r.o, r.h, r.l, r.c, int(r.v)))
        if (i + 1) % max(1, n // 8) == 0 or i + 1 == n:
            print(f"  progress {i+1}/{n} ({100*(i+1)//n}%) files, tickers so far={len(acc)}", flush=True)

    daily = OUT / "daily"; mapd = OUT / "map_files"; facd = OUT / "factor_files"
    for d in (daily, mapd, facd):
        d.mkdir(parents=True, exist_ok=True)

    print(f"writing {len(acc)} ticker zips...", flush=True)
    written = 0
    for ticker, rows in acc.items():
        rows.sort(key=lambda x: x[0])  # by ymd
        lean = lean_name(ticker)
        lines = [f"{ymd} 00:00,{pi(o)},{pi(h)},{pi(l)},{pi(c)},{int(v)}" for ymd, o, h, l, c, v in rows]
        blob = "\n".join(lines) + "\n"
        with zipfile.ZipFile(daily / f"{lean}.zip", "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(f"{lean}.csv", blob)
        first = rows[0][0]
        (mapd / f"{lean}.csv").write_text(f"{first},{lean},Q\n20501231,{lean},Q\n", encoding="utf-8")
        (facd / f"{lean}.csv").write_text("19700101,1,1\n", encoding="utf-8")
        written += 1
    print(f"DONE: {written} tickers written to {daily}", flush=True)

if __name__ == "__main__":
    main()
