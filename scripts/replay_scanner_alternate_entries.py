"""Replay alternate entry assumptions for scanner opportunities (#465).

This is the second #465 slice: unlike `analyze_scanner_entry_triggers.py`, it changes the
entry price and same-day replay path. It still uses local raw intraday parquet only; QC Cloud
and LEAN integration belong to later issues.
"""
from __future__ import annotations

import argparse
import bisect
import gzip
import io
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import build_scanner_opportunity_path_labels as path_labels  # noqa: E402

DEFAULT_PANEL = ROOT / "sweeps" / "reports" / "scanner_opportunity_panel_463" / "opportunity_panel.csv.gz"
DEFAULT_PARQUET_ROOT = Path("/Users/falk/projects/kumo-trader/data/intraday")
DEFAULT_OUTPUT_DIR = ROOT / "sweeps" / "reports" / "scanner_entry_replay_465"

ENTRY_ASSUMPTIONS = (
    "next_open",
    "first_hour_confirm",
    "prior_session_high_breakout",
    "pullback_1pct_reclaim",
)
DEFAULT_CANDIDATE_FILTER = "kumo_top100_or_george"
CANDIDATE_FILTERS = (
    "all",
    "kumo_top100_or_george",
    "kumo_top20_or_george",
    "george_only",
    "kumo_top100",
    "kumo_top20",
)
UNAVAILABLE_STATUSES = {"no_entry_date", "missing_entry_intraday", "no_entry_trigger"}


@dataclass(frozen=True)
class IntradayBar:
    symbol: str
    day: str
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class EntryReplay:
    assumption: str
    triggered: bool
    status: str
    reason: str
    entry_time: str
    entry_price: float | None
    post_entry_bars: tuple[IntradayBar, ...]


