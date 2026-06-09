"""Offline first-hour confirmation audit for the score-6 BCT candidate lane.

This is a research/audit helper. It reads explicit candidate/denominator inputs plus local LEAN
5-minute trade zips, computes first-hour confirmation facts, and reports how many candidates or
George labels survive each confirmation gate. Runtime strategy code must not import it.
"""
from __future__ import annotations

import argparse
import datetime as dt
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import math
import pandas as pd

from sweeps.archive import george_coverage_audit as coverage
from sweeps.archive import george_topk_audit as topk
from sweeps.archive import massive_qc_bridge as bridge


PRICE_SCALE: float = 10000.0
MARKET_OPEN_MS: int = 34_200_000


@dataclass(frozen=True, slots=True)
class FirstHourConfig:
    """First-hour confirmation thresholds."""

    first_hour_bars: int = 12
    max_open_flush_pct: float = 2.0
    min_first_hour_adv_ratio: float = 0.08
    min_first_hour_return_pct: float = 0.0


@dataclass(frozen=True, slots=True)
class FirstHourResult:
    panel: pd.DataFrame
    summary: pd.DataFrame
    flag_summary: pd.DataFrame


def minute_zip_path(minute_dir: Path, symbol: str, date: str) -> Path:
    """Return local LEAN minute trade zip path for symbol/date."""
    lean = symbol.lower()
    ymd = date.replace("-", "")
    return minute_dir / lean / f"{ymd}_trade.zip"


def read_minute_trade_zip(minute_dir: Path, symbol: str, date: str) -> pd.DataFrame | None:
    """Read one local LEAN 5-minute trade zip; return None when absent."""
    path = minute_zip_path(minute_dir, symbol, date)
    if not path.is_file():
        return None
    with zipfile.ZipFile(path) as zf:
        raw = zf.read(zf.namelist()[0]).decode()
    midnight = pd.Timestamp(dt.datetime.strptime(date.replace("-", ""), "%Y%m%d"))
    rows: list[tuple[pd.Timestamp, float, float, float, float, float]] = []
    for line in raw.strip().splitlines():
        ms, open_, high, low, close, volume = line.split(",")
        rows.append(
            (
                midnight + pd.Timedelta(milliseconds=int(ms)),
                float(open_) / PRICE_SCALE,
                float(high) / PRICE_SCALE,
                float(low) / PRICE_SCALE,
                float(close) / PRICE_SCALE,
                float(volume),
            )
        )
    if not rows:
        return None
    return pd.DataFrame(rows, columns=["time", "open", "high", "low", "close", "volume"]).set_index("time")


def first_hour_slice(bars: pd.DataFrame, *, first_hour_bars: int) -> pd.DataFrame:
    """Return completed bars in the first-hour window, starting at regular-session open."""
    if bars.empty:
        return bars
    ms = (
        (bars.index.hour * 60 * 60 * 1000)
        + (bars.index.minute * 60 * 1000)
        + (bars.index.second * 1000)
    )
    regular = bars[ms >= MARKET_OPEN_MS]
    return regular.head(first_hour_bars)


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _row_float(row: pd.Series, name: str) -> float | None:
    if name not in row or not _finite(row[name]):
        return None
    return float(row[name])


def _prior_close(row: pd.Series, first_open: float) -> float | None:
    prior = _row_float(row, "prior_close")
    if prior is not None and prior > 0.0:
        return prior
    gap_pct = _row_float(row, "gap_pct")
    if gap_pct is None:
        return None
    denom = 1.0 + gap_pct / 100.0
    if denom <= 0.0:
        return None
    return first_open / denom


