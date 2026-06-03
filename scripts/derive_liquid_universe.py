"""Derive the UNION dynamic liquid universe from the coarse CSVs (#325 backfill scope).

The local-intraday backfill (build_minute_from_parquet) is scoped to the names the strategy can
SELECT — the UNION of the dynamic daily coarse-passing sets across the window (NOT a frozen
snapshot; CONVENTIONS forbids frozen universe). A name liquid in Jan but not Dec must still be
backfilled (the coarse filter is point-in-time daily). This emits that union: every ticker passing
the coarse floor (price>=$10, avg-DV>=$100M) on ANY day in the range.

Usage: python3 scripts/derive_liquid_universe.py <YYYY_glob> [<YYYY_glob> ...] > liquid.txt
  e.g. python3 scripts/derive_liquid_universe.py 2024 2025 > /tmp/liquid_2024_2025.txt
Emits a comma-separated UPPERCASE ticker list (for build_minute_from_parquet --tickers).
"""
import csv
import glob
import sys
from pathlib import Path

MIN_PRICE = 10.0
MIN_DV = 100_000_000.0
COARSE = Path(__file__).resolve().parents[1] / "data" / "equity" / "usa" / "fundamental" / "coarse"


def derive(year_globs: list[str]) -> set[str]:
    liquid: set[str] = set()
    files: list[str] = []
    for yg in year_globs:
        files += glob.glob(str(COARSE / f"{yg}*.csv"))
    for fp in sorted(files):
        with open(fp) as f:
            for row in csv.reader(f):
                # SID,ticker,close,volume,dollar_volume,has_fundamental_data,price_factor,split_factor
                try:
                    close = float(row[2]); dv = float(row[4]); tk = row[1]
                except (IndexError, ValueError):
                    continue
                if close >= MIN_PRICE and dv >= MIN_DV:
                    liquid.add(tk.upper())
    return liquid


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("usage: derive_liquid_universe.py <YYYY> [<YYYY> ...]")
    names = derive(sys.argv[1:])
    sys.stderr.write(f"union liquid names (price>=${MIN_PRICE:.0f} & DV>=${MIN_DV/1e6:.0f}M): {len(names)}\n")
    print(",".join(sorted(names)))
