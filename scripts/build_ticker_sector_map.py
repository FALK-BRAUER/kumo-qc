#!/usr/bin/env python3
"""
Build a static ticker -> {sector, etf} map for the polygon universe.

The performance_bct strategy uses a STATIC polygon ticker list (no CoarseFundamental),
so MorningstarSectorCode is never populated at runtime. Experiments that gate per-stock
by sector (#155, #156, P2d) need this precomputed map instead.

Source: FMP company profile (sector field). Mapped to SPDR sector ETFs.
Output: algorithm/performance_bct/ticker_sector_map.json  -> {ticker: {sector, etf}}
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UNIVERSE = os.path.join(ROOT, "algorithm/performance_bct/polygon_universe_equity200_fy2025.json")
OUT = os.path.join(ROOT, "algorithm/performance_bct/ticker_sector_map.json")

# FMP sector name -> SPDR sector ETF
SECTOR_ETF = {
    "Technology": "XLK",
    "Communication Services": "XLC",
    "Consumer Cyclical": "XLY",
    "Consumer Defensive": "XLP",
    "Healthcare": "XLV",
    "Industrials": "XLI",
    "Real Estate": "XLRE",
    "Financial Services": "XLF",
    "Energy": "XLE",
    "Basic Materials": "XLB",
    "Utilities": "XLU",
}


def fmp_key() -> str:
    out = subprocess.run(
        ["security", "find-generic-password", "-s", "FMP_API_KEY", "-w"],
        capture_output=True, text=True,
    )
    k = out.stdout.strip()
    if not k:
        sys.exit("FMP_API_KEY not in keychain")
    return k


def main() -> None:
    key = fmp_key()
    uni = json.load(open(UNIVERSE))
    tickers = sorted({t for lst in uni.values() for t in lst})
    print(f"{len(tickers)} tickers")

    from concurrent.futures import ThreadPoolExecutor

    def fetch(sym: str):
        url = f"https://financialmodelingprep.com/stable/profile?symbol={sym}&apikey={key}"
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                data = json.load(r)
            if isinstance(data, list) and data:
                sector = data[0].get("sector") or ""
                return sym, {"sector": sector, "etf": SECTOR_ETF.get(sector)}
        except Exception as e:
            return sym, {"_error": str(e)}
        return sym, None

    result: dict = {}
    missing: list = []
    with ThreadPoolExecutor(max_workers=10) as ex:
        for sym, val in ex.map(fetch, tickers):
            if val and "_error" not in val:
                result[sym] = val
            else:
                missing.append(sym)
    print(f"  fetched {len(result)}, missing {len(missing)}")

    # sequential retry for rate-limited misses
    if missing:
        retry, still = missing, []
        for attempt in range(3):
            still = []
            for sym in retry:
                _, val = fetch(sym)
                if val and "_error" not in val:
                    result[sym] = val
                else:
                    still.append(sym)
                time.sleep(0.25)
            print(f"  retry {attempt+1}: recovered {len(retry)-len(still)}, still {len(still)}")
            if not still:
                break
            retry = still
        missing = still

    unmapped = [t for t, v in result.items() if v["etf"] is None]
    json.dump(result, open(OUT, "w"), indent=2, sort_keys=True)
    print(f"\nwrote {OUT}: {len(result)} mapped, {len(missing)} missing profile, "
          f"{len(unmapped)} no-ETF (unknown sector)")
    if missing:
        print("MISSING:", ",".join(missing))
    if unmapped:
        print("NO-ETF:", ",".join(f"{t}:{result[t]['sector']}" for t in unmapped))


if __name__ == "__main__":
    main()
