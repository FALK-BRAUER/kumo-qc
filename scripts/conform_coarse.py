#!/usr/bin/env python3
"""conform_coarse.py — regenerate local LEAN coarse-fundamental CSVs in QC-STANDARD format.

WHY (#238): the mainV2 engine selects its universe LIVE from QC's coarse feed in
`src/runtime/lean_entry.py::_coarse_selection`. On CLOUD QC supplies the native coarse
feed; LOCALLY LEAN reads `data/equity/usa/fundamental/coarse/YYYYMMDD.csv` via its native
CoarseFundamental reader. The repo's prior local coarse files were a CUSTOM 5-col header'd
format LEAN's native reader CANNOT parse. This script emits the QC-STANDARD 8-col headerless
format so the SAME code path (`_coarse_selection`) runs identically local + cloud
(charter: local simulates cloud, single code path).

QC-STANDARD coarse row (8 cols, headerless) — verified against LEAN-shipped sample files
(data/.../coarse/20140324.csv) AND LEAN source CoarseFundamental.ToRow comment
("sid,symbol,close,volume,dollar volume,has fundamental data,price factor,split factor"):

    SID,ticker,close,volume,dollar_volume,has_fundamental_data,price_factor,split_factor

LEAN's coarse reader builds the Symbol as:  new Symbol(SecurityIdentifier.Parse(csv[0]), csv[1])
and for a plain equity Symbol.Value == csv[1].ToUpper() (GetAlias returns null; verified in
Common/Symbol.cs). So `_coarse_selection`'s `c.symbol.value` is column 1 (the ticker), NOT
derived from the SID. The SID must merely PARSE and resolve the equity's price data; its
encoded first-date need not match QC's canonical date for an FY2025 window (Path A, blessed).

SID encoding (Path A — hand-rolled GenerateEquity, no network). Constants from
Common/SecurityIdentifier.cs, empirically validated by decoding real LEAN-shipped SIDs
(AAPL R735QTJ8XC9X -> securityType=1/Equity, market=1/USA, OADate=35797=1998-01-02):
  properties = securityType*SecurityTypeOffset
             + market*MarketOffset
             + OADate(firstDate)*DaysOffset
  SID string = f"{TICKER.upper()} {base36(properties)}"
firstDate = the FIRST date in the ticker's local map_file (LEAN: "the first date mentioned
in the map_files"). Local map_files are stub-dated (mostly 20210512); for an FY2025 window
that is harmless (2021 < 2025, data resolves). FLAGGED in the handoff/report.

DATA SOURCING (charter: source from the SAME data the BT reads):
  close, volume  <- the ticker's daily zip bar for that date (LEAN daily equity prices are
                    scaled x10000 deci-cents; we DIVIDE by 10000 to get the real price the
                    coarse `close` column expects — the 2014 sample shows real prices, e.g.
                    AAPL 539.1).
  dollar_volume  = close * volume   (real price * shares)
  price_factor / split_factor <- from factor_files/<tkr>.csv as-of the date if present,
                    else 1.0. RAW prices everywhere (engine uses RAW; adjusted corrupts
                    Ichimoku).
  has_fundamental_data = True (we only emit rows for tickers that have a daily zip; the
                    field is informational for the coarse reader, not a selection gate the
                    engine reads).

BREADTH (charter-critical — NOT a curated universe): rows are emitted for the BROADEST
locally-available pool = every ticker with BOTH a daily/<tkr>.zip AND a map_files/<tkr>.csv
that has a bar on the given date. `_coarse_selection` applies its live prefilter/floors/rank
over this pool each day. If local data availability narrows this pool, that is a flagged
local-approximation limit (cloud=truth validates true breadth) — we do NOT pre-curate.

Idempotent + deterministic: re-running overwrites cleanly; rows are sorted by ticker.

WARMUP WINDOW (#259 — the empty-warmup parity fix):
  The mainV2 engine calls `set_warmup(timedelta(days=560))` (WARMUP_DAYS=560 CALENDAR days)
  before the FY2025 start (2025-01-01). 560 cal days before 2025-01-01 = 2023-06-21, so the
  warmup span is 2023-06-20 → 2024-12-31 (06-20 floor = a 1-day safety margin). BEFORE #259
  this window held the OLD ~201-row 5-col-HEADER synthetic coarse format LEAN's native reader
  CANNOT parse → the local warmup universe was EMPTY for 18 months → zero subscriptions → the
  maintained daily indicators never warmed → score_symbol_native returned None → local barely
  traded until ~Oct-2025 (the −0.616/+3.9% empty-warmup ARTIFACT vs cloud −11.8%, #173). The
  `--warmup` flag conforms this span to the SAME 8-col headerless QC-native format as FY2025
  (identical logic — daily-zip close/volume/DV, hand-rolled Path-A SID, RAW), OVERWRITING the
  old synthetic files in place and DELETING orphan old-format files on non-session dates
  (holidays) in the span so the native reader never trips on a stale 5-col header.

Usage:
  # smoke (one ticker, one day):
  python3 scripts/conform_coarse.py --smoke --ticker NVDA --date 20250103
  # full FY2025 (session calendar derived from the daily data, not hardcoded):
  python3 scripts/conform_coarse.py --start 20250102 --end 20251231
  # WARMUP window (the #259 fix) — derives 2023-06-20 → 2024-12-31 + cleans orphans:
  python3 scripts/conform_coarse.py --warmup
"""
from __future__ import annotations