def first_hour_features(row: pd.Series, bars: pd.DataFrame, *, config: FirstHourConfig) -> dict[str, Any]:
    """Compute first-hour confirmation facts for one candidate row."""
    symbol = str(row["symbol"]).upper()
    date = str(row["date"])
    first_hour = first_hour_slice(bars, first_hour_bars=config.first_hour_bars)
    if first_hour.empty:
        return {
            "date": date,
            "symbol": symbol,
            "key": f"{date}|{symbol}",
            "intraday_available": False,
            "fh_bars": 0,
        }

    first = first_hour.iloc[0]
    last = first_hour.iloc[-1]
    first_open = float(first["open"])
    first_bar_high = float(first["high"])
    fh_high = float(first_hour["high"].max())
    fh_low = float(first_hour["low"].min())
    fh_close = float(last["close"])
    fh_volume = float(first_hour["volume"].sum())
    prior_close = _prior_close(row, first_open)
    avg_volume20 = _row_float(row, "avg_volume20")
    fh_return_pct = (fh_close / first_open - 1.0) * 100.0 if first_open > 0.0 else math.nan
    fh_range_pct = (fh_high / first_open - 1.0) * 100.0 if first_open > 0.0 else math.nan
    fh_drawdown_pct = (fh_low / first_open - 1.0) * 100.0 if first_open > 0.0 else math.nan
    fh_volume_adv_ratio = (
        fh_volume / avg_volume20 if avg_volume20 is not None and avg_volume20 > 0.0 else math.nan
    )
    fh_green = fh_return_pct > config.min_first_hour_return_pct
    fh_no_open_flush = fh_drawdown_pct >= -config.max_open_flush_pct
    fh_above_prior_close = prior_close is not None and fh_close > prior_close
    fh_reclaims_first_bar_high = fh_close >= first_bar_high
    fh_volume_ok = _finite(fh_volume_adv_ratio) and fh_volume_adv_ratio >= config.min_first_hour_adv_ratio
    fh_confirm_basic = fh_green and fh_no_open_flush and fh_above_prior_close
    return {
        "date": date,
        "symbol": symbol,
        "key": f"{date}|{symbol}",
        "intraday_available": True,
        "fh_bars": int(len(first_hour)),
        "fh_open": first_open,
        "fh_high": fh_high,
        "fh_low": fh_low,
        "fh_close": fh_close,
        "fh_volume": fh_volume,
        "fh_return_pct": fh_return_pct,
        "fh_range_pct": fh_range_pct,
        "fh_drawdown_pct": fh_drawdown_pct,
        "fh_volume_adv_ratio": fh_volume_adv_ratio,
        "fh_green": fh_green,
        "fh_no_open_flush": fh_no_open_flush,
        "fh_above_prior_close": fh_above_prior_close,
        "fh_reclaims_first_bar_high": fh_reclaims_first_bar_high,
        "fh_volume_ok": fh_volume_ok,
        "fh_confirm_basic": fh_confirm_basic,
        "fh_confirm_breakout": fh_confirm_basic and fh_reclaims_first_bar_high,
        "fh_confirm_volume": fh_confirm_basic and fh_volume_ok,
        "fh_confirm_breakout_volume": fh_confirm_basic and fh_reclaims_first_bar_high and fh_volume_ok,
    }


def build_confirmation_panel(
    candidates: pd.DataFrame,
    *,
    minute_dir: Path,
    config: FirstHourConfig = FirstHourConfig(),
    max_rows: int | None = None,
) -> pd.DataFrame:
    """Join candidate rows to first-hour intraday confirmation facts."""
    rows: list[dict[str, Any]] = []
    frame_cache: dict[tuple[str, str], pd.DataFrame | None] = {}
    source = candidates.copy()
    source["date"] = source["date"].astype(str)
    source["symbol"] = source["symbol"].astype(str).str.upper()
    if max_rows is not None:
        source = source.head(max_rows)
    for _, row in source.iterrows():
        key = (str(row["date"]), str(row["symbol"]).upper())
        if key not in frame_cache:
            frame_cache[key] = read_minute_trade_zip(minute_dir, key[1], key[0])
        bars = frame_cache[key]
        base = row.to_dict()
        if bars is None:
            base.update(
                {
                    "key": f"{key[0]}|{key[1]}",
                    "intraday_available": False,
                    "fh_bars": 0,
                }
            )
        else:
            base.update(first_hour_features(row, bars, config=config))
        rows.append(base)
    return pd.DataFrame(rows)


def summarize_flags(panel: pd.DataFrame, labels: Sequence[tuple[str, str]]) -> pd.DataFrame:
    """Summarize first-hour confirmation flags for all rows and optional George labels."""
    flags = (
        "intraday_available",
        "fh_green",
        "fh_no_open_flush",
        "fh_above_prior_close",
        "fh_reclaims_first_bar_high",
        "fh_volume_ok",
        "fh_confirm_basic",
        "fh_confirm_breakout",
        "fh_confirm_volume",
        "fh_confirm_breakout_volume",
    )
    label_keys = {f"{date}|{symbol.upper()}" for date, symbol in labels}
    panel_keys = set(panel["key"].astype(str)) if "key" in panel else set()
    panel_label_hits = len(label_keys & panel_keys)
    base_precision = panel_label_hits / len(panel) if len(panel) and label_keys else 0.0
    rows: list[dict[str, Any]] = []
    for flag in flags:
        mask = topk._bool_col(panel, flag)
        selected = panel[mask]
        hits = int(selected["key"].astype(str).isin(label_keys).sum()) if label_keys else 0
        precision = hits / len(selected) if len(selected) else 0.0
        rows.append(
            {
                "flag": flag,
                "rows": int(len(selected)),
                "median_daily": float(selected.groupby("date").size().median()) if len(selected) else 0.0,
                "label_hits": hits,
                "label_recall_pct": round(100.0 * hits / len(label_keys), 2) if label_keys else 0.0,
                "panel_label_recall_pct": (
                    round(100.0 * hits / panel_label_hits, 2) if panel_label_hits else 0.0
                ),
                "label_precision_pct": round(100.0 * precision, 3),
                "label_lift_vs_panel": round(precision / base_precision, 2) if base_precision else 0.0,
                "row_pct": round(100.0 * len(selected) / len(panel), 2) if len(panel) else 0.0,
            }
        )
    return pd.DataFrame(rows)


