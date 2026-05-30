#!/usr/bin/env python3
"""Precompute step 1 of 2 — TRADEABILITY FILTER (#233).

ARCH2 universe pipeline: filter (#233, THIS) -> rank+cap (build_universe.py, #220).
Seam (B): two artifacts, true separation. This produces the ELIGIBLE artifact; the
universe step reads it and ranks+caps. The two fingerprints let divergence-debug check
the eligible-set FIRST, then the ranked set (narrows #182-class local/cloud bugs fast).

WHAT THIS DOES — eligibility floors ONLY, no rank, no cap, no Ichimoku:
  A per-trading-date eligible set computed ONLY from bars dated <= that date (no
  hindsight, survivorship-clean: delisted tickers vanish after their last bar, newly
  listed appear once they have history).

  Eligibility AS OF a date D (using only bars with date <= D):
    (a) latest close (the bar at-or-before D) >= min_price, AND
    (b) trailing adv_window-day mean dollar-volume >= min_avg_dollar_volume,
  and the ticker must have at least adv_window bars up to and incl D.

OUTPUT carries the trailing-mean DV per eligible ticker so the universe step can rank
by it WITHOUT re-reading ~19k zips:
  data/universe/<auto>.filter.json -> {"YYYY-MM-DD": {"ticker": dv_mean, ...}, ...,
                                       "_filter_meta": {...}}
  Sibling .filter.meta.json -> params + MEMBERSHIP fingerprint (sha256 over
  date->sorted(tickers), DV excluded — a PURE eligibility fingerprint, the thing you
  diff first when cloud != local).

EVERY substrate trading date gets a key (empty dict if zero-eligible) — completeness by
construction, so a consumer's missing date means a NON-trading day, never a silent gap
(#182's other trap). NO timestamp emitted (Date.now blocked) — the content hash is the
provenance handle.

Substrate: data/equity/usa/daily/<ticker>.zip, rows 'YYYYMMDD 00:00,O,H,L,C,V'.
OHLC in DECI-CENTS (price$ = field/10_000); Volume shares. RAW-only (never
back-adjusted — the 7x-calibration / 1.079 lesson). dollar_volume$ = (Close/10_000)*Volume.
"""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path
from typing import Any

import pandas as pd

# Single-source the fingerprint algorithm: build-time hash MUST equal the load-time
# verify in runtime/lean_entry.py (the anti-#182 fp guardrail). Never reimplement here.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from runtime.fingerprints import membership_hash  # noqa: E402

DECI_CENTS_PER_DOLLAR = 10_000.0


def _ticker_from_zip(zip_path: Path) -> str:
    """Ticker = zip stem, lowercased to match LEAN's on-disk convention."""
    return zip_path.stem.lower()


def load_ticker_frame(zip_path: Path) -> pd.DataFrame | None:
    """Load one daily zip into a DataFrame indexed by date with `close` and
    `dollar_volume` columns (both in $). Returns None if empty/unreadable.

    The inner file is <ticker>.csv with rows 'YYYYMMDD 00:00,O,H,L,C,V' (no header);
    only Close + Volume are needed.
    """
    try:
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            if not names:
                return None
            with zf.open(names[0]) as fh:
                df = pd.read_csv(
                    fh,
                    header=None,
                    usecols=[0, 4, 5],
                    names=["dt", "close_dc", "volume"],
                    dtype={"close_dc": "float64", "volume": "float64"},
                )
    except (zipfile.BadZipFile, OSError, ValueError):
        return None

    if df.empty:
        return None

    date_str = df["dt"].astype(str).str.slice(0, 8)
    df = df.assign(date=pd.to_datetime(date_str, format="%Y%m%d", errors="coerce"))
    df = df.dropna(subset=["date"])
    if df.empty:
        return None

    df["close"] = df["close_dc"] / DECI_CENTS_PER_DOLLAR
    df["dollar_volume"] = df["close"] * df["volume"]
    df = df.set_index("date").sort_index()
    # Defend against duplicate dates within one file (keep last bar of the day).
    df = df[~df.index.duplicated(keep="last")]
    return df[["close", "dollar_volume"]]


