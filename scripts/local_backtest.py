#!/usr/bin/env python3
"""
local_backtest.py — BCT signal scoring against kumo-market.db (no QC dependency).

Uses Yahoo Finance OHLCV from kumo-trader's SQLite DB. Compares output against
scanner_results table to compute recall/precision per condition.

Usage:
  python3 scripts/local_backtest.py --start 2026-04-07 --end 2026-04-11
  python3 scripts/local_backtest.py --start 2026-04-07 --end 2026-05-16
  python3 scripts/local_backtest.py --start 2026-04-07 --end 2026-04-11 --tickers AAPL NVDA
"""

import argparse
import sqlite3
import sys
from pathlib import Path
from collections import defaultdict

import numpy as np
import pandas as pd

DB_PATH = Path(__file__).parent.parent.parent / "kumo-trader" / "data" / "kumo-market.db"
DAILY_BARS = 700
MIN_SCORE = 6  # ++ or better


# ── Signal math (copied from bct_signal.py, no QC imports) ───────────────────

def _mid(high: pd.Series, low: pd.Series, period: int) -> pd.Series:
    return (high.rolling(period).max() + low.rolling(period).min()) / 2


def _adx_wilder(df: pd.DataFrame, period: int = 9):
    h, lo, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([(h - lo), (h - pc).abs(), (lo - pc).abs()], axis=1).max(axis=1)
    up = h - h.shift(1)
    dn = lo.shift(1) - lo
    plus_dm = pd.Series(np.where((up > dn) & (up > 0), up.values, 0.0), index=df.index, dtype=float)
    minus_dm = pd.Series(np.where((dn > up) & (dn > 0), dn.values, 0.0), index=df.index, dtype=float)
    a = 1.0 / period
    atr = tr.ewm(alpha=a, adjust=False).mean()
    plus_di = 100.0 * plus_dm.ewm(alpha=a, adjust=False).mean() / atr
    minus_di = 100.0 * minus_dm.ewm(alpha=a, adjust=False).mean() / atr
    denom = (plus_di + minus_di).replace(0.0, np.nan)
    dx = 100.0 * (plus_di - minus_di).abs() / denom
    adx = dx.ewm(alpha=a, adjust=False).mean()
    return adx, plus_di, minus_di


def _resample_weekly(df: pd.DataFrame) -> pd.DataFrame:
    weekly = df.resample("W-FRI").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    )
    return weekly.dropna(subset=["close"])