import argparse
import datetime as _dt
import math
import sys
import zipfile
from functools import lru_cache
from pathlib import Path


def _warn(msg: str) -> None:
    """Loud, visible drop/skip log (#261-3/4). conform_coarse is an OFFLINE data-prep tool, so a
    malformed ROW is loud-SKIPPED-WITH-A-LOGGED-REASON (to stderr, so it survives stdout being a
    count) rather than aborting the whole multi-thousand-ticker conform — but the drop is NEVER
    silent. The anti-mirage rule (Falk): a degraded drop must be VISIBLE + diagnosable
    (ticker/row/why), never a silent whole-ticker disappearance (the prior blanket except → None)."""
    print(f"[conform_coarse WARN] {msg}", file=sys.stderr)

# ── LEAN SecurityIdentifier constants (Common/SecurityIdentifier.cs) ──────────
# Field layout in the base-36 `properties` integer (offsets are products of widths).
_SECURITY_TYPE_OFFSET = 1
_SECURITY_TYPE_WIDTH = 100
_MARKET_OFFSET = _SECURITY_TYPE_OFFSET * _SECURITY_TYPE_WIDTH            # 100
_MARKET_WIDTH = 1000
_STRIKE_SCALE_OFFSET = _MARKET_OFFSET * _MARKET_WIDTH                    # 100_000
_STRIKE_SCALE_WIDTH = 100
_STRIKE_OFFSET = _STRIKE_SCALE_OFFSET * _STRIKE_SCALE_WIDTH              # 10_000_000
_STRIKE_WIDTH = 1_000_000
_OPTION_STYLE_OFFSET = _STRIKE_OFFSET * _STRIKE_WIDTH                    # 10_000_000_000_000
_OPTION_STYLE_WIDTH = 10
_DAYS_OFFSET = _OPTION_STYLE_OFFSET * _OPTION_STYLE_WIDTH                # 100_000_000_000_000_000

_SECURITY_TYPE_EQUITY = 1   # SecurityType.Equity
_MARKET_USA = 1             # QuantConnect.Market.USA numeric code

_B36 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_OA_EPOCH = _dt.date(1899, 12, 30)  # OLE Automation date epoch

# Local daily-equity price scale (LEAN stores deci-cents: real_price = raw / 10000).
_PRICE_SCALE = 10000.0

# WARMUP window (#259). The engine warms 560 CALENDAR days before the FY2025 start
# (2025-01-01); 560 cal days back = 2023-06-21. We floor the span lower bound to 2023-06-20
# (1-day margin) and end at 2024-12-31 (the day before the live window).
_WARMUP_START = "20230620"
_WARMUP_END = "20241231"

_DATA = Path("data/equity/usa")
_DAILY = _DATA / "daily"
_MAPS = _DATA / "map_files"
_FACTORS = _DATA / "factor_files"
_COARSE_OUT = _DATA / "fundamental" / "coarse"


def _encode_base36(value: int) -> str:
    if value < 0:
        raise ValueError("base36 value must be non-negative")
    if value == 0:
        return "0"
    out: list[str] = []
    while value:
        value, rem = divmod(value, 36)
        out.append(_B36[rem])
    return "".join(reversed(out))