def build_filter(
    data_dir: Path,
    min_price: float,
    min_avg_dollar_volume: float,
    adv_window: int,
    limit_tickers: int | None = None,
) -> dict[str, dict[str, float]]:
    """Return {date_str -> {ticker -> trailing_mean_dv}} for the eligible set per date.

    Build two wide frames (close, trailing-mean DV) indexed by the union of all trading
    dates, columns = tickers. A ticker's DV is NaN on dates with < adv_window bars up to
    and incl that date (point-in-time guard). Per date, keep tickers clearing both floors
    and emit their trailing-mean DV (so the universe step ranks without re-reading zips).
    """
    zips = sorted(data_dir.glob("*.zip"))
    if limit_tickers is not None:
        zips = zips[:limit_tickers]
    if not zips:
        raise SystemExit(f"no .zip files found in {data_dir}")

    close_cols: dict[str, pd.Series] = {}
    dvmean_cols: dict[str, pd.Series] = {}

    for zp in zips:
        ticker = _ticker_from_zip(zp)
        frame = load_ticker_frame(zp)
        if frame is None or frame.empty:
            continue
        # Trailing adv_window mean: min_periods=adv_window => NaN until enough history.
        dvmean = frame["dollar_volume"].rolling(window=adv_window, min_periods=adv_window).mean()
        close_cols[ticker] = frame["close"]
        dvmean_cols[ticker] = dvmean

    if not dvmean_cols:
        return {}

    close_df = pd.DataFrame(close_cols).sort_index()
    dvmean_df = pd.DataFrame(dvmean_cols).reindex(close_df.index)

    # Eligibility mask. NaN close (not yet/no longer listed) or NaN dvmean (< adv_window
    # bars) fails the comparison (NaN >= x is False) -> excluded.
    eligible = (
        dvmean_df.notna()
        & (close_df >= min_price)
        & (dvmean_df >= min_avg_dollar_volume)
    )

    col_order = sorted(dvmean_df.columns)
    dvmean_df = dvmean_df[col_order]
    eligible = eligible[col_order]

    out: dict[str, dict[str, float]] = {}
    for date in eligible.index:
        # EVERY trading date keyed (empty dict if zero-eligible) — no silent gap (#182).
        date_key = date.strftime("%Y-%m-%d")
        elig_row = eligible.loc[date]
        if not bool(elig_row.any()):
            out[date_key] = {}
            continue
        dv_row = dvmean_df.loc[date]
        out[date_key] = {
            str(t): float(dv_row[t]) for t in col_order if bool(elig_row[t])
        }
    return out


def auto_out_name(min_price: float, min_avg_dollar_volume: float, adv_window: int) -> str:
    return f"floors_p{int(min_price)}_adv{int(min_avg_dollar_volume)}_w{adv_window}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--min-price", type=float, default=10.0, help="min latest close, $ (tradeability floor)")
    ap.add_argument("--min-avg-dollar-volume", type=float, default=100_000_000.0,
                    help="min trailing-mean dollar volume, $ (LIQUIDITY threshold; 100M = "
                         "liquid large/mid caps, ~943 names/day FY2025 — fintrack ruling)")
    ap.add_argument("--adv-window", type=int, default=20, help="trailing trading-day window for ADV mean")
    ap.add_argument("--data-dir", type=Path, default=Path("data/equity/usa/daily"))
    ap.add_argument("--out", type=Path, default=None, help="output JSON path (auto under data/universe if omitted)")
    ap.add_argument("--limit-tickers", type=int, default=None, help="cap tickers (for fast tests)")
    args = ap.parse_args(argv)

    filt = build_filter(
        data_dir=args.data_dir,
        min_price=args.min_price,
        min_avg_dollar_volume=args.min_avg_dollar_volume,
        adv_window=args.adv_window,
        limit_tickers=args.limit_tickers,
    )

    fingerprint = membership_hash(filt)
    params: dict[str, Any] = {
        "min_price": args.min_price,
        "min_avg_dollar_volume": args.min_avg_dollar_volume,
        "adv_window": args.adv_window,
        "data_dir": str(args.data_dir),
        "limit_tickers": args.limit_tickers,
    }

    out_path = args.out
    if out_path is None:
        out_path = Path("data/universe") / (
            auto_out_name(args.min_price, args.min_avg_dollar_volume, args.adv_window) + ".filter.json"
        )
    out_path.parent.mkdir(parents=True, exist_ok=True)

    meta_block = {
        "model": "tradeability filter (#233): eligibility floors only, no rank/cap/Ichimoku; carries trailing-mean DV per eligible ticker",
        "params": params,
        "min_price": args.min_price,
        "min_avg_dollar_volume": args.min_avg_dollar_volume,
        "adv_window": args.adv_window,
        "substrate_fingerprint": "see data/MANIFEST.json",
        "membership_fingerprint": fingerprint,
        "num_dates": len(filt),
    }

    payload: dict[str, Any] = {date: filt[date] for date in sorted(filt)}
    payload["_filter_meta"] = meta_block
    out_path.write_text(json.dumps(payload, separators=(",", ":"), sort_keys=False))

    meta_path = out_path.with_suffix(".meta.json")
    meta_path.write_text(json.dumps(meta_block, indent=2, sort_keys=True))

    print(f"wrote {out_path} ({len(filt)} trading dates)")
    print(f"wrote {meta_path}")
    print(f"membership_fingerprint: {fingerprint}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
