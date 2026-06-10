"""Replay future paths for the #463 scanner opportunity panel.

This script consumes the label-free opportunity panel and writes future outcome labels as a
separate artifact. It uses local raw intraday parquet files to derive regular-session daily bars
and does not depend on QC Cloud.
"""
from __future__ import annotations

import argparse
import bisect
import csv
import gzip
import io
import json
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PANEL = ROOT / "sweeps" / "reports" / "scanner_opportunity_panel_463" / "opportunity_panel.csv.gz"
DEFAULT_PARQUET_ROOT = Path("/Users/falk/projects/kumo-trader/data/intraday")
DEFAULT_OUTPUT_DIR = ROOT / "sweeps" / "reports" / "scanner_opportunity_paths_464"
HORIZONS = (1, 2, 5, 10, 20, 40)
TARGET_STOP_PAIRS = ((4, 2), (8, 4))
PANEL_SOURCE_COLUMNS = [
    "scan_date",
    "symbol",
    "kumo_scanner",
    "kumo_top_n",
    "george_scanner_positive",
    "george_watchlist",
    "george_video_mention",
    "kumo_rank_by_score",
    "kumo_score",
    "george_rank",
    "george_watchlist_rank",
    "source_tags",
]


@dataclass(frozen=True)
class DailyBar:
    symbol: str
    day: str
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class BuildConfig:
    panel: str
    parquet_root: str
    output_dir: str
    entry_assumption: str
    horizons: tuple[int, ...]
    target_stop_pairs: tuple[tuple[int, int], ...]
    limit: int | None


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", type=Path, default=DEFAULT_PANEL)
    parser.add_argument("--parquet-root", type=Path, default=DEFAULT_PARQUET_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--limit", type=int, default=None, help="Optional row limit for smoke/debug runs.")
    return parser.parse_args()


def _parse_day(value: Any) -> str:
    if pd.isna(value):
        return ""
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return ""
    return parsed.strftime("%Y-%m-%d")


def _clean_symbol(value: Any) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip().upper()


def _bool_series(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip().str.lower().isin({"1", "true", "yes", "y"})


def _pct(value: float | None) -> float | None:
    if value is None or pd.isna(value):
        return None
    return round(float(value), 4)


def _empty_metrics(horizons: Sequence[int]) -> dict[str, Any]:
    row: dict[str, Any] = {}
    for horizon in horizons:
        row[f"label_ret_{horizon}d_close_pct"] = None
        row[f"label_mfe_{horizon}d_pct"] = None
        row[f"label_mae_{horizon}d_pct"] = None
        row[f"label_available_{horizon}d_sessions"] = 0
        row[f"label_time_to_peak_{horizon}d_sessions"] = None
        row[f"label_max_giveback_after_peak_{horizon}d_pct"] = None
        for target, stop in TARGET_STOP_PAIRS:
            row[f"label_t{target}_s{stop}_{horizon}d_outcome"] = "unavailable"
    return row


def parquet_calendar(parquet_root: Path) -> list[str]:
    if not parquet_root.exists():
        raise FileNotFoundError(parquet_root)
    days = []
    for path in parquet_root.glob("*.parquet"):
        parsed = _parse_day(path.stem)
        if parsed:
            days.append(parsed)
    return sorted(set(days))


def _read_panel(path: Path, *, limit: int | None) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    frame = pd.read_csv(path, usecols=lambda column: column in set(PANEL_SOURCE_COLUMNS), low_memory=False)
    if limit is not None:
        frame = frame.head(limit).copy()
    frame["scan_date"] = frame["scan_date"].map(_parse_day)
    frame["symbol"] = frame["symbol"].map(_clean_symbol)
    frame = frame[(frame["scan_date"] != "") & (frame["symbol"] != "")].copy()
    for column in [
        "kumo_scanner",
        "kumo_top_n",
        "george_scanner_positive",
        "george_watchlist",
        "george_video_mention",
    ]:
        frame[column] = _bool_series(frame[column])
    return frame.reset_index(drop=True)


def _needed_dates(panel: pd.DataFrame, calendar: list[str], *, max_horizon: int) -> list[str]:
    needed: set[str] = set()
    for scan_day in sorted(panel["scan_date"].unique()):
        entry_idx = bisect.bisect_right(calendar, scan_day)
        if entry_idx >= len(calendar):
            continue
        for day in calendar[entry_idx : min(len(calendar), entry_idx + max_horizon)]:
            needed.add(day)
        prior_idx = entry_idx - 1
        if prior_idx >= 0:
            needed.add(calendar[prior_idx])
    return sorted(needed)


def _regular_session_daily_bars(frame: pd.DataFrame, *, day: str, symbols: set[str]) -> list[DailyBar]:
    frame = frame.rename(columns={"ticker": "symbol"}).copy()
    frame["symbol"] = frame["symbol"].map(_clean_symbol)
    frame = frame[frame["symbol"].isin(symbols)].copy()
    if frame.empty:
        return []
    time_text = frame["datetime"].astype(str).str.slice(11, 19)
    frame = frame[(time_text >= "09:30:00") & (time_text <= "16:00:00")].copy()
    if frame.empty:
        return []
    frame = frame.sort_values(["symbol", "datetime"])
    grouped = frame.groupby("symbol", sort=False)
    bars: list[DailyBar] = []
    for symbol, group in grouped:
        bars.append(
            DailyBar(
                symbol=str(symbol),
                day=day,
                open=float(group["open"].iloc[0]),
                high=float(group["high"].max()),
                low=float(group["low"].min()),
                close=float(group["close"].iloc[-1]),
                volume=float(group["volume"].sum()),
            )
        )
    return bars


def build_daily_bar_lookup(
    *,
    parquet_root: Path,
    dates: Sequence[str],
    symbols: set[str],
) -> dict[tuple[str, str], DailyBar]:
    lookup: dict[tuple[str, str], DailyBar] = {}
    for day in dates:
        path = parquet_root / f"{day}.parquet"
        if not path.exists():
            continue
        frame = pd.read_parquet(path, columns=["ticker", "datetime", "open", "high", "low", "close", "volume"])
        bars = _regular_session_daily_bars(frame, day=day, symbols=symbols)
        for bar in bars:
            lookup[(bar.symbol, day)] = bar
    return lookup


def target_stop_outcome(
    *,
    entry_price: float,
    bars: Sequence[DailyBar],
    target_pct: float,
    stop_pct: float,
) -> str:
    target_price = entry_price * (1.0 + target_pct / 100.0)
    stop_price = entry_price * (1.0 - stop_pct / 100.0)
    for bar in bars:
        hit_target = bar.high >= target_price
        hit_stop = bar.low <= stop_price
        if hit_target and hit_stop:
            return "ambiguous_same_day"
        if hit_target:
            return "target_before_stop"
        if hit_stop:
            return "stop_before_target"
    return "neither"


def horizon_metrics(
    *,
    entry_price: float,
    scheduled_days: Sequence[str],
    bars_by_day: dict[str, DailyBar],
    horizon: int,
) -> dict[str, Any]:
    horizon_days = list(scheduled_days[:horizon])
    available_bars = [bars_by_day[day] for day in horizon_days if day in bars_by_day]
    row: dict[str, Any] = {f"label_available_{horizon}d_sessions": len(available_bars)}
    if not available_bars:
        row[f"label_ret_{horizon}d_close_pct"] = None
        row[f"label_mfe_{horizon}d_pct"] = None
        row[f"label_mae_{horizon}d_pct"] = None
        row[f"label_time_to_peak_{horizon}d_sessions"] = None
        row[f"label_max_giveback_after_peak_{horizon}d_pct"] = None
        for target, stop in TARGET_STOP_PAIRS:
            row[f"label_t{target}_s{stop}_{horizon}d_outcome"] = "unavailable"
        return row

    high_values = [bar.high for bar in available_bars]
    low_values = [bar.low for bar in available_bars]
    max_high = max(high_values)
    min_low = min(low_values)
    row[f"label_mfe_{horizon}d_pct"] = _pct((max_high / entry_price - 1.0) * 100.0)
    row[f"label_mae_{horizon}d_pct"] = _pct((min_low / entry_price - 1.0) * 100.0)
    horizon_close_bar = bars_by_day.get(horizon_days[-1]) if horizon_days else None
    row[f"label_ret_{horizon}d_close_pct"] = (
        _pct((horizon_close_bar.close / entry_price - 1.0) * 100.0) if horizon_close_bar else None
    )

    peak_bar = next(bar for bar in available_bars if bar.high == max_high)
    peak_session = horizon_days.index(peak_bar.day) + 1 if peak_bar.day in horizon_days else None
    row[f"label_time_to_peak_{horizon}d_sessions"] = peak_session
    bars_after_peak = [bar for bar in available_bars if horizon_days.index(bar.day) >= horizon_days.index(peak_bar.day)]
    min_low_after_peak = min(bar.low for bar in bars_after_peak) if bars_after_peak else peak_bar.low
    row[f"label_max_giveback_after_peak_{horizon}d_pct"] = _pct((max_high - min_low_after_peak) / entry_price * 100.0)

    for target, stop in TARGET_STOP_PAIRS:
        row[f"label_t{target}_s{stop}_{horizon}d_outcome"] = target_stop_outcome(
            entry_price=entry_price,
            bars=available_bars,
            target_pct=float(target),
            stop_pct=float(stop),
        )
    return row


def classify_outcome(row: dict[str, Any]) -> str:
    if row.get("label_path_status") in {"no_entry_date", "missing_entry_bar"}:
        return "unavailable"
    if bool(row.get("label_bad_trade_20d")):
        return "bad_trade"
    if bool(row.get("label_runner_candidate_20d")) and row.get("label_t4_s2_20d_outcome") != "stop_before_target":
        return "runner_candidate"
    if bool(row.get("label_normal_winner_20d")):
        return "normal_winner"
    if bool(row.get("label_runner_candidate_20d")):
        return "runner_candidate"
    return "chop_or_unclear"


def add_compact_labels(row: dict[str, Any]) -> None:
    if row.get("label_path_status") in {"no_entry_date", "missing_entry_bar"}:
        row["label_runner_candidate_20d"] = False
        row["label_normal_winner_20d"] = False
        row["label_bad_trade_20d"] = False
        row["label_extreme_path_flag"] = False
        row["label_extreme_path_reason"] = ""
        row["label_outcome_20d"] = classify_outcome(row)
        return
    mfe20 = row.get("label_mfe_20d_pct")
    mae20 = row.get("label_mae_20d_pct")
    ret20 = row.get("label_ret_20d_close_pct")
    target4 = row.get("label_t4_s2_20d_outcome")
    row["label_runner_candidate_20d"] = (mfe20 is not None and mfe20 >= 15.0) or (
        ret20 is not None and ret20 >= 10.0
    )
    row["label_normal_winner_20d"] = target4 == "target_before_stop" or (
        ret20 is not None and ret20 >= 5.0
    ) or (mfe20 is not None and mfe20 >= 8.0)
    row["label_bad_trade_20d"] = (
        target4 == "stop_before_target" and (ret20 is None or ret20 <= 0.0)
    ) or (mae20 is not None and mae20 <= -6.0 and (ret20 is None or ret20 <= 0.0))
    reasons: list[str] = []
    if ret20 is not None and abs(ret20) >= 100.0:
        reasons.append("abs_ret20_ge_100")
    if mfe20 is not None and mfe20 >= 100.0:
        reasons.append("mfe20_ge_100")
    if mae20 is not None and mae20 <= -80.0:
        reasons.append("mae20_le_minus_80")
    row["label_extreme_path_flag"] = bool(reasons)
    row["label_extreme_path_reason"] = ";".join(reasons)
    row["label_outcome_20d"] = classify_outcome(row)


def labels_for_opportunity(
    opportunity: dict[str, Any],
    *,
    calendar: list[str],
    bars: dict[tuple[str, str], DailyBar],
    horizons: Sequence[int],
) -> dict[str, Any]:
    scan_day = str(opportunity["scan_date"])
    symbol = str(opportunity["symbol"])
    entry_idx = bisect.bisect_right(calendar, scan_day)
    base: dict[str, Any] = {
        "scan_date": scan_day,
        "symbol": symbol,
        "entry_assumption": "next_regular_open",
        "label_entry_date": "",
        "label_entry_price": None,
        "label_prior_close": None,
        "label_entry_gap_pct": None,
        "label_path_status": "",
        "label_scheduled_40d_sessions": 0,
        "label_available_40d_sessions": 0,
    }
    if entry_idx >= len(calendar):
        base["label_path_status"] = "no_entry_date"
        base.update(_empty_metrics(horizons))
        add_compact_labels(base)
        return base

    max_horizon = max(horizons)
    scheduled_days = calendar[entry_idx : min(len(calendar), entry_idx + max_horizon)]
    entry_day = scheduled_days[0]
    entry_bar = bars.get((symbol, entry_day))
    base["label_entry_date"] = entry_day
    base["label_scheduled_40d_sessions"] = len(scheduled_days)
    if entry_bar is None:
        base["label_path_status"] = "missing_entry_bar"
        base.update(_empty_metrics(horizons))
        add_compact_labels(base)
        return base

    prior_idx = entry_idx - 1
    prior_bar = bars.get((symbol, calendar[prior_idx])) if prior_idx >= 0 else None
    entry_price = entry_bar.open
    base["label_entry_price"] = round(entry_price, 4)
    base["label_prior_close"] = round(prior_bar.close, 4) if prior_bar else None
    base["label_entry_gap_pct"] = _pct((entry_price / prior_bar.close - 1.0) * 100.0) if prior_bar else None
    bars_by_day = {day: bars[(symbol, day)] for day in scheduled_days if (symbol, day) in bars}
    base["label_available_40d_sessions"] = len(bars_by_day)
    if len(scheduled_days) < max_horizon and len(bars_by_day) < len(scheduled_days):
        base["label_path_status"] = "truncated_calendar_and_symbol_missing"
    elif len(scheduled_days) < max_horizon:
        base["label_path_status"] = "truncated_calendar"
    elif len(bars_by_day) < len(scheduled_days):
        base["label_path_status"] = "partial_symbol_missing"
    else:
        base["label_path_status"] = "available_full_40d"

    for horizon in horizons:
        base.update(
            horizon_metrics(
                entry_price=entry_price,
                scheduled_days=scheduled_days,
                bars_by_day=bars_by_day,
                horizon=horizon,
            )
        )
    add_compact_labels(base)
    return base


def build_labels(
    panel: pd.DataFrame,
    *,
    calendar: list[str],
    bars: dict[tuple[str, str], DailyBar],
    horizons: Sequence[int] = HORIZONS,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for record in panel.to_dict("records"):
        label_row = labels_for_opportunity(record, calendar=calendar, bars=bars, horizons=horizons)
        for column in PANEL_SOURCE_COLUMNS:
            label_row[column] = record.get(column)
        rows.append(label_row)
    source_columns = [column for column in PANEL_SOURCE_COLUMNS if column not in {"scan_date", "symbol"}]
    label_columns = [column for column in rows[0] if column not in {"scan_date", "symbol", *source_columns}]
    ordered = ["scan_date", "symbol", *source_columns, *label_columns]
    return pd.DataFrame(rows).loc[:, ordered]


def source_outcome_summary(labels: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    source_flags = [
        "kumo_scanner",
        "kumo_top_n",
        "george_scanner_positive",
        "george_watchlist",
        "george_video_mention",
    ]
    for flag in source_flags:
        subset = labels[labels[flag]]
        available = subset[~subset["label_outcome_20d"].eq("unavailable")]
        rows.append(
            {
                "source_flag": flag,
                "rows": int(len(subset)),
                "available_rows": int(len(available)),
                "runner_pct": _summary_pct(available["label_runner_candidate_20d"]),
                "normal_winner_pct": _summary_pct(available["label_normal_winner_20d"]),
                "bad_trade_pct": _summary_pct(available["label_bad_trade_20d"]),
                "extreme_path_pct": _summary_pct(available["label_extreme_path_flag"]),
                "avg_ret_20d_close_pct": _summary_mean(available["label_ret_20d_close_pct"]),
                "avg_mfe_20d_pct": _summary_mean(available["label_mfe_20d_pct"]),
                "avg_mae_20d_pct": _summary_mean(available["label_mae_20d_pct"]),
                "t4_s2_target_before_stop_pct": _summary_pct(
                    available["label_t4_s2_20d_outcome"].eq("target_before_stop")
                ),
                "t4_s2_stop_before_target_pct": _summary_pct(
                    available["label_t4_s2_20d_outcome"].eq("stop_before_target")
                ),
            }
        )
    return pd.DataFrame(rows)


def coverage_summary(labels: pd.DataFrame) -> pd.DataFrame:
    rows = (
        labels.groupby("label_path_status", dropna=False)
        .agg(rows=("symbol", "size"), symbols=("symbol", "nunique"), dates=("scan_date", "nunique"))
        .reset_index()
        .rename(columns={"label_path_status": "path_status"})
    )
    total = len(labels)
    rows["pct"] = (100.0 * rows["rows"] / total).round(3) if total else 0.0
    return rows.sort_values("rows", ascending=False).reset_index(drop=True)


def best_worst(labels: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    columns = [
        "scan_date",
        "symbol",
        "source_tags",
        "label_entry_date",
        "label_outcome_20d",
        "label_runner_candidate_20d",
        "label_bad_trade_20d",
        "label_extreme_path_flag",
        "label_ret_20d_close_pct",
        "label_mfe_20d_pct",
        "label_mae_20d_pct",
        "label_t4_s2_20d_outcome",
        "label_t8_s4_20d_outcome",
    ]
    available = labels[~labels["label_outcome_20d"].eq("unavailable")].copy()
    best = available.sort_values(["label_mfe_20d_pct", "label_ret_20d_close_pct"], ascending=[False, False]).head(50)
    worst = available.sort_values(["label_mae_20d_pct", "label_ret_20d_close_pct"], ascending=[True, True]).head(50)
    return best.loc[:, columns], worst.loc[:, columns]


def _summary_pct(mask: pd.Series) -> float:
    if len(mask) == 0:
        return 0.0
    return round(100.0 * float(mask.mean()), 3)


def _summary_mean(series: pd.Series) -> float | None:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        return None
    return round(float(values.mean()), 4)


def _write_gzip_csv(frame: pd.DataFrame, path: Path) -> None:
    with path.open("wb") as raw_fh:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw_fh, mtime=0) as gzip_fh:
            with io.TextIOWrapper(gzip_fh, encoding="utf-8", newline="") as text_fh:
                frame.to_csv(text_fh, index=False)


def _markdown_table(frame: pd.DataFrame, columns: list[str], *, limit: int | None = None) -> str:
    subset = frame.loc[:, columns]
    if limit is not None:
        subset = subset.head(limit)
    if subset.empty:
        return "_No rows._"
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for _, row in subset.iterrows():
        lines.append("| " + " | ".join(str(row[col]) for col in columns) + " |")
    return "\n".join(lines)


def write_report(
    *,
    output_dir: Path,
    labels: pd.DataFrame,
    source_summary: pd.DataFrame,
    coverage: pd.DataFrame,
    config: BuildConfig,
) -> None:
    lines = [
        "# Scanner Opportunity Path Labels #464",
        "",
        "This report adds future path labels to the #463 label-free opportunity panel.",
        "The first entry assumption is `next_regular_open`; additional trigger research belongs to #465.",
        "",
        "## Inputs",
        "",
        f"- Panel: `{config.panel}`",
        f"- Parquet root: `{config.parquet_root}`",
        "",
        "## Label Output",
        "",
        f"- Rows: `{len(labels)}`",
        f"- Dates: `{labels['scan_date'].nunique()}`",
        f"- Symbols: `{labels['symbol'].nunique()}`",
        f"- Available 20d rows: `{int(labels['label_ret_20d_close_pct'].notna().sum())}`",
        "",
        "## Coverage",
        "",
        _markdown_table(coverage, ["path_status", "rows", "symbols", "dates", "pct"]),
        "",
        "## Source Outcome Summary",
        "",
        _markdown_table(
            source_summary,
            [
                "source_flag",
                "rows",
                "available_rows",
                "runner_pct",
                "normal_winner_pct",
                "bad_trade_pct",
                "extreme_path_pct",
                "avg_ret_20d_close_pct",
                "avg_mfe_20d_pct",
                "avg_mae_20d_pct",
                "t4_s2_target_before_stop_pct",
                "t4_s2_stop_before_target_pct",
            ],
        ),
        "",
        "## Label Semantics",
        "",
        "- `label_ret_*d_close_pct` is close return from next regular open to the horizon close.",
        "- `label_mfe_*d_pct` and `label_mae_*d_pct` use regular-session daily highs/lows.",
        "- Target/stop ordering uses daily high/low order by day. If both levels are touched on the",
        "  same daily bar, the outcome is `ambiguous_same_day`.",
        "- Runner, normal-winner, bad-trade, and extreme-path percentages are explicit flags and may",
        "  overlap; `label_outcome_20d` is the compact priority bucket.",
        "- `label_outcome_20d` is a compact research label, not a trading rule.",
        "",
    ]
    (output_dir / "opportunity_path_report.md").write_text("\n".join(lines), encoding="utf-8")


def write_outputs(
    *,
    labels: pd.DataFrame,
    config: BuildConfig,
    output_dir: Path,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "README.md").write_text(
        "# scanner_opportunity_paths_464/\n\n"
        "Future-path labels for issue #464. Keep compact derived labels and summaries here; "
        "do not store raw parquet, LEAN zip data, or model artifacts.\n",
        encoding="utf-8",
    )
    labels_path = output_dir / "opportunity_path_labels.csv.gz"
    _write_gzip_csv(labels, labels_path)
    source_summary = source_outcome_summary(labels)
    coverage = coverage_summary(labels)
    best, worst = best_worst(labels)
    source_summary.to_csv(output_dir / "source_outcome_summary.csv", index=False)
    coverage.to_csv(output_dir / "coverage_summary.csv", index=False)
    best.to_csv(output_dir / "best_opportunities.csv", index=False)
    worst.to_csv(output_dir / "worst_opportunities.csv", index=False)
    write_report(output_dir=output_dir, labels=labels, source_summary=source_summary, coverage=coverage, config=config)
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "issue": "https://github.com/FALK-BRAUER/kumo-qc/issues/464",
        "config": asdict(config),
        "outputs": {
            "opportunity_path_labels.csv.gz": {"rows": int(len(labels)), "columns": list(labels.columns)},
            "source_outcome_summary.csv": {"rows": int(len(source_summary))},
            "coverage_summary.csv": {"rows": int(len(coverage))},
            "best_opportunities.csv": {"rows": int(len(best))},
            "worst_opportunities.csv": {"rows": int(len(worst))},
            "opportunity_path_report.md": {},
        },
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return {
        "labels": labels_path,
        "source_outcome_summary": output_dir / "source_outcome_summary.csv",
        "coverage_summary": output_dir / "coverage_summary.csv",
        "best_opportunities": output_dir / "best_opportunities.csv",
        "worst_opportunities": output_dir / "worst_opportunities.csv",
        "report": output_dir / "opportunity_path_report.md",
        "manifest": output_dir / "manifest.json",
    }


def run(
    *,
    panel_path: Path = DEFAULT_PANEL,
    parquet_root: Path = DEFAULT_PARQUET_ROOT,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    limit: int | None = None,
) -> dict[str, Path]:
    config = BuildConfig(
        panel=str(panel_path),
        parquet_root=str(parquet_root),
        output_dir=str(output_dir),
        entry_assumption="next_regular_open",
        horizons=HORIZONS,
        target_stop_pairs=TARGET_STOP_PAIRS,
        limit=limit,
    )
    panel = _read_panel(panel_path, limit=limit)
    calendar = parquet_calendar(parquet_root)
    dates = _needed_dates(panel, calendar, max_horizon=max(HORIZONS))
    bars = build_daily_bar_lookup(parquet_root=parquet_root, dates=dates, symbols=set(panel["symbol"]))
    labels = build_labels(panel, calendar=calendar, bars=bars, horizons=HORIZONS)
    return write_outputs(labels=labels, config=config, output_dir=output_dir)


def main() -> None:
    args = _args()
    outputs = run(panel_path=args.panel, parquet_root=args.parquet_root, output_dir=args.output_dir, limit=args.limit)
    for label, path in outputs.items():
        print(f"{label}: {path}")


if __name__ == "__main__":
    main()