def summarize_panel(panel: pd.DataFrame, labels: Sequence[tuple[str, str]]) -> pd.DataFrame:
    """Return one-row first-hour audit summary."""
    label_keys = {f"{date}|{symbol.upper()}" for date, symbol in labels}
    panel_keys = set(panel["key"].astype(str)) if "key" in panel else set()
    intraday_keys = set(panel.loc[topk._bool_col(panel, "intraday_available"), "key"].astype(str)) if "key" in panel else set()
    return pd.DataFrame(
        [
            {
                "rows": int(len(panel)),
                "dates": int(panel["date"].nunique()) if "date" in panel else 0,
                "intraday_available_rows": int(topk._bool_col(panel, "intraday_available").sum()),
                "labels": len(label_keys),
                "labels_in_panel": len(label_keys & panel_keys),
                "labels_with_intraday": len(label_keys & intraday_keys),
            }
        ]
    )


def run_confirmation(
    candidates: pd.DataFrame,
    *,
    minute_dir: Path,
    labels: Sequence[tuple[str, str]] = (),
    config: FirstHourConfig = FirstHourConfig(),
    max_rows: int | None = None,
) -> FirstHourResult:
    """Run the first-hour confirmation audit."""
    panel = build_confirmation_panel(candidates, minute_dir=minute_dir, config=config, max_rows=max_rows)
    return FirstHourResult(
        panel=panel,
        summary=summarize_panel(panel, labels),
        flag_summary=summarize_flags(panel, labels),
    )


def write_result(result: FirstHourResult, output_dir: Path) -> None:
    """Write first-hour confirmation artifacts as CSVs."""
    output_dir.mkdir(parents=True, exist_ok=True)
    result.panel.to_csv(output_dir / "first_hour_panel.csv", index=False)
    result.summary.to_csv(output_dir / "summary.csv", index=False)
    result.flag_summary.to_csv(output_dir / "flag_summary.csv", index=False)


def _candidate_input(args: argparse.Namespace) -> pd.DataFrame:
    if args.candidate_csv is not None:
        return pd.read_csv(args.candidate_csv, low_memory=False)
    if args.denominator_csv is None:
        raise ValueError("pass either --candidate-csv or --denominator-csv")
    covered_dates = topk.covered_dates_from_coarse(args.year, args.coarse_dir) if args.coarse_dir else None
    bridge_result = bridge.run_bridge(
        bridge.load_denominator(args.denominator_csv),
        covered_dates=covered_dates,
        config=bridge.BridgeConfig(top_n=args.top_n, min_score=args.min_score),
    )
    return bridge_result.panel


def _labels(args: argparse.Namespace) -> list[tuple[str, str]]:
    if args.labels_csv is None:
        return []
    labels = coverage.load_george_labels(args.labels_csv)
    if args.coarse_dir is None:
        return labels
    covered_dates = topk.covered_dates_from_coarse(args.year, args.coarse_dir)
    return [(date, symbol) for date, symbol in labels if date in covered_dates]


def _print_result(result: FirstHourResult) -> None:
    print("\nSUMMARY")
    print(result.summary.to_string(index=False))
    print("\nFLAGS")
    print(result.flag_summary.to_string(index=False))


def _filter_labels_only(candidates: pd.DataFrame, labels: Sequence[tuple[str, str]]) -> pd.DataFrame:
    if not labels:
        return candidates
    label_keys = {f"{date}|{symbol.upper()}" for date, symbol in labels}
    source = candidates.copy()
    source["date"] = source["date"].astype(str)
    source["symbol"] = source["symbol"].astype(str).str.upper()
    keys = source["date"] + "|" + source["symbol"]
    return source.loc[keys.isin(label_keys)].reset_index(drop=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-csv", type=Path)
    parser.add_argument("--denominator-csv", type=Path)
    parser.add_argument("--labels-csv", type=Path)
    parser.add_argument("--coarse-dir", type=Path)
    parser.add_argument("--minute-dir", required=True, type=Path)
    parser.add_argument("--year", default=2026, type=int)
    parser.add_argument("--top-n", default=3000, type=int)
    parser.add_argument("--min-score", default=6, type=int)
    parser.add_argument("--max-rows", type=int)
    parser.add_argument("--labels-only", action="store_true")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)

    labels = _labels(args)
    candidates = _candidate_input(args)
    if args.labels_only:
        candidates = _filter_labels_only(candidates, labels)
    result = run_confirmation(
        candidates,
        minute_dir=args.minute_dir,
        labels=labels,
        max_rows=args.max_rows,
    )
    _print_result(result)
    if args.output_dir is not None:
        write_result(result, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
