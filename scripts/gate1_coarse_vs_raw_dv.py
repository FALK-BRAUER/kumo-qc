"""GATE 1 (flag-don't-guess): coarse single-day DV vs RAW close*volume, and the trailing-20d
mean DV computed each way, on real artifacts.

The incremental-DV design accumulates the COARSE single-day DV into a rolling 20-day window;
the OLD path computed trailing DV from RAW history close*volume.

SCOPE — READ THIS BEFORE TRUSTING THE 0.000% RESULT:
  This is a LOCAL check, and the 0.000% / 0-flips outcome is TAUTOLOGICAL. The #238 conform
  built the local coarse DollarVolume as raw_close * raw_volume from the SAME daily source
  this script reads back — so coarse DV is bit-identical to raw_close*raw_volume and coarse
  Price is bit-identical to the raw close BY CONSTRUCTION. 0.000% divergence is therefore
  GUARANTEED locally and proves NOTHING about cloud. What it DOES confirm: the parser, the
  field mapping (coarse col2=Price, col4=DollarVolume), and the trailing-20d-mean arithmetic
  are correct — i.e. the rolling-DV math is wired to the right inputs.

  The CLOUD case (QC's vendor coarse feed, potentially split/dividend-ADJUSTED) is NOT proven
  here. Its robustness is ARGUED, not gated: dollar-volume is split-invariant (a k:1 split
  scales price /k and volume *k -> product constant), which is sound for a LIQUIDITY floor
  (a coarse gate, not a price-precision signal like Ichimoku/ATR). CAVEAT: this argument does
  NOT cover dividend adjustment, nor a vendor that derives DV from already-adjusted inputs.
  Those residuals get EMPIRICALLY validated at the post-#240 cloud Step-A active-set parity
  (cloud selection hash vs local), not by this script.

Reads ONLY real artifacts:
  - conformed coarse CSVs: data/equity/usa/fundamental/coarse/YYYYMMDD.csv
      columns: SID, Symbol, Price(close), Volume, DollarVolume, HasFundamental, ?, ?
  - RAW daily zips:        data/equity/usa/daily/<ticker>.zip -> <ticker>.csv
      columns: YYYYMMDD 00:00, O, H, L, C, V  (OHLC scaled x10000)

No estimation. Every number printed comes from the files.
"""
from __future__ import annotations

import csv
import io
import sys
import zipfile
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"
COARSE_DIR = DATA / "equity" / "usa" / "fundamental" / "coarse"
DAILY_DIR = DATA / "equity" / "usa" / "daily"

MIN_PRICE = 10.0
MIN_AVG_DV = 100_000_000.0
ADV_WINDOW = 20
PRICE_SCALE = 10000.0  # LEAN equity OHLC scale in the daily zips


def trading_dates_2025() -> list[str]:
    """YYYYMMDD strings present as REAL (8-col) coarse CSVs in 2025, sorted. Degenerate
    holiday/placeholder files (5-col header-only) are excluded."""
    return sorted(p.stem for p in COARSE_DIR.glob("2025*.csv") if is_real_trading_coarse(p.stem))


def load_coarse_day(yyyymmdd: str) -> dict[str, tuple[float, float]]:
    """{ticker_lower: (coarse_close, coarse_single_day_dv)} for one coarse CSV.

    The standard 8-col schema is: SID, Symbol, Price, Volume, DollarVolume, HasFund, ?, ?.
    A handful of 2025 files are degenerate holiday/placeholder files with a 5-col
    `Symbol,Price,Volume,DollarVolume,HasFundamentalData` header + few/no USA-equity rows;
    those are skipped (header rows are non-numeric; we detect and ignore them)."""
    out: dict[str, tuple[float, float]] = {}
    p = COARSE_DIR / f"{yyyymmdd}.csv"
    with p.open() as fh:
        for row in csv.reader(fh):
            if len(row) < 5:
                continue
            # Standard 8-col rows: ticker=col1, close=col2, dv=col4. Holiday 5-col rows would
            # have ticker=col0 — but those files are non-trading placeholders we don't use.
            if len(row) < 8:
                continue
            ticker = row[1].strip().lower()
            try:
                close = float(row[2])
                dv = float(row[4])
            except ValueError:
                continue  # header line
            out[ticker] = (close, dv)
    return out