@dataclass(frozen=True)
class ReplayConfig:
    panel: str
    parquet_root: str
    output_dir: str
    candidate_filter: str
    horizons: tuple[int, ...]
    assumptions: tuple[str, ...]
    limit: int | None


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", type=Path, default=DEFAULT_PANEL)
    parser.add_argument("--parquet-root", type=Path, default=DEFAULT_PARQUET_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--candidate-filter", choices=CANDIDATE_FILTERS, default=DEFAULT_CANDIDATE_FILTER)
    parser.add_argument("--limit", type=int, default=None, help="Optional row limit for smoke/debug runs.")
    return parser.parse_args()


def _round(value: float | None) -> float | None:
    if value is None or pd.isna(value):
        return None
    return round(float(value), 4)


def _pct(value: float | None) -> float | None:
    if value is None or pd.isna(value):
        return None
    return round(float(value), 4)


def _synthetic_entry_bar(*, symbol: str, day: str, timestamp: str, entry_price: float) -> IntradayBar:
    return IntradayBar(
        symbol=symbol,
        day=day,
        timestamp=f"{timestamp}|entry",
        open=float(entry_price),
        high=float(entry_price),
        low=float(entry_price),
        close=float(entry_price),
        volume=0.0,
    )


def _partial_daily_bar(*, symbol: str, day: str, bars: Sequence[IntradayBar]) -> path_labels.DailyBar | None:
    if not bars:
        return None
    return path_labels.DailyBar(
        symbol=symbol,
        day=day,
        open=float(bars[0].open),
        high=float(max(bar.high for bar in bars)),
        low=float(min(bar.low for bar in bars)),
        close=float(bars[-1].close),
        volume=float(sum(bar.volume for bar in bars)),
    )


def _no_trigger(assumption: str, status: str, reason: str) -> EntryReplay:
    return EntryReplay(
        assumption=assumption,
        triggered=False,
        status=status,
        reason=reason,
        entry_time="",
        entry_price=None,
        post_entry_bars=(),
    )


def replay_next_open(bars: Sequence[IntradayBar]) -> EntryReplay:
    if not bars:
        return _no_trigger("next_open", "missing_entry_intraday", "no regular-session intraday bars")
    entry = bars[0]
    return EntryReplay(
        assumption="next_open",
        triggered=True,
        status="triggered",
        reason="first regular bar open",
        entry_time=entry.timestamp,
        entry_price=float(entry.open),
        post_entry_bars=tuple(bars),
    )


def replay_first_hour_confirm(bars: Sequence[IntradayBar]) -> EntryReplay:
    if not bars:
        return _no_trigger("first_hour_confirm", "missing_entry_intraday", "no regular-session intraday bars")
    first_hour = [bar for bar in bars if _time_text(bar.timestamp) < "10:30:00"]
    if not first_hour:
        return _no_trigger("first_hour_confirm", "no_entry_trigger", "no first-hour window")
    first_open = float(first_hour[0].open)
    confirm_bar = first_hour[-1]
    entry_price = float(confirm_bar.close)
    if entry_price <= first_open:
        return _no_trigger("first_hour_confirm", "no_entry_trigger", "first-hour close did not confirm above open")
    later_bars = tuple(bar for bar in bars if bar.timestamp > confirm_bar.timestamp)
    synthetic = _synthetic_entry_bar(
        symbol=confirm_bar.symbol,
        day=confirm_bar.day,
        timestamp=confirm_bar.timestamp,
        entry_price=entry_price,
    )
    return EntryReplay(
        assumption="first_hour_confirm",
        triggered=True,
        status="triggered",
        reason="first-hour close above first-hour open",
        entry_time=confirm_bar.timestamp,
        entry_price=entry_price,
        post_entry_bars=(synthetic, *later_bars),
    )


def replay_prior_session_high_breakout(
    bars: Sequence[IntradayBar],
    *,
    prior_session_high: float | None,
) -> EntryReplay:
    if not bars:
        return _no_trigger(
            "prior_session_high_breakout",
            "missing_entry_intraday",
            "no regular-session intraday bars",
        )
    if prior_session_high is None or pd.isna(prior_session_high):
        return _no_trigger("prior_session_high_breakout", "no_entry_trigger", "missing prior-session high")
    for index, bar in enumerate(bars):
        if float(bar.high) >= float(prior_session_high):
            entry_price = max(float(prior_session_high), float(bar.open)) if index == 0 else float(prior_session_high)
            later_bars = tuple(bars[index + 1 :])
            synthetic = _synthetic_entry_bar(
                symbol=bar.symbol,
                day=bar.day,
                timestamp=bar.timestamp,
                entry_price=entry_price,
            )
            return EntryReplay(
                assumption="prior_session_high_breakout",
                triggered=True,
                status="triggered",
                reason="crossed prior-session high",
                entry_time=bar.timestamp,
                entry_price=entry_price,
                post_entry_bars=(synthetic, *later_bars),
            )
    return _no_trigger("prior_session_high_breakout", "no_entry_trigger", "did not cross prior-session high")


def replay_pullback_1pct_reclaim(bars: Sequence[IntradayBar]) -> EntryReplay:
    if not bars:
        return _no_trigger("pullback_1pct_reclaim", "missing_entry_intraday", "no regular-session intraday bars")
    session_open = float(bars[0].open)
    pullback_level = session_open * 0.99
    armed = False
    for index, bar in enumerate(bars[1:], start=1):
        if not armed and float(bar.low) <= pullback_level:
            armed = True
        if armed and float(bar.close) >= session_open:
            entry_price = float(bar.close)
            later_bars = tuple(bars[index + 1 :])
            synthetic = _synthetic_entry_bar(
                symbol=bar.symbol,
                day=bar.day,
                timestamp=bar.timestamp,
                entry_price=entry_price,
            )
            return EntryReplay(
                assumption="pullback_1pct_reclaim",
                triggered=True,
                status="triggered",
                reason="1pct pullback reclaimed session open",
                entry_time=bar.timestamp,
                entry_price=entry_price,
                post_entry_bars=(synthetic, *later_bars),
            )
    return _no_trigger("pullback_1pct_reclaim", "no_entry_trigger", "no 1pct pullback reclaim")


def _time_text(timestamp: str) -> str:
    text = str(timestamp)
    if len(text) >= 19 and text[10] == " ":
        return text[11:19]
    if len(text) >= 8:
        return text[-8:]
    return text


def filter_panel(panel: pd.DataFrame, candidate_filter: str) -> pd.DataFrame:
    rank = pd.to_numeric(panel["kumo_rank_by_score"], errors="coerce")
    george = panel["george_scanner_positive"] | panel["george_watchlist"]
    masks = {
        "all": pd.Series(True, index=panel.index),
        "kumo_top100_or_george": panel["kumo_top_n"] | george,
        "kumo_top20_or_george": rank.le(20) | george,
        "george_only": george,
        "kumo_top100": panel["kumo_top_n"],
        "kumo_top20": rank.le(20),
    }
    return panel[masks[candidate_filter]].copy().reset_index(drop=True)


def build_bar_lookups(
    *,
    parquet_root: Path,
    dates: Sequence[str],
    symbols: set[str],
) -> tuple[dict[tuple[str, str], path_labels.DailyBar], dict[tuple[str, str], tuple[IntradayBar, ...]]]:
    daily: dict[tuple[str, str], path_labels.DailyBar] = {}
    intraday: dict[tuple[str, str], tuple[IntradayBar, ...]] = {}
    for day in dates:
        path = parquet_root / f"{day}.parquet"
        if not path.exists():
            continue
        frame = pd.read_parquet(path, columns=["ticker", "datetime", "open", "high", "low", "close", "volume"])
        frame = frame.rename(columns={"ticker": "symbol"}).copy()
        frame["symbol"] = frame["symbol"].map(path_labels._clean_symbol)
        frame = frame[frame["symbol"].isin(symbols)].copy()
        if frame.empty:
            continue
        time_text = frame["datetime"].astype(str).str.slice(11, 19)
        frame = frame[(time_text >= "09:30:00") & (time_text <= "16:00:00")].copy()
        if frame.empty:
            continue
        frame = frame.sort_values(["symbol", "datetime"])
        for symbol, group in frame.groupby("symbol", sort=False):
            bars = tuple(
                IntradayBar(
                    symbol=str(symbol),
                    day=day,
                    timestamp=str(row.datetime),
                    open=float(row.open),
                    high=float(row.high),
                    low=float(row.low),
                    close=float(row.close),
                    volume=float(row.volume),
                )
                for row in group.itertuples(index=False)
            )
            intraday[(str(symbol), day)] = bars
            partial = _partial_daily_bar(symbol=str(symbol), day=day, bars=bars)
            if partial is not None:
                daily[(str(symbol), day)] = partial
    return daily, intraday


def _entry_context(
    *,
    scan_day: str,
    symbol: str,
    calendar: list[str],
    daily_bars: dict[tuple[str, str], path_labels.DailyBar],
) -> dict[str, Any]:
    entry_idx = bisect.bisect_right(calendar, scan_day)
    if entry_idx >= len(calendar):
        return {"entry_idx": entry_idx, "entry_day": "", "prior_bar": None, "scheduled_days": []}
    max_horizon = max(path_labels.HORIZONS)
    scheduled_days = calendar[entry_idx : min(len(calendar), entry_idx + max_horizon)]
    prior_idx = entry_idx - 1
    prior_bar = daily_bars.get((symbol, calendar[prior_idx])) if prior_idx >= 0 else None
    return {
        "entry_idx": entry_idx,
        "entry_day": scheduled_days[0],
        "prior_bar": prior_bar,
        "scheduled_days": scheduled_days,
    }


def _replay_assumption(
    assumption: str,
    *,
    intraday_bars: Sequence[IntradayBar],
    prior_bar: path_labels.DailyBar | None,
) -> EntryReplay:
    if assumption == "next_open":
        return replay_next_open(intraday_bars)
    if assumption == "first_hour_confirm":
        return replay_first_hour_confirm(intraday_bars)
    if assumption == "prior_session_high_breakout":
        return replay_prior_session_high_breakout(
            intraday_bars,
            prior_session_high=prior_bar.high if prior_bar else None,
        )
    if assumption == "pullback_1pct_reclaim":
        return replay_pullback_1pct_reclaim(intraday_bars)
    raise ValueError(f"Unsupported entry assumption: {assumption}")


def _add_compact_labels(row: dict[str, Any]) -> None:
    if row.get("label_path_status") in UNAVAILABLE_STATUSES:
        row["label_runner_candidate_20d"] = False
        row["label_normal_winner_20d"] = False
        row["label_bad_trade_20d"] = False
        row["label_extreme_path_flag"] = False
        row["label_extreme_path_reason"] = ""
        row["label_outcome_20d"] = "unavailable"
        return
    path_labels.add_compact_labels(row)


def replay_for_opportunity(
    record: dict[str, Any],
    *,
    assumption: str,
    calendar: list[str],
    daily_bars: dict[tuple[str, str], path_labels.DailyBar],
    intraday_bars: dict[tuple[str, str], tuple[IntradayBar, ...]],
    horizons: Sequence[int] = path_labels.HORIZONS,
) -> dict[str, Any]:
    scan_day = str(record["scan_date"])
    symbol = str(record["symbol"])
    context = _entry_context(scan_day=scan_day, symbol=symbol, calendar=calendar, daily_bars=daily_bars)
    base: dict[str, Any] = {
        "scan_date": scan_day,
        "symbol": symbol,
        "entry_assumption": assumption,
        "label_entry_date": context["entry_day"],
        "label_entry_time": "",
        "label_entry_price": None,
        "label_prior_close": _round(context["prior_bar"].close) if context["prior_bar"] else None,
        "label_prior_session_high": _round(context["prior_bar"].high) if context["prior_bar"] else None,
        "label_entry_gap_pct": None,
        "label_triggered": False,
        "label_trigger_status": "",
        "label_trigger_reason": "",
        "label_path_status": "",
        "label_scheduled_40d_sessions": len(context["scheduled_days"]),
        "label_available_40d_sessions": 0,
    }
    if not context["entry_day"]:
        base["label_path_status"] = "no_entry_date"
        base["label_trigger_status"] = "no_entry_date"
        base["label_trigger_reason"] = "scan date has no following parquet calendar day"
        base.update(path_labels._empty_metrics(horizons))
        _add_compact_labels(base)
        return base

    entry_day = str(context["entry_day"])
    day_intraday = intraday_bars.get((symbol, entry_day), ())
    replay = _replay_assumption(assumption, intraday_bars=day_intraday, prior_bar=context["prior_bar"])
    base["label_trigger_status"] = replay.status
    base["label_trigger_reason"] = replay.reason
    base["label_triggered"] = replay.triggered
    base["label_entry_time"] = replay.entry_time
    base["label_entry_price"] = _round(replay.entry_price)
    if replay.entry_price is not None and context["prior_bar"] is not None:
        base["label_entry_gap_pct"] = _pct((float(replay.entry_price) / context["prior_bar"].close - 1.0) * 100.0)

    if not replay.triggered or replay.entry_price is None:
        base["label_path_status"] = replay.status
        if replay.status == "no_entry_trigger":
            base["label_path_status"] = "no_entry_trigger"
        base.update(path_labels._empty_metrics(horizons))
        _add_compact_labels(base)
        return base

    scheduled_days = list(context["scheduled_days"])
    bars_by_day: dict[str, path_labels.DailyBar] = {}
    same_day_partial = _partial_daily_bar(symbol=symbol, day=entry_day, bars=replay.post_entry_bars)
    if same_day_partial is not None:
        bars_by_day[entry_day] = same_day_partial
    for day in scheduled_days[1:]:
        bar = daily_bars.get((symbol, day))
        if bar is not None:
            bars_by_day[day] = bar

    base["label_available_40d_sessions"] = len(bars_by_day)
    max_horizon = max(horizons)
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
            path_labels.horizon_metrics(
                entry_price=float(replay.entry_price),
                scheduled_days=scheduled_days,
                bars_by_day=bars_by_day,
                horizon=horizon,
            )
        )
    _add_compact_labels(base)
    return base


