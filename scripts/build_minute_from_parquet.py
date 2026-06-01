#!/usr/bin/env python3
"""Build LEAN MINUTE-resolution equity zips from RAW 5-min Massive parquet (#275, Option C).

⚠️ HONESTY (CONVENTIONS "Execution environment"): these "minute"-resolution zips carry 5-MINUTE
Massive bars, NOT true 1-minute. Our Massive intraday feed is natively 5-min (78 RTH bars/day =
George's BCT decision cadence); LEAN has no native 5-min resolution, so we store the 5-min bars in
the `minute/` tree and the intraday execution clock consumes them DIRECTLY (no consolidator —
Option C, HQ-approved #275). Consequences a reader/indicator MUST know:
  - the intraday execution timeframe IS 5-min by data construction;
  - intraday indicator PERIODS are in 5-MIN-BAR units (e.g. an intraday Tenkan(9) spans 45 min);
  - this is RAW (not back-adjusted) — same discipline as the daily build (adjusted corrupts Ichimoku).

PARITY (CRITICAL, carries to #277): the cloud-confirm BT MUST run on THIS SAME 5-min-as-minute data
(upload it to QC), NOT QC's native 1-min minute data — else local(5-min) != cloud(1-min) is a NEW
parity surface. The smoke proved delivery-TIMING is clean; this ensures the DATA is identical too.

Parquet layout: kumo-trader/data/intraday/<YYYY-MM-DD>.parquet (one day, all tickers).
Columns: ticker, datetime, open, high, low, close, volume. Range 2021-05-12 .. 2026-05-08.

Output: data/equity/usa/minute/<lean>/<YYYYMMDD>_trade.zip
  entry: <YYYYMMDD>_<lean>_minute_trade.csv
  line:  <ms_since_midnight>,O*10000,H*10000,L*10000,C*10000,V   (ms = bar START time, deci-cents)

FAIL-LOUD spacing guard (#261 class): each day's bars MUST be ~300s-spaced. A mis-spaced /
true-1-min / irregular feed RAISES SpacingError (catches a data mislabel before it silently
corrupts the intraday indicators). --strict (default) raises; --report logs offenders + skips them.

Usage:
  python3 scripts/build_minute_from_parquet.py --start 20250101 --end 20251231 [--tickers AAPL,MSFT]
  python3 scripts/build_minute_from_parquet.py --smoke           # one day, a few tickers, validate format
"""
from __future__ import annotations

import argparse
import glob
import os
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

import pandas as pd

PARQ = "/Users/falk/projects/kumo-trader/data/intraday"
# Default OUT = the SHARED data dir (where the daily build also writes; worktrees symlink to it).
# Overridable via --out so a run never crosses the worktree boundary unexpectedly (#273 isolation).
DEFAULT_OUT = Path("/Users/falk/projects/kumo-qc/data/equity/usa")
RTH_START = 9 * 60 + 30   # 570  — first RTH 5-min bar opens 09:30
RTH_END = 16 * 60         # 960  — last RTH 5-min bar opens 15:55, closes 16:00
EXPECTED_SPACING_S = 300.0  # 5-min bars
SPACING_TOL_S = 1.0


class SpacingError(Exception):
    """Raised when intraday bars are not ~300s-spaced — a data mislabel (true-1-min / irregular)
    that would silently corrupt the 5-min intraday indicators (#261 fail-loud class, #275)."""


def lean_name(t: str) -> str:
    return str(t).lower().replace("-", ".")


def pi(v: float) -> int:
    return int(round(float(v) * 10000))


def ms_of_day(ts: pd.Timestamp) -> int:
    return int((ts.hour * 3600 + ts.minute * 60 + ts.second) * 1000)