def score_df(daily: pd.DataFrame) -> dict | None:
    if len(daily) < 230:
        return None

    weekly = _resample_weekly(daily)
    if len(weekly) < 78:
        return None

    # Weekly Ichimoku
    w_tenkan = _mid(weekly["high"], weekly["low"], 9)
    w_kijun  = _mid(weekly["high"], weekly["low"], 26)
    w_cloud_a = ((w_tenkan + w_kijun) / 2).shift(26)
    w_cloud_b = _mid(weekly["high"], weekly["low"], 52).shift(26)

    w_price       = weekly["close"].iloc[-1]
    w_cloud_a_now = w_cloud_a.iloc[-1]
    w_cloud_b_now = w_cloud_b.iloc[-1]
    w_tenkan_now  = w_tenkan.iloc[-1]
    w_kijun_now   = w_kijun.iloc[-1]
    w_price_26_ago = weekly["close"].iloc[-27] if len(weekly) >= 27 else float("nan")

    # Daily Ichimoku
    d_tenkan  = _mid(daily["high"], daily["low"], 9)
    d_kijun   = _mid(daily["high"], daily["low"], 26)
    d_cloud_a = ((d_tenkan + d_kijun) / 2).shift(26)
    d_cloud_b = _mid(daily["high"], daily["low"], 52).shift(26)

    d_price       = daily["close"].iloc[-1]
    d_tenkan_now  = d_tenkan.iloc[-1]
    d_cloud_a_now = d_cloud_a.iloc[-1]
    d_cloud_b_now = d_cloud_b.iloc[-1]
    ma200         = daily["close"].rolling(200).mean().iloc[-1]

    # ADX / DMI
    adx, plus_di, minus_di = _adx_wilder(daily, period=9)
    adx_now      = adx.iloc[-1]
    plus_di_now  = plus_di.iloc[-1]
    minus_di_now = minus_di.iloc[-1]
    adx_rising   = bool(adx.iloc[-1] > adx.iloc[-4])

    critical = [w_cloud_a_now, w_cloud_b_now, w_tenkan_now, w_kijun_now, w_price_26_ago,
                d_cloud_a_now, d_cloud_b_now, d_tenkan_now, ma200, adx_now, plus_di_now, minus_di_now]
    if any(pd.isna(v) for v in critical):
        return None

    conditions = [
        bool(w_price > max(w_cloud_a_now, w_cloud_b_now)),
        bool(w_tenkan_now > w_kijun_now),
        bool(w_price > w_price_26_ago),
        bool(w_cloud_a_now > w_cloud_b_now),
        bool(d_price > max(d_cloud_a_now, d_cloud_b_now)),
        bool(d_price > d_tenkan_now),
        bool(adx_rising and plus_di_now > minus_di_now and adx_now >= 20),
        bool(d_price > ma200),
    ]
    score = sum(conditions)
    if score == 8:   rating = "+++"
    elif score >= 6: rating = "++"
    elif score >= 4: rating = "+"
    elif score >= 2: rating = "="
    else:            rating = "--"

    return {"score": score, "rating": rating, "conditions": conditions}


# ── DB helpers ────────────────────────────────────────────────────────────────

def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def trading_dates(conn, start: str, end: str) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT date FROM ohlcv WHERE date >= ? AND date <= ? ORDER BY date",
        (start, end)
    ).fetchall()
    return [r["date"] for r in rows]


def fetch_ohlcv(conn, ticker: str, as_of: str, bars: int) -> pd.DataFrame:
    rows = conn.execute(
        """SELECT date, open, high, low, close, volume FROM ohlcv
           WHERE ticker = ? AND date <= ? ORDER BY date DESC LIMIT ?""",
        (ticker, as_of, bars)
    ).fetchall()
    if len(rows) < 230:
        return pd.DataFrame()
    df = pd.DataFrame([dict(r) for r in reversed(rows)])
    df.index = pd.to_datetime(df["date"])
    df.drop(columns=["date"], inplace=True)
    return df.astype(float)


def scanner_signals(conn, start: str, end: str, min_score: int) -> dict[str, set[str]]:
    """Ground truth from scanner_results: {run_date: set(tickers)}."""
    rows = conn.execute(
        """SELECT run_date, ticker FROM scanner_results
           WHERE run_date >= ? AND run_date <= ? AND score >= ?""",
        (start.replace("-", ""), end.replace("-", ""), min_score)
    ).fetchall()
    result: dict[str, set[str]] = defaultdict(set)
    for r in rows:
        date = r["run_date"]
        # Normalize to YYYY-MM-DD
        if len(date) == 8:
            date = f"{date[:4]}-{date[4:6]}-{date[6:]}"
        result[date].add(r["ticker"])
    return dict(result)