def build_replay_labels(
    panel: pd.DataFrame,
    *,
    calendar: list[str],
    daily_bars: dict[tuple[str, str], path_labels.DailyBar],
    intraday_bars: dict[tuple[str, str], tuple[IntradayBar, ...]],
    assumptions: Sequence[str] = ENTRY_ASSUMPTIONS,
    horizons: Sequence[int] = path_labels.HORIZONS,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    source_columns = [column for column in path_labels.PANEL_SOURCE_COLUMNS if column not in {"scan_date", "symbol"}]
    if panel.empty:
        return pd.DataFrame()
    for record in panel.to_dict("records"):
        for assumption in assumptions:
            row = replay_for_opportunity(
                record,
                assumption=assumption,
                calendar=calendar,
                daily_bars=daily_bars,
                intraday_bars=intraday_bars,
                horizons=horizons,
            )
            row["opportunity_id"] = f"{row['scan_date']}|{row['symbol']}"
            for column in source_columns:
                row[column] = record.get(column)
            rows.append(row)
    label_columns = [column for column in rows[0] if column not in {"scan_date", "symbol", *source_columns}]
    ordered = ["scan_date", "symbol", *source_columns, *label_columns]
    return pd.DataFrame(rows).loc[:, ordered]


def _summary_pct(mask: pd.Series) -> float:
    if len(mask) == 0:
        return 0.0
    return round(100.0 * float(mask.mean()), 3)


def _summary_mean(series: pd.Series) -> float | None:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        return None
    return round(float(values.mean()), 4)


def _summary_median(series: pd.Series) -> float | None:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        return None
    return round(float(values.median()), 4)


def _assumption_summary_rows(labels: pd.DataFrame, *, group_columns: Sequence[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for group_values, subset in labels.groupby(list(group_columns), dropna=False):
        if not isinstance(group_values, tuple):
            group_values = (group_values,)
        available = subset[subset["label_ret_20d_close_pct"].notna()].copy()
        row = {column: value for column, value in zip(group_columns, group_values)}
        row.update(
            {
                "candidate_rows": int(len(subset)),
                "triggered_rows": int(subset["label_triggered"].sum()),
                "trigger_rate_pct": _summary_pct(subset["label_triggered"]),
                "available_20d_rows": int(len(available)),
                "avg_ret_20d_close_pct": _summary_mean(available["label_ret_20d_close_pct"]),
                "candidate_weighted_avg_ret_20d_pct": _summary_mean(
                    pd.to_numeric(subset["label_ret_20d_close_pct"], errors="coerce").fillna(0.0)
                ),
                "median_ret_20d_close_pct": _summary_median(available["label_ret_20d_close_pct"]),
                "runner_pct": _summary_pct(available["label_runner_candidate_20d"]),
                "normal_winner_pct": _summary_pct(available["label_normal_winner_20d"]),
                "bad_trade_pct": _summary_pct(available["label_bad_trade_20d"]),
                "target4_before_stop2_pct": _summary_pct(
                    available["label_t4_s2_20d_outcome"].eq("target_before_stop")
                ),
                "stop2_before_target4_pct": _summary_pct(
                    available["label_t4_s2_20d_outcome"].eq("stop_before_target")
                ),
                "avg_mfe_20d_pct": _summary_mean(available["label_mfe_20d_pct"]),
                "avg_mae_20d_pct": _summary_mean(available["label_mae_20d_pct"]),
            }
        )
        rows.append(row)
    return rows


def entry_assumption_summary(labels: pd.DataFrame) -> pd.DataFrame:
    rows = _assumption_summary_rows(labels, group_columns=["entry_assumption"])
    return pd.DataFrame(rows).sort_values("avg_ret_20d_close_pct", ascending=False).reset_index(drop=True)


def source_assumption_summary(labels: pd.DataFrame) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    source_masks = {
        "kumo_top100": labels["kumo_top_n"],
        "kumo_scanner": labels["kumo_scanner"],
        "george_scanner_or_watchlist": labels["george_scanner_positive"] | labels["george_watchlist"],
    }
    for source_flag, mask in source_masks.items():
        subset = labels[mask].copy()
        rows = _assumption_summary_rows(subset, group_columns=["entry_assumption"])
        source_frame = pd.DataFrame(rows)
        if not source_frame.empty:
            source_frame.insert(0, "source_flag", source_flag)
            frames.append(source_frame)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).sort_values(
        ["source_flag", "avg_ret_20d_close_pct"],
        ascending=[True, False],
    )


def trigger_failure_summary(labels: pd.DataFrame) -> pd.DataFrame:
    failures = labels[~labels["label_triggered"]].copy()
    if failures.empty:
        return pd.DataFrame(columns=["entry_assumption", "label_trigger_status", "label_trigger_reason", "rows"])
    return (
        failures.groupby(["entry_assumption", "label_trigger_status", "label_trigger_reason"], dropna=False)
        .agg(rows=("symbol", "size"))
        .reset_index()
        .sort_values(["entry_assumption", "rows"], ascending=[True, False])
        .reset_index(drop=True)
    )


def best_worst(labels: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    columns = [
        "scan_date",
        "symbol",
        "entry_assumption",
        "source_tags",
        "kumo_rank_by_score",
        "kumo_score",
        "label_entry_date",
        "label_entry_time",
        "label_entry_price",
        "label_outcome_20d",
        "label_ret_20d_close_pct",
        "label_mfe_20d_pct",
        "label_mae_20d_pct",
        "label_t4_s2_20d_outcome",
        "label_trigger_reason",
    ]
    available = labels[labels["label_ret_20d_close_pct"].notna()].copy()
    best = available.sort_values(["label_ret_20d_close_pct", "label_mfe_20d_pct"], ascending=[False, False]).head(50)
    worst = available.sort_values(["label_ret_20d_close_pct", "label_mae_20d_pct"], ascending=[True, True]).head(50)
    return best.loc[:, columns], worst.loc[:, columns]


def _write_gzip_csv(frame: pd.DataFrame, path: Path) -> None:
    with path.open("wb") as raw_fh:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw_fh, mtime=0) as gzip_fh:
            with io.TextIOWrapper(gzip_fh, encoding="utf-8", newline="") as text_fh:
                frame.to_csv(text_fh, index=False)


def _markdown_table(frame: pd.DataFrame, columns: list[str], *, limit: int | None = None) -> str:
    if frame.empty:
        return "_No rows._"
    subset = frame.loc[:, columns]
    if limit is not None:
        subset = subset.head(limit)
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
    assumption_summary: pd.DataFrame,
    source_summary: pd.DataFrame,
    failures: pd.DataFrame,
    config: ReplayConfig,
) -> None:
    best = assumption_summary.iloc[0]
    lines = [
        "# Scanner Alternate Entry Replay #465",
        "",
        "This report replays scanner opportunities with changed entry prices and post-entry paths.",
        "It is still a research harness, not a LEAN/QC deployment artifact.",
        "",
        "## Inputs",
        "",
        f"- Panel: `{config.panel}`",
        f"- Parquet root: `{config.parquet_root}`",
        f"- Candidate filter: `{config.candidate_filter}`",
        "",
        "## Read",
        "",
        f"- Replayed candidate rows: `{labels['opportunity_id'].nunique()}` opportunities x "
        f"`{labels['entry_assumption'].nunique()}` assumptions = `{len(labels)}` rows.",
        f"- Best replay assumption by average 20d close return: `{best['entry_assumption']}`.",
        "- Delayed entries use only post-entry same-day bars; first-hour and pullback entries are",
        "  entered at the trigger bar close, while breakout uses a prior-session-high stop proxy.",
        "- No-entry rows are kept in trigger-rate statistics but excluded from return percentages.",
        "",
        "## Entry Assumption Summary",
        "",
        _markdown_table(
            assumption_summary,
            [
                "entry_assumption",
                "candidate_rows",
                "triggered_rows",
                "trigger_rate_pct",
                "available_20d_rows",
                "avg_ret_20d_close_pct",
                "candidate_weighted_avg_ret_20d_pct",
                "median_ret_20d_close_pct",
                "runner_pct",
                "bad_trade_pct",
                "target4_before_stop2_pct",
                "stop2_before_target4_pct",
            ],
        ),
        "",
        "## Source Summary",
        "",
        _markdown_table(
            source_summary,
            [
                "source_flag",
                "entry_assumption",
                "candidate_rows",
                "triggered_rows",
                "trigger_rate_pct",
                "avg_ret_20d_close_pct",
                "candidate_weighted_avg_ret_20d_pct",
                "runner_pct",
                "bad_trade_pct",
            ],
        ),
        "",
        "## Trigger Failures",
        "",
        _markdown_table(
            failures,
            ["entry_assumption", "label_trigger_status", "label_trigger_reason", "rows"],
            limit=20,
        ),
        "",
        "## Caveats",
        "",
        "- Intrabar event ordering is unknown. Delayed triggers avoid counting pre-entry same-day bars.",
        "- This pass uses the practical `kumo_top100_or_george` default subset unless configured",
        "  otherwise; it is not a full 313k-row all-panel replay by default.",
        "- Breakout is approximated as a prior-session-high stop entry, not full Ichimoku/cloud logic.",
        "",
    ]
    (output_dir / "entry_replay_report.md").write_text("\n".join(lines), encoding="utf-8")


def write_outputs(
    *,
    labels: pd.DataFrame,
    config: ReplayConfig,
    output_dir: Path,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "README.md").write_text(
        "# scanner_entry_replay_465/\n\n"
        "Alternate entry replay outputs for issue #465. Keep compact derived labels, summaries, "
        "and examples here; do not store raw parquet data, model artifacts, or bulky LEAN runs.\n",
        encoding="utf-8",
    )
    labels_path = output_dir / "alternate_entry_labels.csv.gz"
    _write_gzip_csv(labels, labels_path)
    assumption_summary = entry_assumption_summary(labels)
    source_summary = source_assumption_summary(labels)
    failures = trigger_failure_summary(labels)
    best, worst = best_worst(labels)
    assumption_summary.to_csv(output_dir / "entry_assumption_summary.csv", index=False)
    source_summary.to_csv(output_dir / "source_entry_assumption_summary.csv", index=False)
    failures.to_csv(output_dir / "trigger_failure_summary.csv", index=False)
    best.to_csv(output_dir / "best_alternate_entries.csv", index=False)
    worst.to_csv(output_dir / "worst_alternate_entries.csv", index=False)
    write_report(
        output_dir=output_dir,
        labels=labels,
        assumption_summary=assumption_summary,
        source_summary=source_summary,
        failures=failures,
        config=config,
    )
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "issue": "https://github.com/FALK-BRAUER/kumo-qc/issues/465",
        "config": asdict(config),
        "outputs": {
            "alternate_entry_labels.csv.gz": {"rows": int(len(labels)), "columns": list(labels.columns)},
            "entry_assumption_summary.csv": {"rows": int(len(assumption_summary))},
            "source_entry_assumption_summary.csv": {"rows": int(len(source_summary))},
            "trigger_failure_summary.csv": {"rows": int(len(failures))},
            "best_alternate_entries.csv": {"rows": int(len(best))},
            "worst_alternate_entries.csv": {"rows": int(len(worst))},
            "entry_replay_report.md": {},
        },
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return {
        "labels": labels_path,
        "entry_assumption_summary": output_dir / "entry_assumption_summary.csv",
        "source_entry_assumption_summary": output_dir / "source_entry_assumption_summary.csv",
        "trigger_failure_summary": output_dir / "trigger_failure_summary.csv",
        "best_examples": output_dir / "best_alternate_entries.csv",
        "worst_examples": output_dir / "worst_alternate_entries.csv",
        "report": output_dir / "entry_replay_report.md",
        "manifest": output_dir / "manifest.json",
    }


def run(
    *,
    panel_path: Path = DEFAULT_PANEL,
    parquet_root: Path = DEFAULT_PARQUET_ROOT,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    candidate_filter: str = DEFAULT_CANDIDATE_FILTER,
    limit: int | None = None,
) -> dict[str, Path]:
    config = ReplayConfig(
        panel=str(panel_path),
        parquet_root=str(parquet_root),
        output_dir=str(output_dir),
        candidate_filter=candidate_filter,
        horizons=tuple(path_labels.HORIZONS),
        assumptions=tuple(ENTRY_ASSUMPTIONS),
        limit=limit,
    )
    panel = path_labels._read_panel(panel_path, limit=None)
    panel = filter_panel(panel, candidate_filter)
    if limit is not None:
        panel = panel.head(limit).copy()
    calendar = path_labels.parquet_calendar(parquet_root)
    dates = path_labels._needed_dates(panel, calendar, max_horizon=max(path_labels.HORIZONS))
    symbols = set(panel["symbol"].astype(str))
    daily_bars, intraday_bars = build_bar_lookups(parquet_root=parquet_root, dates=dates, symbols=symbols)
    labels = build_replay_labels(panel, calendar=calendar, daily_bars=daily_bars, intraday_bars=intraday_bars)
    return write_outputs(labels=labels, config=config, output_dir=output_dir)


def main() -> None:
    args = _args()
    outputs = run(
        panel_path=args.panel,
        parquet_root=args.parquet_root,
        output_dir=args.output_dir,
        candidate_filter=args.candidate_filter,
        limit=args.limit,
    )
    for label, path in outputs.items():
        print(f"{label}: {path}")


if __name__ == "__main__":
    main()