def _to_oadate(d: _dt.date) -> int:
    return (d - _OA_EPOCH).days


def generate_equity_sid(ticker: str, first_date: _dt.date) -> str:
    """Replicate SecurityIdentifier.GenerateEquity(ticker, Market.USA, firstDate).

    Returns the SID string `"<TICKER> <base36-properties>"`. The properties integer packs
    securityType=Equity, market=USA, and the first-trading-date (OADate) at DaysOffset.
    """
    props = (
        _SECURITY_TYPE_EQUITY * _SECURITY_TYPE_OFFSET
        + _MARKET_USA * _MARKET_OFFSET
        + _to_oadate(first_date) * _DAYS_OFFSET
    )
    return f"{ticker.upper()} {_encode_base36(props)}"


def map_first_date(ticker: str) -> _dt.date | None:
    """First date in the ticker's local map_file (the SID first-date per LEAN)."""
    fp = _MAPS / f"{ticker.lower()}.csv"
    if not fp.is_file():
        return None
    with fp.open() as fh:
        line = fh.readline().strip()
    if not line:
        return None
    ymd = line.split(",")[0]
    return _dt.datetime.strptime(ymd, "%Y%m%d").date()


@lru_cache(maxsize=None)
def _factor_rows(ticker: str) -> tuple[tuple[_dt.date, float, float], ...]:
    """Parsed+sorted factor rows for a ticker, MEMOISED (each file read+parsed once).

    A full-span conform calls factor_for for every (ticker × session) pair — re-parsing the
    same file thousands of times without a cache. lru_cache keyed on the ticker reads+parses
    each factor file exactly once (empty tuple = no file / unparseable). Returned as a tuple
    so it stays hashable + immutable in the cache.
    """
    fp = _FACTORS / f"{ticker.lower()}.csv"
    if not fp.is_file():
        return ()
    rows: list[tuple[_dt.date, float, float]] = []
    with fp.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            parts = line.split(",")
            if len(parts) < 3:
                continue
            try:
                d = _dt.datetime.strptime(parts[0], "%Y%m%d").date()
                rows.append((d, float(parts[1]), float(parts[2])))
            except ValueError:
                continue
    rows.sort()
    return tuple(rows)


def factor_for(ticker: str, on: _dt.date) -> tuple[float, float]:
    """(price_factor, split_factor) from factor_files as-of `on`, else (1.0, 1.0).

    Factor file rows: YYYYMMDD,price_factor,split_factor (effective on/before that date).
    We take the latest row with date >= `on` (LEAN factor lookup is forward-looking from
    the bar date); fall back to the last row, else (1,1). RAW prices mean these are emitted
    for format-completeness, not applied to close. File parse is memoised in _factor_rows.
    """
    rows = _factor_rows(ticker)
    if not rows:
        return 1.0, 1.0
    for d, pf, sf in rows:
        if d >= on:
            return pf, sf
    return rows[-1][1], rows[-1][2]


def _read_daily_zip(ticker: str) -> dict[str, tuple[float, int]] | None:
    """{YYYYMMDD: (real_close, volume)} for a ticker's daily zip, or None if absent/unreadable.

    FAIL-LOUD (#261-3): the prior implementation wrapped the WHOLE parse loop in
    `except (BadZipFile, IndexError, ValueError): return None`, so a SINGLE malformed row (a
    non-numeric close, a truncated/half row, a stray header line) silently dropped the ENTIRE
    ticker — including every VALID bar after the bad row — with no logged reason. That is the
    silent-drop class the anti-mirage mandate forbids. Now:
      - a BadZipFile (the whole file is corrupt, not one row) → loud-WARN + return None (no rows
        to salvage; the named ticker drop is at least VISIBLE);
      - a malformed individual ROW → loud-WARN with the ticker + the offending row + why, and
        SKIP ONLY THAT ROW, keeping every valid bar. No whole-ticker silent disappearance.
    Offline-tool judgment (per the ticket): a row-level loud-SKIP-WITH-LOG is acceptable here
    (vs a hard raise in the live engine path) because conform is data-prep — but the skip is
    LOGGED, never silent."""
    fp = _DAILY / f"{ticker.lower()}.zip"
    if not fp.is_file():
        return None
    out: dict[str, tuple[float, int]] = {}
    try:
        zf = zipfile.ZipFile(fp)
    except zipfile.BadZipFile:
        _warn(f"ticker={ticker!r}: corrupt/unreadable daily zip (BadZipFile) — DROPPED (#261-3)")
        return None
    with zf:
        name = zf.namelist()[0]
        with zf.open(name) as fh:
            for raw in fh:
                line = raw.decode("ascii", "ignore").strip()
                if not line:
                    continue
                parts = line.split(",")
                # "YYYYMMDD HH:MM,open,high,low,close,volume" (6 cols)
                if len(parts) < 6:
                    _warn(
                        f"ticker={ticker!r}: malformed daily row (need 6 cols, got "
                        f"{len(parts)}): {line!r} — ROW SKIPPED, ticker kept (#261-3)"
                    )
                    continue
                try:
                    ymd = parts[0].split(" ")[0]
                    close = float(parts[4]) / _PRICE_SCALE
                    volume = int(float(parts[5]))
                except ValueError as exc:
                    _warn(
                        f"ticker={ticker!r}: non-numeric daily row ({exc}): {line!r} — "
                        f"ROW SKIPPED, ticker kept (#261-3)"
                    )
                    continue
                out[ymd] = (close, volume)
    return out


