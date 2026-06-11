"""Analyze scanner opportunity exit and profit-realization policies (#466)."""
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

DEFAULT_LABELS = ROOT / "sweeps" / "reports" / "scanner_opportunity_paths_464" / "opportunity_path_labels.csv.gz"
DEFAULT_PANEL = ROOT / "sweeps" / "reports" / "scanner_opportunity_panel_463" / "opportunity_panel.csv.gz"
DEFAULT_PARQUET_ROOT = Path("/Users/falk/projects/kumo-trader/data/intraday")
DEFAULT_OUTPUT_DIR = ROOT / "sweeps" / "reports" / "scanner_exit_policies_466"
DEFAULT_CANDIDATE_FILTER = "kumo_top100_or_george"
MAX_HORIZON = 40

CANDIDATE_FILTERS = (
    "all",
    "kumo_top100_or_george",
    "kumo_top20_or_george",
    "george_only",
    "kumo_top100",
    "kumo_top20",
)

BOOL_COLUMNS = [
    "kumo_scanner",
    "kumo_top_n",
    "george_scanner_positive",
    "george_watchlist",
    "george_video_mention",
    "label_runner_candidate_20d",
    "label_normal_winner_20d",
    "label_bad_trade_20d",
    "label_extreme_path_flag",
]

LABEL_COLUMNS = [
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
    "label_entry_date",
    "label_entry_price",
    "label_path_status",
    "label_ret_20d_close_pct",
    "label_mfe_20d_pct",
    "label_mae_20d_pct",
    "label_ret_40d_close_pct",
    "label_mfe_40d_pct",
    "label_mae_40d_pct",
    "label_runner_candidate_20d",
    "label_normal_winner_20d",
    "label_bad_trade_20d",
    "label_extreme_path_flag",
    "label_outcome_20d",
]

PANEL_METADATA_COLUMNS = [
    "scan_date",
    "symbol",
    "company_sector",
    "company_industry",
    "sector_category",
    "sector_etf_proxy",
]


@dataclass(frozen=True)
class PolicySpec:
    policy_id: str
    description: str
    deployability: str


@dataclass(frozen=True)
class PolicyResult:
    policy_id: str
    policy_status: str
    exit_reason: str
    exit_day: str
    exit_session: int | None
    realized_ret_pct: float
    open_mtm_ret_40d_pct: float
    total_equity_ret_40d_pct: float | None
    open_fraction_40d: float
    closed_fraction_40d: float
    exposure_sessions: int
    peak_equity_ret_pct: float | None
    max_drawdown_ret_pct: float | None
    giveback_from_peak_pct: float | None
    partial_taken: bool
    ambiguous_same_day: bool