def is_real_trading_coarse(yyyymmdd: str) -> bool:
    """A real USA-equity trading day = the standard 8-col schema with many rows."""
    p = COARSE_DIR / f"{yyyymmdd}.csv"
    with p.open() as fh:
        first = fh.readline()
    return first.count(",") >= 7


def load_raw_daily(ticker: str) -> dict[str, tuple[float, float]]:
    """{YYYYMMDD: (raw_close, raw_volume)} from the daily zip. Close de-scaled by 10000."""
    zp = DAILY_DIR / f"{ticker.lower()}.zip"
    if not zp.exists():
        return {}
    out: dict[str, tuple[float, float]] = {}
    with zipfile.ZipFile(zp) as z:
        name = z.namelist()[0]
        with z.open(name) as fh:
            for row in csv.reader(io.TextIOWrapper(fh, "utf-8")):
                if not row:
                    continue
                day = row[0].split(" ")[0]
                close = float(row[4]) / PRICE_SCALE
                vol = float(row[5])
                out[day] = (close, vol)
    return out


def pct(a: float, b: float) -> float:
    """abs % divergence of a vs b, b as base. 0 if both 0."""
    if b == 0:
        return 0.0 if a == 0 else float("inf")
    return abs(a - b) / abs(b) * 100.0


def main() -> int:
    dates = trading_dates_2025()
    if len(dates) < ADV_WINDOW + 5:
        print(f"NOT ENOUGH coarse dates: {len(dates)}")
        return 2

    # Pick a sample of liquid tickers from a mid-year coarse file (top by DV) + a few hand-picks
    # known to have had 2025 corporate actions, to stress the split-adjustment question.
    midday = dates[len(dates) // 2]
    coarse_mid = load_coarse_day(midday)
    by_dv = sorted(coarse_mid.items(), key=lambda kv: -kv[1][1])
    sample = [t for t, _ in by_dv[:20]]
    # add a few near the floor + a few mid-cap to test the boundary, if present
    for t, (_, dv) in by_dv:
        if 8e7 <= dv <= 1.5e8 and t not in sample:
            sample.append(t)
        if len(sample) >= 30:
            break

    print(f"GATE 1 — coarse-DV vs RAW-DV / coarse-close vs RAW-close")
    print(f"coarse dates in 2025: {len(dates)} ({dates[0]}..{dates[-1]})")
    print(f"sample tickers: {len(sample)} -> {sample}")
    print(f"floors: price>=${MIN_PRICE}, trailing-{ADV_WINDOW}d mean DV >= {MIN_AVG_DV:,.0f}")
    print("=" * 100)

    # Sample several test dates spread across the year, each needing 20 prior trading days.
    test_idx = [
        ADV_WINDOW + 5,
        len(dates) // 4,
        len(dates) // 2,
        (3 * len(dates)) // 4,
        len(dates) - 1,
    ]
    test_dates = sorted({dates[i] for i in test_idx if i >= ADV_WINDOW})

    raw_cache: dict[str, dict[str, tuple[float, float]]] = {}
    for t in sample:
        raw_cache[t] = load_raw_daily(t)

    # Preload coarse for all dates we need (test dates + their 20-day windows)
    needed_idx: set[int] = set()
    for td in test_dates:
        i = dates.index(td)
        needed_idx.update(range(i - ADV_WINDOW + 1, i + 1))
    coarse_cache: dict[str, dict[str, tuple[float, float]]] = {}
    for i in sorted(needed_idx):
        d = dates[i]
        coarse_cache[d] = load_coarse_day(d)

    max_close_div = 0.0
    max_sdv_div = 0.0
    max_trailing_div = 0.0
    floor_flips: list[str] = []
    n_compared = 0

    for td in test_dates:
        i = dates.index(td)
        window_dates = dates[i - ADV_WINDOW + 1: i + 1]
        print(f"\n--- test date {td} (window {window_dates[0]}..{window_dates[-1]}) ---")
        print(f"{'ticker':<8} {'c_close':>10} {'r_close':>10} {'cl%':>6} "
              f"{'c_trailDV':>16} {'r_trailDV':>16} {'tdv%':>6} "
              f"{'c_pass':>6} {'r_pass':>6} {'flip':>5}")
        for t in sample:
            raw = raw_cache.get(t, {})
            # coarse trailing: mean of coarse single-day DV over the window (the NEW path)
            c_dvs: list[float] = []
            c_close_today = None
            for wd in window_dates:
                cd = coarse_cache.get(wd, {})
                if t in cd:
                    c_close_today = cd[t][0]  # last assignment = today's close
                    c_dvs.append(cd[t][1])
            # raw trailing: mean of raw close*volume over the window (the OLD path)
            r_dvs: list[float] = []
            r_close_today = None
            for wd in window_dates:
                key = wd  # YYYYMMDD
                if key in raw:
                    rc, rv = raw[key]
                    r_close_today = rc
                    r_dvs.append(rc * rv)
            if not c_dvs or not r_dvs or c_close_today is None or r_close_today is None:
                continue
            n_compared += 1
            c_trail = sum(c_dvs) / len(c_dvs)
            r_trail = sum(r_dvs) / len(r_dvs)
            cl_div = pct(c_close_today, r_close_today)
            tdv_div = pct(c_trail, r_trail)
            sdv_today_div = pct(coarse_cache[td][t][1], raw[td][0] * raw[td][1]) if td in raw and t in coarse_cache[td] else 0.0
            max_close_div = max(max_close_div, cl_div)
            max_trailing_div = max(max_trailing_div, tdv_div)
            max_sdv_div = max(max_sdv_div, sdv_today_div)

            c_pass = c_close_today >= MIN_PRICE and c_trail >= MIN_AVG_DV
            r_pass = r_close_today >= MIN_PRICE and r_trail >= MIN_AVG_DV
            flip = "FLIP" if c_pass != r_pass else ""
            if flip:
                floor_flips.append(f"{t}@{td}: coarse_pass={c_pass} raw_pass={r_pass} "
                                   f"(c_close={c_close_today:.2f} r_close={r_close_today:.2f} "
                                   f"c_trail={c_trail:,.0f} r_trail={r_trail:,.0f})")
            print(f"{t:<8} {c_close_today:>10.2f} {r_close_today:>10.2f} {cl_div:>6.2f} "
                  f"{c_trail:>16,.0f} {r_trail:>16,.0f} {tdv_div:>6.2f} "
                  f"{str(c_pass):>6} {str(r_pass):>6} {flip:>5}")

    print("\n" + "=" * 100)
    print(f"COMPARISONS: {n_compared}")
    print(f"MAX coarse-close vs raw-close divergence:        {max_close_div:.3f} %")
    print(f"MAX coarse single-day DV vs raw DV divergence:   {max_sdv_div:.3f} %")
    print(f"MAX coarse trailing-20d vs raw trailing-20d:     {max_trailing_div:.3f} %")
    print(f"FLOOR FLIPS (decision changed): {len(floor_flips)}")
    for f in floor_flips:
        print(f"  {f}")
    print("=" * 100)
    local_ok = not floor_flips and max_trailing_div <= 5.0 and max_close_div <= 5.0
    verdict = "LOCAL-OK" if local_ok else "REVIEW"
    print(f"VERDICT: {verdict}")
    print(
        "  NOTE: this is a LOCAL check only. 0.000% / 0-flips is TAUTOLOGICAL — the #238 "
        "conform built local coarse DV as raw_close*raw_volume from the SAME source, so it is\n"
        "  bit-identical by construction. It confirms the field-mapping + rolling-mean wiring "
        "are correct; it is NOT cloud proof.\n"
        "  The cloud (vendor-adjusted) case rests on DV being split-invariant (sound for a "
        "liquidity floor; does NOT cover dividend-adjust / adjusted-derived DV) and is\n"
        "  EMPIRICALLY validated at the post-#240 cloud Step-A active-set parity, not here."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