def _local_pool() -> list[str]:
    """BROADEST local pool: tickers with BOTH a daily zip AND a map_file (lowercased stems)."""
    if not _DAILY.is_dir():
        sys.exit(f"daily dir not found: {_DAILY.resolve()}")
    daily = {p.stem.lower() for p in _DAILY.glob("*.zip")}
    maps = {p.name[: -len(".csv")].lower() for p in _MAPS.glob("*.csv")}
    return sorted(daily & maps)


def _fmt_num(x: float) -> str:
    """Compact numeric format: integers without trailing .0, floats trimmed."""
    if x == int(x):
        return str(int(x))
    return repr(round(x, 6))


def build_row(ticker: str, ymd: str, daily: dict[str, tuple[float, int]]) -> str | None:
    """One QC-standard 8-col coarse row for ticker on ymd, or None if no bar / degraded bar.

    FAIL-LOUD (#261-4): the prior implementation emitted a row from whatever close it was handed
    with NO finite/sign validation — a NEGATIVE or non-finite close (a corrupt daily bar) was
    WRITTEN into the universe file as a malformed coarse row (negative close → negative
    dollar_volume). The downstream live floor rejects it, but conform must not SHIP a degraded
    row in the first place. Now a non-finite or negative close is loud-SKIPPED-WITH-A-LOGGED-
    REASON (offline-tool judgment: skip-with-log, not a hard raise, so one bad ticker/day does
    not abort the whole conform — but the skip is VISIBLE, never a silent emit). A zero close is
    also skipped (a $0 print is a degraded/halted bar, never a tradeable coarse row)."""
    bar = daily.get(ymd)
    if bar is None:
        return None
    close, volume = bar
    if not math.isfinite(close) or close <= 0.0:
        _warn(
            f"ticker={ticker!r} day={ymd}: non-finite/non-positive close ({close!r}) — coarse "
            f"row SKIPPED (degraded bar must not be written to the universe file) (#261-4)"
        )
        return None
    fd = map_first_date(ticker)
    if fd is None:
        return None
    sid = generate_equity_sid(ticker, fd)
    dollar_volume = close * volume
    on = _dt.datetime.strptime(ymd, "%Y%m%d").date()
    pf, sf = factor_for(ticker, on)
    return (
        f"{sid},{ticker.upper()},{_fmt_num(close)},{volume},"
        f"{_fmt_num(dollar_volume)},True,{_fmt_num(pf)},{_fmt_num(sf)}"
    )


def session_dates(start: str, end: str) -> list[str]:
    """Trading sessions in [start, end] DERIVED from the daily data calendar (SPY's bars).

    SPY trades every NYSE session; using its daily zip as the calendar avoids hardcoding the
    holiday schedule. Falls back to the union of a few large names if SPY is absent.
    """
    cal_source = None
    for probe in ("spy", "aapl", "msft"):
        d = _read_daily_zip(probe)
        if d:
            cal_source = d
            break
    if cal_source is None:
        sys.exit("no calendar source (spy/aapl/msft daily zip) found")
    days = sorted(ymd for ymd in cal_source if start <= ymd <= end)
    return days


