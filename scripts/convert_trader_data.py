#!/usr/bin/env python3
"""Convert kumo-trader SQLite OHLCV data into LEAN daily equity files.

Output structure:
- data/equity/usa/daily/<ticker_lower>.zip (contains <ticker_lower>.csv)
- data/equity/usa/map_files/<ticker_lower>.csv
- data/equity/usa/factor_files/<ticker_lower>.csv
"""

from __future__ import annotations

import argparse
import sqlite3
import zipfile
from pathlib import Path


def _lean_name(ticker: str) -> str:
    return ticker.lower().replace("-", ".")


def _price_to_int(value: float) -> int:
    return int(round(float(value) * 10000))


def _quality_tickers(
    conn: sqlite3.Connection,
    ref_start: str,
    ref_end: str,
    min_close: float,
    min_dollar_volume: float,
) -> list[str]:
    query = """
        SELECT
            ticker,
            AVG(close) AS avg_close,
            AVG(close * volume) AS avg_dollar_volume
        FROM ohlcv
        WHERE date BETWEEN ? AND ?
        GROUP BY ticker
        HAVING avg_close >= ?
           AND avg_dollar_volume >= ?
        ORDER BY ticker
    """
    rows = conn.execute(query, (ref_start, ref_end, min_close, min_dollar_volume)).fetchall()
    return [row[0] for row in rows]


def _write_ticker_files(base: Path, ticker: str, rows: list[tuple]) -> None:
    daily_dir = base / "daily"
    map_dir = base / "map_files"
    factor_dir = base / "factor_files"
    daily_dir.mkdir(parents=True, exist_ok=True)
    map_dir.mkdir(parents=True, exist_ok=True)
    factor_dir.mkdir(parents=True, exist_ok=True)

    lean = _lean_name(ticker)
    csv_name = f"{lean}.csv"

    csv_lines: list[str] = []
    for _, date_text, o, h, l, c, v in rows:
        ymd = date_text.replace("-", "")
        csv_lines.append(
            f"{ymd} 00:00,{_price_to_int(o)},{_price_to_int(h)},{_price_to_int(l)},{_price_to_int(c)},{int(v)}"
        )
    csv_blob = "\n".join(csv_lines) + "\n"

    zip_path = daily_dir / f"{lean}.zip"
    with zipfile.ZipFile(zip_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(csv_name, csv_blob)

    first_date = rows[0][1].replace("-", "") if rows else "20220103"
    (map_dir / f"{lean}.csv").write_text(
        f"{first_date},{lean},Q\n20501231,{lean},Q\n", encoding="utf-8"
    )
    (factor_dir / f"{lean}.csv").write_text("19700101,1,1\n", encoding="utf-8")


def _export_range(
    conn: sqlite3.Connection,
    tickers: list[str],
    start_date: str,
    end_date: str,
    output_base: Path,
) -> int:
    if not tickers:
        return 0

    conn.execute("DROP TABLE IF EXISTS selected_tickers")
    conn.execute("CREATE TEMP TABLE selected_tickers(ticker TEXT PRIMARY KEY)")
    conn.executemany("INSERT INTO selected_tickers(ticker) VALUES (?)", ((t,) for t in tickers))

    query = """
        SELECT o.ticker, o.date, o.open, o.high, o.low, o.close, o.volume
        FROM ohlcv o
        INNER JOIN selected_tickers s ON s.ticker = o.ticker
        WHERE o.date BETWEEN ? AND ?
        ORDER BY o.ticker, o.date
    """

    current_ticker: str | None = None
    bucket: list[tuple] = []
    written = 0
    processed = 0

    def _flush(t: str, b: list[tuple]) -> int:
        if not b:
            print(f"  WARNING: {t} — no rows in export range, skipping")
            return 0
        _write_ticker_files(output_base, t, b)
        return 1

    for row in conn.execute(query, (start_date, end_date)):
        ticker = row[0]
        if current_ticker is None:
            current_ticker = ticker
        if ticker != current_ticker:
            written += _flush(current_ticker, bucket)
            processed += 1
            if processed % 100 == 0:
                print(f"  progress: {processed}/{len(tickers)} tickers processed, {written} written")
            current_ticker = ticker
            bucket = [row]
        else:
            bucket.append(row)

    if current_ticker is not None:
        written += _flush(current_ticker, bucket)
        processed += 1

    # tickers with zero rows in DB for the export range never appeared in query results;
    # detect them by comparing written against tickers list length
    tickers_with_data = set()
    for t in tickers:
        zip_path = output_base / "daily" / f"{_lean_name(t)}.zip"
        if zip_path.exists():
            tickers_with_data.add(t)
    for t in tickers:
        if t not in tickers_with_data:
            print(f"  WARNING: {t} — zero rows found in DB for {start_date}..{end_date}, skipping")

    return written


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert SQLite OHLCV into LEAN daily equity data")
    parser.add_argument(
        "--db-path",
        default="/Users/falk/projects/kumo-trader/data/kumo-market.db",
        help="Path to kumo-market SQLite DB",
    )
    parser.add_argument(
        "--output-base",
        default="/Users/falk/projects/kumo-qc/data/equity/usa",
        help="LEAN usa data directory base",
    )
    parser.add_argument("--start-date", default="2022-01-01", help="Export start date YYYY-MM-DD")
    parser.add_argument("--end-date", default="2025-12-31", help="Export end date YYYY-MM-DD")
    parser.add_argument("--ref-start", default="2025-01-01", help="Filter reference start YYYY-MM-DD")
    parser.add_argument("--ref-end", default="2025-12-31", help="Filter reference end YYYY-MM-DD")
    parser.add_argument("--min-close", type=float, default=3.0, help="Minimum recent close")
    parser.add_argument(
        "--min-dollar-volume",
        type=float,
        default=500000.0,
        help="Minimum average daily dollar volume",
    )
    parser.add_argument(
        "--tickers",
        default="",
        help="Optional comma-separated explicit tickers (overrides quality filter)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    db_path = Path(args.db_path)
    out = Path(args.output_base)
    if not db_path.exists():
        raise FileNotFoundError(f"DB not found: {db_path}")

    with sqlite3.connect(db_path) as conn:
        if args.tickers.strip():
            tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
            print(f"mode=explicit_tickers count={len(tickers)}")
        else:
            tickers = _quality_tickers(
                conn,
                ref_start=args.ref_start,
                ref_end=args.ref_end,
                min_close=args.min_close,
                min_dollar_volume=args.min_dollar_volume,
            )
            print(
                "mode=quality_filter"
                f" ref={args.ref_start}..{args.ref_end}"
                f" min_close={args.min_close}"
                f" min_adv_dollar={args.min_dollar_volume}"
                f" count={len(tickers)}"
            )

        written = _export_range(
            conn,
            tickers=tickers,
            start_date=args.start_date,
            end_date=args.end_date,
            output_base=out,
        )

    print(
        "export_complete"
        f" tickers_selected={len(tickers)}"
        f" tickers_written={written}"
        f" range={args.start_date}..{args.end_date}"
        f" out={out}"
    )


if __name__ == "__main__":
    main()