def active_tickers(conn, as_of: str, min_bars: int = 230) -> list[str]:
    rows = conn.execute(
        """SELECT ticker, COUNT(*) as cnt FROM ohlcv
           WHERE date <= ? GROUP BY ticker HAVING cnt >= ?""",
        (as_of, min_bars)
    ).fetchall()
    return [r["ticker"] for r in rows]


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--start", required=True, help="YYYY-MM-DD")
    p.add_argument("--end",   required=True, help="YYYY-MM-DD")
    p.add_argument("--db",    default=str(DB_PATH))
    p.add_argument("--min-score", type=int, default=MIN_SCORE)
    p.add_argument("--tickers", nargs="+", help="Limit to specific tickers")
    p.add_argument("--verbose", "-v", action="store_true")
    args = p.parse_args()

    db = Path(args.db)
    if not db.exists():
        sys.exit(f"DB not found: {db}")

    conn = connect(db)
    dates = trading_dates(conn, args.start, args.end)
    if not dates:
        sys.exit(f"No trading dates found in [{args.start}, {args.end}]")

    ground_truth = scanner_signals(conn, args.start, args.end, args.min_score)
    print(f"Dates: {len(dates)}  Ground truth days: {len(ground_truth)}")

    # Per-condition match tracking
    cond_tp = [0] * 8
    cond_fp = [0] * 8
    cond_fn = [0] * 8

    total_tp = total_fp = total_fn = 0
    all_signals: dict[str, list[str]] = {}

    for date in dates:
        tickers = args.tickers or active_tickers(conn, date, min_bars=230)
        day_signals = []

        for ticker in tickers:
            daily = fetch_ohlcv(conn, ticker, date, DAILY_BARS)
            if daily.empty:
                continue
            result = score_df(daily)
            if result is None or result["score"] < args.min_score:
                continue
            day_signals.append(ticker)

        all_signals[date] = day_signals
        gt = ground_truth.get(date, set())
        sig_set = set(day_signals)

        tp = sig_set & gt
        fp = sig_set - gt
        fn = gt - sig_set

        total_tp += len(tp)
        total_fp += len(fp)
        total_fn += len(fn)

        if args.verbose:
            print(f"{date}: local={len(sig_set)} scanner={len(gt)} tp={len(tp)} fp={len(fp)} fn={len(fn)}")
            if fn:
                print(f"  missed: {sorted(fn)[:10]}")
            if fp:
                print(f"  extra:  {sorted(fp)[:10]}")

        # Per-condition breakdown for TP tickers
        for ticker in tp:
            daily = fetch_ohlcv(conn, ticker, date, DAILY_BARS)
            result = score_df(daily)
            if result:
                sc_row = conn.execute(
                    "SELECT c1,c2,c3,c4,c5,c6,c7,c8 FROM scanner_results WHERE ticker=? AND run_date=?",
                    (ticker, date.replace("-", ""))
                ).fetchone()
                if sc_row:
                    for i, (local_c, sc_c) in enumerate(zip(result["conditions"], [sc_row[f"c{j+1}"] for j in range(8)])):
                        if local_c and sc_c:   cond_tp[i] += 1
                        elif local_c and not sc_c: cond_fp[i] += 1
                        elif not local_c and sc_c: cond_fn[i] += 1

    # Summary
    recall    = total_tp / (total_tp + total_fn) if (total_tp + total_fn) else 0
    precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) else 0

    print(f"\n{'='*50}")
    print(f"  Period: {args.start} → {args.end}  ({len(dates)} days)")
    print(f"  Min score: {args.min_score}/8")
    print(f"  TP={total_tp}  FP={total_fp}  FN={total_fn}")
    print(f"  Recall:    {recall*100:.1f}%")
    print(f"  Precision: {precision*100:.1f}%")
    print(f"\n  Per-condition match (TP tickers only):")
    cond_names = ["W>cloud","W:TK>KJ","W:chikou","W:green","D>cloud","D>tenkan","ADX","200MA"]
    for i, name in enumerate(cond_names):
        tp_i = cond_tp[i]; fp_i = cond_fp[i]; fn_i = cond_fn[i]
        match = tp_i / (tp_i + fp_i + fn_i) * 100 if (tp_i + fp_i + fn_i) else 0
        print(f"    C{i+1} {name:<10} match={match:.0f}%  tp={tp_i} fp={fp_i} fn={fn_i}")
    print(f"{'='*50}")

    conn.close()


if __name__ == "__main__":
    main()