def write_day(ymd: str, pool: list[str], daily_cache: dict[str, dict[str, tuple[float, int]] | None]) -> int:
    """Write one YYYYMMDD.csv for all pool tickers with a bar that day. Returns row count."""
    rows: list[str] = []
    for tk in pool:
        d = daily_cache.get(tk, ...)
        if d is ...:
            d = _read_daily_zip(tk)
            daily_cache[tk] = d
        if not d:
            continue
        row = build_row(tk, ymd, d)
        if row:
            rows.append(row)
    rows.sort()  # deterministic ticker order (SID begins with TICKER, so this is ticker-sorted)
    _COARSE_OUT.mkdir(parents=True, exist_ok=True)
    out = _COARSE_OUT / f"{ymd}.csv"
    out.write_text("\n".join(rows) + ("\n" if rows else ""))
    return len(rows)


def clean_orphan_files(start: str, end: str, sessions: list[str]) -> list[str]:
    """Delete coarse CSVs in [start,end] that are NOT trading sessions (stale holiday files).

    The session calendar (derived from SPY) excludes market holidays, so a conform run never
    writes/overwrites a coarse file on e.g. 2023-07-04. The pre-#259 synthetic feed DID emit
    those days as 5-col-header files; left behind they are stale orphans the native reader
    could still trip on. Removing them keeps the span uniformly 8-col QC-native. Returns the
    list of removed YYYYMMDD stems.
    """
    session_set = set(sessions)
    removed: list[str] = []
    if not _COARSE_OUT.is_dir():
        return removed
    for fp in _COARSE_OUT.glob("*.csv"):
        ymd = fp.stem
        if start <= ymd <= end and ymd not in session_set:
            fp.unlink()
            removed.append(ymd)
    return sorted(removed)


def _run_span(start: str, end: str, clean: bool) -> None:
    """Conform every session in [start, end]; optionally purge non-session orphans first."""
    pool = _local_pool()
    sessions = session_dates(start, end)
    if not sessions:
        sys.exit(f"no sessions in [{start}..{end}] — check daily calendar source")
    print(f"local pool = {len(pool)} tickers (daily ∩ map_file); sessions = {len(sessions)} "
          f"[{sessions[0]}..{sessions[-1]}]")
    if clean:
        removed = clean_orphan_files(start, end, sessions)
        print(f"removed {len(removed)} orphan non-session coarse files: {removed}")
    daily_cache: dict[str, dict[str, tuple[float, int]] | None] = {}
    total = 0
    for ymd in sessions:
        n = write_day(ymd, pool, daily_cache)
        total += n
    print(f"wrote {len(sessions)} files, {total} rows total, avg {total // max(1, len(sessions))} rows/day")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--smoke", action="store_true", help="emit a single ticker/day row (gate)")
    p.add_argument("--ticker", help="smoke: ticker symbol")
    p.add_argument("--date", help="smoke or single-day: YYYYMMDD")
    p.add_argument("--start", help="full: first session YYYYMMDD")
    p.add_argument("--end", help="full: last session YYYYMMDD")
    p.add_argument(
        "--warmup", action="store_true",
        help=f"conform the #259 WARMUP span ({_WARMUP_START}..{_WARMUP_END}) + clean orphans",
    )
    args = p.parse_args()

    if args.smoke:
        if not (args.ticker and args.date):
            sys.exit("--smoke requires --ticker and --date")
        daily = _read_daily_zip(args.ticker)
        if not daily:
            sys.exit(f"no daily zip for {args.ticker}")
        row = build_row(args.ticker, args.date, daily)
        if row is None:
            sys.exit(f"no daily bar for {args.ticker} on {args.date}")
        _COARSE_OUT.mkdir(parents=True, exist_ok=True)
        out = _COARSE_OUT / f"{args.date}.csv"
        out.write_text(row + "\n")
        print(f"SMOKE wrote {out} :\n  {row}")
        return

    if args.warmup:
        # The #259 warmup conform: clean the stale 5-col orphans + write the 8-col span.
        _run_span(_WARMUP_START, _WARMUP_END, clean=True)
        return

    if not (args.start and args.end):
        sys.exit("full run requires --start and --end (YYYYMMDD), or use --warmup")
    _run_span(args.start, args.end, clean=False)


if __name__ == "__main__":
    main()