def _check_spacing(ticker: str, ymd: str, times: list[pd.Timestamp], strict: bool) -> bool:
    """RAISE (strict) or return False (report) if the RTH bars are not ~300s-spaced."""
    if len(times) < 2:
        return True  # a 1-bar day can't be mis-spaced
    deltas = [(times[i] - times[i - 1]).total_seconds() for i in range(1, len(times))]
    bad = [d for d in deltas if abs(d - EXPECTED_SPACING_S) > SPACING_TOL_S]
    # tolerate a FEW gaps (halts/missing bars) but not a systematic mis-spacing (e.g. all 60s).
    # NOTE: the max(3,…) floor assumes near-full RTH days (78 bars); a degenerate ≤4-bar all-1-min
    # day slips the floor — not a practical risk (a real day is 78 bars, a 1-min mislabel ~390),
    # and such a stub day is already too truncated to feed indicators meaningfully.
    if bad and len(bad) > max(3, len(deltas) // 10):
        modal = max(set(deltas), key=deltas.count)
        msg = (f"{ticker} {ymd}: {len(bad)}/{len(deltas)} RTH bar-gaps off 300s "
               f"(modal {modal}s) — NOT 5-min spacing. A true-1-min/irregular feed would "
               f"silently corrupt the 5-min intraday indicators (#275 Option C expects 5-min).")
        if strict:
            raise SpacingError(msg)
        print(f"  ⚠️ SKIP {msg}", file=sys.stderr)
        return False
    return True


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", help="YYYYMMDD inclusive")
    ap.add_argument("--end", help="YYYYMMDD inclusive")
    ap.add_argument("--tickers", help="comma list (default: all)")
    ap.add_argument("--smoke", action="store_true", help="one day, a few tickers, validate")
    ap.add_argument("--report", action="store_true", help="log+skip mis-spaced days (default: --strict raise)")
    ap.add_argument("--out", help=f"output equity dir (default {DEFAULT_OUT})")
    args = ap.parse_args()
    strict = not args.report
    out = Path(args.out) if args.out else DEFAULT_OUT

    files = sorted(glob.glob(f"{PARQ}/*.parquet"))
    if not files:
        print("NO PARQUET FILES", file=sys.stderr); sys.exit(1)

    def in_range(f: str) -> bool:
        d = os.path.basename(f)[:10].replace("-", "")
        if args.start and d < args.start:
            return False
        if args.end and d > args.end:
            return False
        return True

    files = [f for f in files if in_range(f)]
    if args.smoke:
        files = files[:1]
    if not files:
        print("NO PARQUET FILES IN RANGE", file=sys.stderr); sys.exit(1)
    want = {t.strip().lower() for t in args.tickers.split(",")} if args.tickers else None
    if args.smoke and not want:
        want = {"aapl", "msft", "spy"}

    print(f"parquet files: {len(files)} ({os.path.basename(files[0])} .. {os.path.basename(files[-1])})", flush=True)

    minute_dir = out / "minute"
    minute_dir.mkdir(parents=True, exist_ok=True)
    written = skipped = 0
    n = len(files)
    for i, f in enumerate(files):
        df = pd.read_parquet(f, columns=["ticker", "datetime", "open", "high", "low", "close", "volume"])
        df["_dt"] = pd.to_datetime(df["datetime"])
        tmin = df["_dt"].dt.hour * 60 + df["_dt"].dt.minute
        df = df.loc[(tmin >= RTH_START) & (tmin < RTH_END)].copy()
        if want is not None:
            df = df.loc[df["ticker"].str.lower().isin(want)]
        if df.empty:
            continue
        ymd = pd.to_datetime(df["_dt"].iloc[0]).strftime("%Y%m%d")
        for ticker, g in df.groupby("ticker"):
            g = g.sort_values("_dt")
            times = list(g["_dt"])
            if not _check_spacing(str(ticker), ymd, times, strict):
                skipped += 1
                continue
            lean = lean_name(ticker)
            lines = [
                f"{ms_of_day(t)},{pi(r.open)},{pi(r.high)},{pi(r.low)},{pi(r.close)},{int(r.volume)}"
                for t, (_, r) in zip(times, g.iterrows())
            ]
            blob = "\n".join(lines) + "\n"
            tdir = minute_dir / lean
            tdir.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(tdir / f"{ymd}_trade.zip", "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr(f"{ymd}_{lean}_minute_trade.csv", blob)
            written += 1
        if (i + 1) % max(1, n // 8) == 0 or i + 1 == n:
            print(f"  progress {i+1}/{n} days ({100*(i+1)//n}%), zips written={written} skipped={skipped}", flush=True)

    print(f"DONE: {written} ticker-day minute zips ({skipped} skipped) → {minute_dir}", flush=True)
    if skipped and strict:
        print("(strict mode: no mis-spaced days reached here — any would have raised)", flush=True)


if __name__ == "__main__":
    main()