@dataclass(frozen=True)
class ExitConfig:
    labels: str
    panel: str
    parquet_root: str
    output_dir: str
    candidate_filter: str
    max_horizon: int
    limit: int | None


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--panel", type=Path, default=DEFAULT_PANEL)
    parser.add_argument("--parquet-root", type=Path, default=DEFAULT_PARQUET_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--candidate-filter", choices=CANDIDATE_FILTERS, default=DEFAULT_CANDIDATE_FILTER)
    parser.add_argument("--limit", type=int, default=None, help="Optional row limit after filtering.")
    return parser.parse_args()


def policy_catalog() -> list[PolicySpec]:
    return [
        PolicySpec("hold_40d_mtm", "Hold to 40-session mark-to-market.", "research_baseline"),
        PolicySpec("fixed_t4_s2", "Full exit at +4% target or -2% stop.", "lean_and_qc_ready"),
        PolicySpec("fixed_t8_s4", "Full exit at +8% target or -4% stop.", "lean_and_qc_ready"),
        PolicySpec(
            "partial_t4_trail8",
            "Sell 50% at +4%, then trail the remainder 8% below peak with a -4% hard stop.",
            "lean_and_qc_ready",
        ),
        PolicySpec(
            "giveback35_after8",
            "Hard stop -6%; after +8% peak, exit on 35% giveback from peak gain.",
            "lean_and_qc_ready",
        ),
        PolicySpec(
            "swinglow3_after8",
            "Hard stop -6%; after +8% peak, exit on break of prior 3-session swing low.",
            "lean_and_qc_ready",
        ),
        PolicySpec(
            "time10_lt2_hard6",
            "Hard stop -6%; exit on session 10 close if return is below +2%.",
            "lean_and_qc_ready",
        ),
        PolicySpec(
            "sector_etf_weak3d",
            "Hard stop -6%; exit at close when sector ETF loses at least 3% over 3 sessions.",
            "lean_and_qc_ready_if_sector_proxy_available",
        ),
    ]


def _bool_series(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip().str.lower().isin({"1", "true", "yes", "y"})


def _parse_day(value: Any) -> str:
    return path_labels._parse_day(value)


def _clean_symbol(value: Any) -> str:
    return path_labels._clean_symbol(value)


def _round(value: float | None, digits: int = 4) -> float | None:
    if value is None or pd.isna(value):
        return None
    return round(float(value), digits)


def _ret_pct(price: float, entry_price: float) -> float:
    return (float(price) / float(entry_price) - 1.0) * 100.0


def read_labels(labels_path: Path, panel_path: Path, *, candidate_filter: str, limit: int | None) -> pd.DataFrame:
    if not labels_path.exists():
        raise FileNotFoundError(labels_path)
    if not panel_path.exists():
        raise FileNotFoundError(panel_path)

    labels = pd.read_csv(labels_path, usecols=lambda column: column in set(LABEL_COLUMNS), low_memory=False)
    labels["scan_date"] = labels["scan_date"].map(_parse_day)
    labels["symbol"] = labels["symbol"].map(_clean_symbol)
    for column in BOOL_COLUMNS:
        labels[column] = _bool_series(labels[column])

    panel = pd.read_csv(panel_path, usecols=lambda column: column in set(PANEL_METADATA_COLUMNS), low_memory=False)
    panel["scan_date"] = panel["scan_date"].map(_parse_day)
    panel["symbol"] = panel["symbol"].map(_clean_symbol)
    panel = panel.drop_duplicates(["scan_date", "symbol"], keep="first")
    labels = labels.merge(panel, on=["scan_date", "symbol"], how="left")
    labels["sector_etf_proxy"] = labels["sector_etf_proxy"].map(_clean_symbol)

    labels = labels[labels["label_path_status"].astype(str).str.startswith("available")].copy()
    labels = filter_candidates(labels, candidate_filter)
    if limit is not None:
        labels = labels.head(limit).copy()
    labels["opportunity_id"] = labels["scan_date"] + "|" + labels["symbol"]
    labels["true_runner_40d"] = (
        labels["label_runner_candidate_20d"]
        | pd.to_numeric(labels["label_mfe_40d_pct"], errors="coerce").ge(25.0)
        | pd.to_numeric(labels["label_ret_40d_close_pct"], errors="coerce").ge(15.0)
    )
    return labels.reset_index(drop=True)


def filter_candidates(frame: pd.DataFrame, candidate_filter: str) -> pd.DataFrame:
    rank = pd.to_numeric(frame["kumo_rank_by_score"], errors="coerce")
    george = frame["george_scanner_positive"] | frame["george_watchlist"]
    masks = {
        "all": pd.Series(True, index=frame.index),
        "kumo_top100_or_george": frame["kumo_top_n"] | george,
        "kumo_top20_or_george": rank.le(20) | george,
        "george_only": george,
        "kumo_top100": frame["kumo_top_n"],
        "kumo_top20": rank.le(20),
    }
    return frame[masks[candidate_filter]].copy()


def needed_dates(labels: pd.DataFrame, calendar: list[str], *, max_horizon: int) -> list[str]:
    needed: set[str] = set()
    for scan_day in sorted(labels["scan_date"].unique()):
        entry_idx = bisect.bisect_right(calendar, scan_day)
        for day in calendar[entry_idx : min(len(calendar), entry_idx + max_horizon)]:
            needed.add(day)
    return sorted(needed)


def _bars_for_record(
    record: dict[str, Any],
    *,
    calendar: list[str],
    bars: dict[tuple[str, str], path_labels.DailyBar],
    max_horizon: int,
) -> tuple[list[path_labels.DailyBar], list[str]]:
    symbol = str(record["symbol"])
    scan_day = str(record["scan_date"])
    entry_idx = bisect.bisect_right(calendar, scan_day)
    scheduled_days = calendar[entry_idx : min(len(calendar), entry_idx + max_horizon)]
    return [bars[(symbol, day)] for day in scheduled_days if (symbol, day) in bars], scheduled_days


def _etf_bars_for_record(
    record: dict[str, Any],
    *,
    scheduled_days: Sequence[str],
    bars: dict[tuple[str, str], path_labels.DailyBar],
) -> list[path_labels.DailyBar]:
    etf = _clean_symbol(record.get("sector_etf_proxy"))
    if not etf:
        return []
    return [bars[(etf, day)] for day in scheduled_days if (etf, day) in bars]


def _result(
    *,
    policy_id: str,
    policy_status: str,
    exit_reason: str,
    exit_day: str = "",
    exit_session: int | None = None,
    realized_ret_pct: float = 0.0,
    open_mtm_ret_40d_pct: float = 0.0,
    total_equity_ret_40d_pct: float | None = None,
    open_fraction_40d: float = 0.0,
    closed_fraction_40d: float = 0.0,
    exposure_sessions: int = 0,
    peak_equity_ret_pct: float | None = None,
    max_drawdown_ret_pct: float | None = None,
    partial_taken: bool = False,
    ambiguous_same_day: bool = False,
) -> PolicyResult:
    giveback = None
    if peak_equity_ret_pct is not None and total_equity_ret_40d_pct is not None:
        giveback = max(0.0, peak_equity_ret_pct - total_equity_ret_40d_pct)
    return PolicyResult(
        policy_id=policy_id,
        policy_status=policy_status,
        exit_reason=exit_reason,
        exit_day=exit_day,
        exit_session=exit_session,
        realized_ret_pct=round(realized_ret_pct, 4),
        open_mtm_ret_40d_pct=round(open_mtm_ret_40d_pct, 4),
        total_equity_ret_40d_pct=_round(total_equity_ret_40d_pct),
        open_fraction_40d=round(open_fraction_40d, 4),
        closed_fraction_40d=round(closed_fraction_40d, 4),
        exposure_sessions=exposure_sessions,
        peak_equity_ret_pct=_round(peak_equity_ret_pct),
        max_drawdown_ret_pct=_round(max_drawdown_ret_pct),
        giveback_from_peak_pct=_round(giveback),
        partial_taken=partial_taken,
        ambiguous_same_day=ambiguous_same_day,
    )


def _finish_open(
    *,
    policy_id: str,
    entry_price: float,
    bars: Sequence[path_labels.DailyBar],
    realized: float,
    remaining: float,
    peak: float | None,
    drawdown: float | None,
    partial_taken: bool = False,
    ambiguous: bool = False,
) -> PolicyResult:
    if not bars:
        return _result(policy_id=policy_id, policy_status="unavailable", exit_reason="missing_bars")
    final_ret = _ret_pct(bars[-1].close, entry_price)
    open_mtm = remaining * final_ret
    total = realized + open_mtm
    return _result(
        policy_id=policy_id,
        policy_status="open_at_horizon" if remaining > 0 else "closed",
        exit_reason="horizon_mtm" if remaining > 0 else "policy_exit",
        exit_day="" if remaining > 0 else bars[-1].day,
        exit_session=None if remaining > 0 else len(bars),
        realized_ret_pct=realized,
        open_mtm_ret_40d_pct=open_mtm,
        total_equity_ret_40d_pct=total,
        open_fraction_40d=remaining,
        closed_fraction_40d=1.0 - remaining,
        exposure_sessions=len(bars),
        peak_equity_ret_pct=peak,
        max_drawdown_ret_pct=drawdown,
        partial_taken=partial_taken,
        ambiguous_same_day=ambiguous,
    )


def _mark_path_extremes(
    *,
    entry_price: float,
    bar: path_labels.DailyBar,
    realized: float,
    remaining: float,
    peak: float | None,
    drawdown: float | None,
) -> tuple[float, float]:
    high_equity = realized + remaining * _ret_pct(bar.high, entry_price)
    low_equity = realized + remaining * _ret_pct(bar.low, entry_price)
    return (
        high_equity if peak is None else max(peak, high_equity),
        low_equity if drawdown is None else min(drawdown, low_equity),
    )


def simulate_hold(entry_price: float, bars: Sequence[path_labels.DailyBar]) -> PolicyResult:
    peak = None
    drawdown = None
    for bar in bars:
        peak, drawdown = _mark_path_extremes(
            entry_price=entry_price,
            bar=bar,
            realized=0.0,
            remaining=1.0,
            peak=peak,
            drawdown=drawdown,
        )
    return _finish_open(
        policy_id="hold_40d_mtm",
        entry_price=entry_price,
        bars=bars,
        realized=0.0,
        remaining=1.0,
        peak=peak,
        drawdown=drawdown,
    )


def simulate_fixed_target_stop(
    *,
    policy_id: str,
    entry_price: float,
    bars: Sequence[path_labels.DailyBar],
    target_pct: float,
    stop_pct: float,
) -> PolicyResult:
    peak = None
    drawdown = None
    target_price = entry_price * (1.0 + target_pct / 100.0)
    stop_price = entry_price * (1.0 - stop_pct / 100.0)
    for session, bar in enumerate(bars, start=1):
        peak, drawdown = _mark_path_extremes(
            entry_price=entry_price,
            bar=bar,
            realized=0.0,
            remaining=1.0,
            peak=peak,
            drawdown=drawdown,
        )
        hit_stop = bar.low <= stop_price
        hit_target = bar.high >= target_price
        if hit_stop or hit_target:
            ambiguous = hit_stop and hit_target
            exit_price = stop_price if hit_stop else target_price
            ret = _ret_pct(exit_price, entry_price)
            return _result(
                policy_id=policy_id,
                policy_status="closed",
                exit_reason="ambiguous_stop_first" if ambiguous else ("stop" if hit_stop else "target"),
                exit_day=bar.day,
                exit_session=session,
                realized_ret_pct=ret,
                total_equity_ret_40d_pct=ret,
                closed_fraction_40d=1.0,
                exposure_sessions=session,
                peak_equity_ret_pct=peak,
                max_drawdown_ret_pct=drawdown,
                ambiguous_same_day=ambiguous,
            )
    return _finish_open(
        policy_id=policy_id,
        entry_price=entry_price,
        bars=bars,
        realized=0.0,
        remaining=1.0,
        peak=peak,
        drawdown=drawdown,
    )


def simulate_partial_target_trail(
    *,
    entry_price: float,
    bars: Sequence[path_labels.DailyBar],
    target_pct: float = 4.0,
    stop_pct: float = 4.0,
    trail_pct: float = 8.0,
    partial_fraction: float = 0.5,
) -> PolicyResult:
    policy_id = "partial_t4_trail8"
    peak = None
    drawdown = None
    realized = 0.0
    remaining = 1.0
    partial_taken = False
    peak_price = entry_price
    target_price = entry_price * (1.0 + target_pct / 100.0)
    hard_stop = entry_price * (1.0 - stop_pct / 100.0)
    ambiguous = False

    for session, bar in enumerate(bars, start=1):
        peak, drawdown = _mark_path_extremes(
            entry_price=entry_price,
            bar=bar,
            realized=realized,
            remaining=remaining,
            peak=peak,
            drawdown=drawdown,
        )
        if remaining <= 0:
            break
        if not partial_taken and bar.low <= hard_stop:
            exit_ret = _ret_pct(hard_stop, entry_price)
            ambiguous = bar.high >= target_price
            total = realized + remaining * exit_ret
            return _result(
                policy_id=policy_id,
                policy_status="closed",
                exit_reason="ambiguous_stop_first" if ambiguous else "hard_stop",
                exit_day=bar.day,
                exit_session=session,
                realized_ret_pct=total,
                total_equity_ret_40d_pct=total,
                closed_fraction_40d=1.0,
                exposure_sessions=session,
                peak_equity_ret_pct=peak,
                max_drawdown_ret_pct=drawdown,
                partial_taken=partial_taken,
                ambiguous_same_day=ambiguous,
            )
        if partial_taken:
            trail_stop = peak_price * (1.0 - trail_pct / 100.0)
            if bar.low <= trail_stop:
                exit_ret = _ret_pct(trail_stop, entry_price)
                realized += remaining * exit_ret
                remaining = 0.0
                return _result(
                    policy_id=policy_id,
                    policy_status="closed",
                    exit_reason="trail_stop",
                    exit_day=bar.day,
                    exit_session=session,
                    realized_ret_pct=realized,
                    total_equity_ret_40d_pct=realized,
                    closed_fraction_40d=1.0,
                    exposure_sessions=session,
                    peak_equity_ret_pct=peak,
                    max_drawdown_ret_pct=drawdown,
                    partial_taken=partial_taken,
                    ambiguous_same_day=ambiguous,
                )
        if not partial_taken and bar.high >= target_price:
            realized += partial_fraction * _ret_pct(target_price, entry_price)
            remaining -= partial_fraction
            partial_taken = True
        peak_price = max(peak_price, bar.high)

    return _finish_open(
        policy_id=policy_id,
        entry_price=entry_price,
        bars=bars,
        realized=realized,
        remaining=remaining,
        peak=peak,
        drawdown=drawdown,
        partial_taken=partial_taken,
        ambiguous=ambiguous,
    )


def simulate_giveback_after_peak(
    *,
    entry_price: float,
    bars: Sequence[path_labels.DailyBar],
    arm_pct: float = 8.0,
    giveback_fraction: float = 0.35,
    hard_stop_pct: float = 6.0,
) -> PolicyResult:
    policy_id = "giveback35_after8"
    peak = None
    drawdown = None
    peak_price = entry_price
    hard_stop = entry_price * (1.0 - hard_stop_pct / 100.0)

    for session, bar in enumerate(bars, start=1):
        armed = _ret_pct(peak_price, entry_price) >= arm_pct
        if armed:
            peak_gain = peak_price - entry_price
            stop_level = entry_price + peak_gain * (1.0 - giveback_fraction)
            if bar.low <= stop_level:
                ret = _ret_pct(stop_level, entry_price)
                peak, drawdown = _mark_path_extremes(
                    entry_price=entry_price,
                    bar=bar,
                    realized=0.0,
                    remaining=1.0,
                    peak=peak,
                    drawdown=drawdown,
                )
                return _result(
                    policy_id=policy_id,
                    policy_status="closed",
                    exit_reason="giveback_stop",
                    exit_day=bar.day,
                    exit_session=session,
                    realized_ret_pct=ret,
                    total_equity_ret_40d_pct=ret,
                    closed_fraction_40d=1.0,
                    exposure_sessions=session,
                    peak_equity_ret_pct=peak,
                    max_drawdown_ret_pct=drawdown,
                )
        elif bar.low <= hard_stop:
            ret = _ret_pct(hard_stop, entry_price)
            peak, drawdown = _mark_path_extremes(
                entry_price=entry_price,
                bar=bar,
                realized=0.0,
                remaining=1.0,
                peak=peak,
                drawdown=drawdown,
            )
            return _result(
                policy_id=policy_id,
                policy_status="closed",
                exit_reason="hard_stop",
                exit_day=bar.day,
                exit_session=session,
                realized_ret_pct=ret,
                total_equity_ret_40d_pct=ret,
                closed_fraction_40d=1.0,
                exposure_sessions=session,
                peak_equity_ret_pct=peak,
                max_drawdown_ret_pct=drawdown,
            )

        peak, drawdown = _mark_path_extremes(
            entry_price=entry_price,
            bar=bar,
            realized=0.0,
            remaining=1.0,
            peak=peak,
            drawdown=drawdown,
        )
        peak_price = max(peak_price, bar.high)

    return _finish_open(
        policy_id=policy_id,
        entry_price=entry_price,
        bars=bars,
        realized=0.0,
        remaining=1.0,
        peak=peak,
        drawdown=drawdown,
    )


def simulate_swinglow_trail(
    *,
    entry_price: float,
    bars: Sequence[path_labels.DailyBar],
    arm_pct: float = 8.0,
    hard_stop_pct: float = 6.0,
    lookback: int = 3,
) -> PolicyResult:
    policy_id = "swinglow3_after8"
    peak = None
    drawdown = None
    peak_price = entry_price
    prior_lows: list[float] = []
    hard_stop = entry_price * (1.0 - hard_stop_pct / 100.0)

    for session, bar in enumerate(bars, start=1):
        armed = _ret_pct(peak_price, entry_price) >= arm_pct and len(prior_lows) >= lookback
        if armed:
            stop_level = min(prior_lows[-lookback:])
            if bar.low <= stop_level:
                ret = _ret_pct(stop_level, entry_price)
                peak, drawdown = _mark_path_extremes(
                    entry_price=entry_price,
                    bar=bar,
                    realized=0.0,
                    remaining=1.0,
                    peak=peak,
                    drawdown=drawdown,
                )
                return _result(
                    policy_id=policy_id,
                    policy_status="closed",
                    exit_reason="swing_low_break",
                    exit_day=bar.day,
                    exit_session=session,
                    realized_ret_pct=ret,
                    total_equity_ret_40d_pct=ret,
                    closed_fraction_40d=1.0,
                    exposure_sessions=session,
                    peak_equity_ret_pct=peak,
                    max_drawdown_ret_pct=drawdown,
                )
        elif bar.low <= hard_stop:
            ret = _ret_pct(hard_stop, entry_price)
            peak, drawdown = _mark_path_extremes(
                entry_price=entry_price,
                bar=bar,
                realized=0.0,
                remaining=1.0,
                peak=peak,
                drawdown=drawdown,
            )
            return _result(
                policy_id=policy_id,
                policy_status="closed",
                exit_reason="hard_stop",
                exit_day=bar.day,
                exit_session=session,
                realized_ret_pct=ret,
                total_equity_ret_40d_pct=ret,
                closed_fraction_40d=1.0,
                exposure_sessions=session,
                peak_equity_ret_pct=peak,
                max_drawdown_ret_pct=drawdown,
            )

        peak, drawdown = _mark_path_extremes(
            entry_price=entry_price,
            bar=bar,
            realized=0.0,
            remaining=1.0,
            peak=peak,
            drawdown=drawdown,
        )
        peak_price = max(peak_price, bar.high)
        prior_lows.append(bar.low)

    return _finish_open(
        policy_id=policy_id,
        entry_price=entry_price,
        bars=bars,
        realized=0.0,
        remaining=1.0,
        peak=peak,
        drawdown=drawdown,
    )


def simulate_time_stop(
    *,
    entry_price: float,
    bars: Sequence[path_labels.DailyBar],
    session_stop: int = 10,
    min_return_pct: float = 2.0,
    hard_stop_pct: float = 6.0,
) -> PolicyResult:
    policy_id = "time10_lt2_hard6"
    peak = None
    drawdown = None
    hard_stop = entry_price * (1.0 - hard_stop_pct / 100.0)
    for session, bar in enumerate(bars, start=1):
        peak, drawdown = _mark_path_extremes(
            entry_price=entry_price,
            bar=bar,
            realized=0.0,
            remaining=1.0,
            peak=peak,
            drawdown=drawdown,
        )
        if bar.low <= hard_stop:
            ret = _ret_pct(hard_stop, entry_price)
            return _result(
                policy_id=policy_id,
                policy_status="closed",
                exit_reason="hard_stop",
                exit_day=bar.day,
                exit_session=session,
                realized_ret_pct=ret,
                total_equity_ret_40d_pct=ret,
                closed_fraction_40d=1.0,
                exposure_sessions=session,
                peak_equity_ret_pct=peak,
                max_drawdown_ret_pct=drawdown,
            )
        if session == session_stop and _ret_pct(bar.close, entry_price) < min_return_pct:
            ret = _ret_pct(bar.close, entry_price)
            return _result(
                policy_id=policy_id,
                policy_status="closed",
                exit_reason="time_stop_under_threshold",
                exit_day=bar.day,
                exit_session=session,
                realized_ret_pct=ret,
                total_equity_ret_40d_pct=ret,
                closed_fraction_40d=1.0,
                exposure_sessions=session,
                peak_equity_ret_pct=peak,
                max_drawdown_ret_pct=drawdown,
            )
    return _finish_open(
        policy_id=policy_id,
        entry_price=entry_price,
        bars=bars,
        realized=0.0,
        remaining=1.0,
        peak=peak,
        drawdown=drawdown,
    )


def simulate_sector_weakness(
    *,
    entry_price: float,
    bars: Sequence[path_labels.DailyBar],
    etf_bars: Sequence[path_labels.DailyBar],
    hard_stop_pct: float = 6.0,
    weakness_3d_pct: float = -3.0,
) -> PolicyResult:
    policy_id = "sector_etf_weak3d"
    if len(etf_bars) < 4:
        return _result(policy_id=policy_id, policy_status="missing_policy_data", exit_reason="missing_sector_etf")

    etf_by_day = {bar.day: bar for bar in etf_bars}
    etf_closes: list[float] = []
    peak = None
    drawdown = None
    hard_stop = entry_price * (1.0 - hard_stop_pct / 100.0)

    for session, bar in enumerate(bars, start=1):
        peak, drawdown = _mark_path_extremes(
            entry_price=entry_price,
            bar=bar,
            realized=0.0,
            remaining=1.0,
            peak=peak,
            drawdown=drawdown,
        )
        if bar.low <= hard_stop:
            ret = _ret_pct(hard_stop, entry_price)
            return _result(
                policy_id=policy_id,
                policy_status="closed",
                exit_reason="hard_stop",
                exit_day=bar.day,
                exit_session=session,
                realized_ret_pct=ret,
                total_equity_ret_40d_pct=ret,
                closed_fraction_40d=1.0,
                exposure_sessions=session,
                peak_equity_ret_pct=peak,
                max_drawdown_ret_pct=drawdown,
            )
        etf_bar = etf_by_day.get(bar.day)
        if etf_bar is None:
            continue
        etf_closes.append(etf_bar.close)
        if len(etf_closes) >= 4:
            ret_3d = _ret_pct(etf_closes[-1], etf_closes[-4])
            if ret_3d <= weakness_3d_pct:
                ret = _ret_pct(bar.close, entry_price)
                return _result(
                    policy_id=policy_id,
                    policy_status="closed",
                    exit_reason="sector_etf_3d_weakness",
                    exit_day=bar.day,
                    exit_session=session,
                    realized_ret_pct=ret,
                    total_equity_ret_40d_pct=ret,
                    closed_fraction_40d=1.0,
                    exposure_sessions=session,
                    peak_equity_ret_pct=peak,
                    max_drawdown_ret_pct=drawdown,
                )

    return _finish_open(
        policy_id=policy_id,
        entry_price=entry_price,
        bars=bars,
        realized=0.0,
        remaining=1.0,
        peak=peak,
        drawdown=drawdown,
    )


def simulate_policy(
    policy_id: str,
    *,
    entry_price: float,
    bars: Sequence[path_labels.DailyBar],
    etf_bars: Sequence[path_labels.DailyBar] = (),
) -> PolicyResult:
    if not bars or entry_price <= 0:
        return _result(policy_id=policy_id, policy_status="unavailable", exit_reason="missing_price_path")
    if policy_id == "hold_40d_mtm":
        return simulate_hold(entry_price, bars)
    if policy_id == "fixed_t4_s2":
        return simulate_fixed_target_stop(
            policy_id=policy_id,
            entry_price=entry_price,
            bars=bars,
            target_pct=4.0,
            stop_pct=2.0,
        )
    if policy_id == "fixed_t8_s4":
        return simulate_fixed_target_stop(
            policy_id=policy_id,
            entry_price=entry_price,
            bars=bars,
            target_pct=8.0,
            stop_pct=4.0,
        )
    if policy_id == "partial_t4_trail8":
        return simulate_partial_target_trail(entry_price=entry_price, bars=bars)
    if policy_id == "giveback35_after8":
        return simulate_giveback_after_peak(entry_price=entry_price, bars=bars)
    if policy_id == "swinglow3_after8":
        return simulate_swinglow_trail(entry_price=entry_price, bars=bars)
    if policy_id == "time10_lt2_hard6":
        return simulate_time_stop(entry_price=entry_price, bars=bars)
    if policy_id == "sector_etf_weak3d":
        return simulate_sector_weakness(entry_price=entry_price, bars=bars, etf_bars=etf_bars)
    raise ValueError(f"Unsupported policy_id: {policy_id}")


def build_policy_labels(
    labels: pd.DataFrame,
    *,
    calendar: list[str],
    bars: dict[tuple[str, str], path_labels.DailyBar],
    max_horizon: int = MAX_HORIZON,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    specs = {spec.policy_id: spec for spec in policy_catalog()}
    for record in labels.to_dict("records"):
        path, scheduled_days = _bars_for_record(record, calendar=calendar, bars=bars, max_horizon=max_horizon)
        etf_path = _etf_bars_for_record(record, scheduled_days=scheduled_days, bars=bars)
        entry_price = float(record["label_entry_price"])
        for policy_id, spec in specs.items():
            result = simulate_policy(policy_id, entry_price=entry_price, bars=path, etf_bars=etf_path)
            row = {
                "scan_date": record["scan_date"],
                "symbol": record["symbol"],
                "opportunity_id": record["opportunity_id"],
                "policy_id": policy_id,
                "policy_description": spec.description,
                "deployability": spec.deployability,
                "source_tags": record.get("source_tags", ""),
                "kumo_scanner": record.get("kumo_scanner", False),
                "kumo_top_n": record.get("kumo_top_n", False),
                "george_scanner_positive": record.get("george_scanner_positive", False),
                "george_watchlist": record.get("george_watchlist", False),
                "kumo_rank_by_score": record.get("kumo_rank_by_score"),
                "kumo_score": record.get("kumo_score"),
                "company_sector": record.get("company_sector"),
                "company_industry": record.get("company_industry"),
                "sector_etf_proxy": record.get("sector_etf_proxy"),
                "label_entry_date": record.get("label_entry_date"),
                "label_entry_price": record.get("label_entry_price"),
                "label_outcome_20d": record.get("label_outcome_20d"),
                "label_runner_candidate_20d": record.get("label_runner_candidate_20d"),
                "label_bad_trade_20d": record.get("label_bad_trade_20d"),
                "label_mfe_40d_pct": record.get("label_mfe_40d_pct"),
                "label_ret_40d_close_pct": record.get("label_ret_40d_close_pct"),
                "true_runner_40d": record.get("true_runner_40d"),
                **asdict(result),
            }
            row["runner_preserved_40d"] = bool(
                row["true_runner_40d"]
                and row["total_equity_ret_40d_pct"] is not None
                and (
                    row["open_fraction_40d"] >= 0.5
                    or row["total_equity_ret_40d_pct"] >= 0.5 * float(row["label_mfe_40d_pct"] or 0.0)
                )
            )
            row["runner_cut_early_40d"] = bool(
                row["true_runner_40d"]
                and row["policy_status"] == "closed"
                and (row["exit_session"] is not None and row["exit_session"] < 20)
                and not row["runner_preserved_40d"]
            )
            rows.append(row)
    return pd.DataFrame(rows)


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


def _summary_pct(mask: pd.Series) -> float:
    if len(mask) == 0:
        return 0.0
    return round(100.0 * float(mask.mean()), 3)


def _policy_summary_rows(frame: pd.DataFrame, *, group_columns: Sequence[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for group_values, subset in frame.groupby(list(group_columns), dropna=False):
        if not isinstance(group_values, tuple):
            group_values = (group_values,)
        available = subset[subset["total_equity_ret_40d_pct"].notna()].copy()
        runners = available[available["true_runner_40d"]].copy()
        row = {column: value for column, value in zip(group_columns, group_values)}
        row.update(
            {
                "rows": int(len(subset)),
                "available_rows": int(len(available)),
                "closed_pct": _summary_pct(available["policy_status"].eq("closed")),
                "open_at_horizon_pct": _summary_pct(available["open_fraction_40d"].gt(0)),
                "avg_realized_ret_pct": _summary_mean(available["realized_ret_pct"]),
                "avg_open_mtm_ret_pct": _summary_mean(available["open_mtm_ret_40d_pct"]),
                "avg_total_equity_ret_40d_pct": _summary_mean(available["total_equity_ret_40d_pct"]),
                "median_total_equity_ret_40d_pct": _summary_median(available["total_equity_ret_40d_pct"]),
                "win_rate_pct": _summary_pct(available["total_equity_ret_40d_pct"].gt(0)),
                "bad_total_le_minus6_pct": _summary_pct(available["total_equity_ret_40d_pct"].le(-6)),
                "avg_giveback_from_peak_pct": _summary_mean(available["giveback_from_peak_pct"]),
                "avg_max_drawdown_ret_pct": _summary_mean(available["max_drawdown_ret_pct"]),
                "runner_rows": int(len(runners)),
                "runner_preserved_pct": _summary_pct(runners["runner_preserved_40d"]) if len(runners) else 0.0,
                "runner_cut_early_pct": _summary_pct(runners["runner_cut_early_40d"]) if len(runners) else 0.0,
                "avg_exposure_sessions": _summary_mean(available["exposure_sessions"]),
                "objective_score": _objective_score(available, runners),
            }
        )
        rows.append(row)
    return rows


def _objective_score(available: pd.DataFrame, runners: pd.DataFrame) -> float:
    if available.empty:
        return -999.0
    total = _summary_mean(available["total_equity_ret_40d_pct"]) or 0.0
    realized = _summary_mean(available["realized_ret_pct"]) or 0.0
    drawdown = abs(_summary_mean(available["max_drawdown_ret_pct"]) or 0.0)
    runner_preserved = _summary_pct(runners["runner_preserved_40d"]) if len(runners) else 0.0
    runner_cut = _summary_pct(runners["runner_cut_early_40d"]) if len(runners) else 0.0
    return round(total + 0.35 * realized - 0.08 * drawdown + 0.02 * runner_preserved - 0.03 * runner_cut, 4)


def policy_summary(frame: pd.DataFrame) -> pd.DataFrame:
    rows = _policy_summary_rows(frame, group_columns=["policy_id"])
    return pd.DataFrame(rows).sort_values("objective_score", ascending=False).reset_index(drop=True)


def source_policy_summary(frame: pd.DataFrame) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    source_masks = {
        "kumo_top100": frame["kumo_top_n"],
        "kumo_scanner": frame["kumo_scanner"],
        "george_scanner_or_watchlist": frame["george_scanner_positive"] | frame["george_watchlist"],
    }
    for source_flag, mask in source_masks.items():
        subset = frame[mask].copy()
        if subset.empty:
            continue
        source_frame = pd.DataFrame(_policy_summary_rows(subset, group_columns=["policy_id"]))
        source_frame.insert(0, "source_flag", source_flag)
        frames.append(source_frame)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).sort_values(
        ["source_flag", "objective_score"],
        ascending=[True, False],
    )


def exit_reason_summary(frame: pd.DataFrame) -> pd.DataFrame:
    return (
        frame.groupby(["policy_id", "policy_status", "exit_reason"], dropna=False)
        .agg(rows=("symbol", "size"))
        .reset_index()
        .sort_values(["policy_id", "rows"], ascending=[True, False])
        .reset_index(drop=True)
    )


def best_worst(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    columns = [
        "scan_date",
        "symbol",
        "policy_id",
        "source_tags",
        "kumo_rank_by_score",
        "kumo_score",
        "sector_etf_proxy",
        "label_outcome_20d",
        "true_runner_40d",
        "policy_status",
        "exit_reason",
        "exit_session",
        "realized_ret_pct",
        "open_mtm_ret_40d_pct",
        "total_equity_ret_40d_pct",
        "giveback_from_peak_pct",
        "runner_preserved_40d",
        "runner_cut_early_40d",
    ]
    available = frame[frame["total_equity_ret_40d_pct"].notna()].copy()
    best = available.sort_values(["total_equity_ret_40d_pct", "realized_ret_pct"], ascending=[False, False]).head(50)
    worst = available.sort_values(["total_equity_ret_40d_pct", "max_drawdown_ret_pct"], ascending=[True, True]).head(50)
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
    policies: pd.DataFrame,
    source_summary: pd.DataFrame,
    reason_summary: pd.DataFrame,
    config: ExitConfig,
) -> None:
    deployable = policies[~policies["policy_id"].eq("hold_40d_mtm")].head(3)
    lines = [
        "# Scanner Exit Policy Research #466",
        "",
        "This report simulates realization policies on the #464 scanner opportunity paths.",
        "Metrics include closed realized return plus open mark-to-market at the 40-session horizon.",
        "",
        "## Inputs",
        "",
        f"- Labels: `{config.labels}`",
        f"- Panel metadata: `{config.panel}`",
        f"- Parquet root: `{config.parquet_root}`",
        f"- Candidate filter: `{config.candidate_filter}`",
        "",
        "## Read",
        "",
        f"- Opportunities: `{labels['opportunity_id'].nunique()}`",
        f"- Policy rows: `{len(labels)}`",
        "- `hold_40d_mtm` is the runner-preservation baseline, not a deployable exit.",
        "- No simple tested exit beats the hold baseline on total 40-session equity; the candidates",
        "  below are LEAN/QC sweep candidates, not promotion recommendations.",
        "- Stop/target conflicts on one daily bar are treated conservatively as stop-first.",
        "- Sector ETF weakness is measured only where the #463 panel has a sector ETF proxy.",
        "",
        "## Policy Summary",
        "",
        _markdown_table(
            policies,
            [
                "policy_id",
                "available_rows",
                "closed_pct",
                "open_at_horizon_pct",
                "avg_realized_ret_pct",
                "avg_open_mtm_ret_pct",
                "avg_total_equity_ret_40d_pct",
                "median_total_equity_ret_40d_pct",
                "win_rate_pct",
                "bad_total_le_minus6_pct",
                "runner_preserved_pct",
                "runner_cut_early_pct",
                "objective_score",
            ],
        ),
        "",
        "## Recommended LEAN/QC Sweep Candidates",
        "",
        "These are the best deployable candidates by the current objective. They deliberately",
        "trade off total equity against realization, drawdown, and runner retention.",
        "",
        _markdown_table(
            deployable,
            [
                "policy_id",
                "avg_realized_ret_pct",
                "avg_total_equity_ret_40d_pct",
                "runner_preserved_pct",
                "runner_cut_early_pct",
                "avg_giveback_from_peak_pct",
                "objective_score",
            ],
        ),
        "",
        "## Source Summary",
        "",
        _markdown_table(
            source_summary,
            [
                "source_flag",
                "policy_id",
                "avg_realized_ret_pct",
                "avg_total_equity_ret_40d_pct",
                "runner_preserved_pct",
                "runner_cut_early_pct",
                "objective_score",
            ],
            limit=30,
        ),
        "",
        "## Exit Reasons",
        "",
        _markdown_table(reason_summary, ["policy_id", "policy_status", "exit_reason", "rows"], limit=40),
        "",
        "## Deployability Notes",
        "",
        "- Fixed target/stop, partial target + trail, giveback trail, swing-low trail, and time stop",
        "  need only price bars and are deployable in local LEAN and QC Cloud.",
        "- Sector ETF weakness requires an ETF proxy map to be present in the candidate metadata and",
        "  the ETF symbols to be subscribed in LEAN/QC.",
        "- A true cloud/Kijun trail should be tested in LEAN with indicator state; this raw-bar harness",
        "  uses `swinglow3_after8` as the deployable price-only proxy.",
        "",
    ]
    (output_dir / "exit_policy_report.md").write_text("\n".join(lines), encoding="utf-8")


def write_outputs(*, labels: pd.DataFrame, config: ExitConfig, output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "README.md").write_text(
        "# scanner_exit_policies_466/\n\n"
        "Exit and profit-realization policy research for issue #466. Keep compact derived labels, "
        "summaries, and examples here; do not store raw parquet or bulky LEAN run folders.\n",
        encoding="utf-8",
    )
    label_path = output_dir / "exit_policy_labels.csv.gz"
    _write_gzip_csv(labels, label_path)
    policies = policy_summary(labels)
    source_summary = source_policy_summary(labels)
    reasons = exit_reason_summary(labels)
    best, worst = best_worst(labels)
    policies.to_csv(output_dir / "exit_policy_summary.csv", index=False)
    source_summary.to_csv(output_dir / "source_exit_policy_summary.csv", index=False)
    reasons.to_csv(output_dir / "exit_reason_summary.csv", index=False)
    best.to_csv(output_dir / "best_exit_policy_examples.csv", index=False)
    worst.to_csv(output_dir / "worst_exit_policy_examples.csv", index=False)
    write_report(
        output_dir=output_dir,
        labels=labels,
        policies=policies,
        source_summary=source_summary,
        reason_summary=reasons,
        config=config,
    )
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "issue": "https://github.com/FALK-BRAUER/kumo-qc/issues/466",
        "config": asdict(config),
        "outputs": {
            "exit_policy_labels.csv.gz": {"rows": int(len(labels)), "columns": list(labels.columns)},
            "exit_policy_summary.csv": {"rows": int(len(policies))},
            "source_exit_policy_summary.csv": {"rows": int(len(source_summary))},
            "exit_reason_summary.csv": {"rows": int(len(reasons))},
            "best_exit_policy_examples.csv": {"rows": int(len(best))},
            "worst_exit_policy_examples.csv": {"rows": int(len(worst))},
            "exit_policy_report.md": {},
        },
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return {
        "labels": label_path,
        "exit_policy_summary": output_dir / "exit_policy_summary.csv",
        "source_exit_policy_summary": output_dir / "source_exit_policy_summary.csv",
        "exit_reason_summary": output_dir / "exit_reason_summary.csv",
        "best_examples": output_dir / "best_exit_policy_examples.csv",
        "worst_examples": output_dir / "worst_exit_policy_examples.csv",
        "report": output_dir / "exit_policy_report.md",
        "manifest": output_dir / "manifest.json",
    }


def run(
    *,
    labels_path: Path = DEFAULT_LABELS,
    panel_path: Path = DEFAULT_PANEL,
    parquet_root: Path = DEFAULT_PARQUET_ROOT,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    candidate_filter: str = DEFAULT_CANDIDATE_FILTER,
    limit: int | None = None,
) -> dict[str, Path]:
    config = ExitConfig(
        labels=str(labels_path),
        panel=str(panel_path),
        parquet_root=str(parquet_root),
        output_dir=str(output_dir),
        candidate_filter=candidate_filter,
        max_horizon=MAX_HORIZON,
        limit=limit,
    )
    labels = read_labels(labels_path, panel_path, candidate_filter=candidate_filter, limit=limit)
    calendar = path_labels.parquet_calendar(parquet_root)
    dates = needed_dates(labels, calendar, max_horizon=MAX_HORIZON)
    symbols = set(labels["symbol"].astype(str))
    symbols.update(symbol for symbol in labels["sector_etf_proxy"].astype(str) if symbol and symbol != "nan")
    bars = path_labels.build_daily_bar_lookup(parquet_root=parquet_root, dates=dates, symbols=symbols)
    policy_labels = build_policy_labels(labels, calendar=calendar, bars=bars, max_horizon=MAX_HORIZON)
    return write_outputs(labels=policy_labels, config=config, output_dir=output_dir)


def main() -> None:
    args = _args()
    outputs = run(
        labels_path=args.labels,
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
