"""Build as-of intraday decision rows from ranked scanner candidates (#491)."""
from __future__ import annotations

import argparse
import bisect
import gzip
import io
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import build_scanner_opportunity_path_labels as path_labels  # noqa: E402

DEFAULT_UNIVERSE = ROOT / "sweeps" / "reports" / "scanner_trade_universe_482" / "scanner_trade_universe.csv.gz"
DEFAULT_ENTRY_LABELS = ROOT / "sweeps" / "reports" / "scanner_entry_replay_465" / "alternate_entry_labels.csv.gz"
DEFAULT_EXIT_LABELS = ROOT / "sweeps" / "reports" / "scanner_exit_policies_466" / "exit_policy_labels.csv.gz"
DEFAULT_PARQUET_ROOT = Path("/Users/falk/projects/kumo-trader/data/intraday")
DEFAULT_OUTPUT_DIR = ROOT / "sweeps" / "reports" / "intraday_decision_panel_491"
FEATURE_VERSION = "intraday_decision_panel_491_v1"
BAR_MINUTES = 5
CHECKPOINTS: tuple[tuple[str, str], ...] = (
    ("open", "09:30:00"),
    ("after_15m", "09:45:00"),
    ("after_30m", "10:00:00"),
    ("first_hour", "10:30:00"),
    ("midday", "12:00:00"),
    ("close", "16:00:00"),
)
CANDIDATE_FILTERS = ("all", "kumo_ranked", "kumo_top100", "george_seen", "kumo_or_george")

BOOL_COLUMNS = (
    "george_signal_seen",
    "george_video_only_context",
    "kumo_signal_seen",
    "kumo_top_n",
    "both_george_and_kumo",
    "george_scanner_positive",
    "george_watchlist",
    "george_video_mention",
    "kumo_scanner",
    "best_entry_runner_candidate_20d",
    "best_entry_normal_winner_20d",
    "best_entry_bad_trade_20d",
    "next_open_triggered",
    "next_open_bad_trade_20d",
    "best_deployable_runner_preserved_40d",
)
UNIVERSE_COLUMNS = {
    "scan_date",
    "symbol",
    "opportunity_id",
    "trade_bucket",
    "reason_codes",
    "source_bucket",
    "george_signal_seen",
    "george_video_only_context",
    "kumo_signal_seen",
    "kumo_top_n",
    "both_george_and_kumo",
    "george_scanner_positive",
    "george_watchlist",
    "george_video_mention",
    "kumo_scanner",
    "kumo_rank_by_score",
    "kumo_score",
    "george_rank",
    "george_watchlist_rank",
    "company_sector",
    "company_industry",
    "sector_category",
    "sector_etf_proxy",
    "source_tags",
    "best_entry_assumption",
    "best_entry_date",
    "best_entry_time",
    "best_entry_price",
    "best_entry_ret_20d_close_pct",
    "best_entry_mfe_20d_pct",
    "best_entry_mae_20d_pct",
    "best_entry_t4_s2_20d_outcome",
    "best_entry_runner_candidate_20d",
    "best_entry_normal_winner_20d",
    "best_entry_bad_trade_20d",
    "best_entry_outcome_20d",
    "next_open_triggered",
    "next_open_ret_20d_close_pct",
    "next_open_mfe_20d_pct",
    "next_open_mae_20d_pct",
    "next_open_bad_trade_20d",
    "best_deployable_exit_policy_id",
    "best_deployable_exit_reason",
    "best_deployable_exit_status",
    "best_deployable_total_equity_ret_40d_pct",
    "best_deployable_realized_ret_pct",
    "best_deployable_exposure_sessions",
    "best_deployable_runner_preserved_40d",
    "oracle_best_exit_policy_id",
    "oracle_best_total_equity_ret_40d_pct",
    "hold_40d_total_equity_ret_40d_pct",
    "model_combined_score",
}
ENTRY_LABEL_COLUMNS = {
    "opportunity_id",
    "entry_assumption",
    "label_triggered",
    "label_trigger_status",
    "label_trigger_reason",
    "label_entry_time",
    "label_entry_price",
    "label_prior_close",
    "label_prior_session_high",
    "label_entry_gap_pct",
    "label_ret_20d_close_pct",
    "label_mfe_20d_pct",
    "label_mae_20d_pct",
    "label_bad_trade_20d",
    "label_outcome_20d",
}
EXIT_LABEL_COLUMNS = {
    "opportunity_id",
    "policy_id",
    "policy_status",
    "exit_reason",
    "exit_day",
    "exit_session",
    "realized_ret_pct",
    "total_equity_ret_40d_pct",
    "runner_preserved_40d",
    "runner_cut_early_40d",
}


@dataclass(frozen=True)
class DecisionConfig:
    universe: str
    entry_labels: str
    exit_labels: str
    parquet_root: str
    output_dir: str
    candidate_filter: str
    limit: int | None
    checkpoints: tuple[tuple[str, str], ...]


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--universe", type=Path, default=DEFAULT_UNIVERSE)
    parser.add_argument("--entry-labels", type=Path, default=DEFAULT_ENTRY_LABELS)
    parser.add_argument("--exit-labels", type=Path, default=DEFAULT_EXIT_LABELS)
    parser.add_argument("--parquet-root", type=Path, default=DEFAULT_PARQUET_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--candidate-filter", choices=CANDIDATE_FILTERS, default="kumo_or_george")
    parser.add_argument("--limit", type=int, default=None, help="Optional candidate limit for smoke/debug runs.")
    return parser.parse_args()


def _parse_day(value: Any) -> str:
    return path_labels._parse_day(value)


def _clean_symbol(value: Any) -> str:
    return path_labels._clean_symbol(value)


def _bool_series(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip().str.lower().isin({"1", "true", "yes", "y"})


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame:
        return pd.Series(np.nan, index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce")


def _round(value: Any, digits: int = 4) -> float | None:
    if value is None or pd.isna(value):
        return None
    return round(float(value), digits)


def _ts(value: Any) -> pd.Timestamp | None:
    if value is None or pd.isna(value) or str(value).strip() == "":
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return pd.Timestamp(parsed).tz_localize(None) if pd.Timestamp(parsed).tzinfo else pd.Timestamp(parsed)


def _checkpoint_timestamp(day: str, time_text: str) -> pd.Timestamp:
    return pd.Timestamp(f"{day} {time_text}")


def read_universe(path: Path, *, candidate_filter: str, limit: int | None) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    frame = pd.read_csv(path, usecols=lambda column: column in UNIVERSE_COLUMNS, low_memory=False)
    frame["scan_date"] = frame["scan_date"].map(_parse_day)
    frame["symbol"] = frame["symbol"].map(_clean_symbol)
    frame["opportunity_id"] = frame["scan_date"] + "|" + frame["symbol"]
    frame["trade_bucket"] = frame["trade_bucket"].astype(str).str.strip().str.lower()
    for column in BOOL_COLUMNS:
        if column in frame:
            frame[column] = _bool_series(frame[column])
    rank = _num(frame, "kumo_rank_by_score")
    george_seen = frame["george_signal_seen"] | frame["george_scanner_positive"] | frame["george_watchlist"]
    filters = {
        "all": pd.Series(True, index=frame.index),
        "kumo_ranked": frame["kumo_signal_seen"] & rank.notna(),
        "kumo_top100": frame["kumo_top_n"],
        "george_seen": george_seen,
        "kumo_or_george": (frame["kumo_signal_seen"] & rank.notna()) | george_seen,
    }
    frame = frame[filters[candidate_filter]].copy()
    if limit is not None:
        frame = frame.head(limit).copy()
    return frame.sort_values(["scan_date", "symbol"]).reset_index(drop=True)


def read_entry_labels(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=sorted(ENTRY_LABEL_COLUMNS))
    frame = pd.read_csv(path, usecols=lambda column: column in ENTRY_LABEL_COLUMNS, low_memory=False)
    frame["opportunity_id"] = frame["opportunity_id"].astype(str)
    frame["entry_assumption"] = frame["entry_assumption"].astype(str)
    if "label_triggered" in frame:
        frame["label_triggered"] = _bool_series(frame["label_triggered"])
    if "label_bad_trade_20d" in frame:
        frame["label_bad_trade_20d"] = _bool_series(frame["label_bad_trade_20d"])
    return frame


def read_exit_labels(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=sorted(EXIT_LABEL_COLUMNS))
    frame = pd.read_csv(path, usecols=lambda column: column in EXIT_LABEL_COLUMNS, low_memory=False)
    frame["opportunity_id"] = frame["opportunity_id"].astype(str)
    frame["policy_id"] = frame["policy_id"].astype(str)
    for column in ("runner_preserved_40d", "runner_cut_early_40d"):
        if column in frame:
            frame[column] = _bool_series(frame[column])
    return frame


def enrich_with_entry_label_counts(universe: pd.DataFrame, entry_labels: pd.DataFrame) -> pd.DataFrame:
    if entry_labels.empty:
        universe["triggered_entry_assumptions"] = 0
        universe["bad_entry_assumptions"] = 0
        universe["next_open_prior_close"] = np.nan
        universe["next_open_prior_session_high"] = np.nan
        universe["next_open_entry_gap_pct"] = np.nan
        return universe
    grouped = (
        entry_labels.groupby("opportunity_id", dropna=False)
        .agg(
            triggered_entry_assumptions=("label_triggered", "sum"),
            bad_entry_assumptions=("label_bad_trade_20d", "sum"),
        )
        .reset_index()
    )
    out = universe.merge(grouped, on="opportunity_id", how="left")
    next_open = (
        entry_labels[entry_labels["entry_assumption"].eq("next_open")]
        .loc[:, ["opportunity_id", "label_prior_close", "label_prior_session_high", "label_entry_gap_pct"]]
        .rename(
            columns={
                "label_prior_close": "next_open_prior_close",
                "label_prior_session_high": "next_open_prior_session_high",
                "label_entry_gap_pct": "next_open_entry_gap_pct",
            }
        )
        .drop_duplicates("opportunity_id", keep="first")
    )
    out = out.merge(next_open, on="opportunity_id", how="left")
    out["triggered_entry_assumptions"] = _num(out, "triggered_entry_assumptions").fillna(0).astype(int)
    out["bad_entry_assumptions"] = _num(out, "bad_entry_assumptions").fillna(0).astype(int)
    return out


def enrich_with_exit_policy_context(universe: pd.DataFrame, exit_labels: pd.DataFrame) -> pd.DataFrame:
    if exit_labels.empty or "best_deployable_exit_policy_id" not in universe:
        universe["best_exit_runner_cut_early_40d"] = False
        return universe
    best_policy = universe.loc[:, ["opportunity_id", "best_deployable_exit_policy_id"]].rename(
        columns={"best_deployable_exit_policy_id": "policy_id"}
    )
    context = best_policy.merge(exit_labels, on=["opportunity_id", "policy_id"], how="left")
    context = context.loc[
        :,
        [
            "opportunity_id",
            "runner_cut_early_40d",
            "runner_preserved_40d",
            "policy_status",
            "exit_reason",
            "total_equity_ret_40d_pct",
        ],
    ].rename(
        columns={
            "runner_cut_early_40d": "best_exit_runner_cut_early_40d",
            "runner_preserved_40d": "best_exit_runner_preserved_40d_from_policy",
            "policy_status": "best_exit_policy_status_from_policy",
            "exit_reason": "best_exit_reason_from_policy",
            "total_equity_ret_40d_pct": "best_exit_total_equity_ret_40d_pct_from_policy",
        }
    )
    out = universe.merge(context, on="opportunity_id", how="left")
    out["best_exit_runner_cut_early_40d"] = _bool_series(out["best_exit_runner_cut_early_40d"])
    out["best_exit_runner_preserved_40d_from_policy"] = _bool_series(out["best_exit_runner_preserved_40d_from_policy"])
    return out


def attach_entry_days(universe: pd.DataFrame, calendar: list[str]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for row in universe.to_dict("records"):
        scan_day = str(row["scan_date"])
        idx = bisect.bisect_right(calendar, scan_day)
        row["entry_session_date"] = calendar[idx] if idx < len(calendar) else ""
        row["entry_session_available"] = idx < len(calendar)
        rows.append(row)
    return pd.DataFrame(rows)


def _read_day_bars(parquet_root: Path, day: str, symbols: set[str]) -> pd.DataFrame:
    path = parquet_root / f"{day}.parquet"
    if not path.exists() or not symbols:
        return pd.DataFrame(columns=["symbol", "_dt", "open", "high", "low", "close", "volume"])
    frame = pd.read_parquet(path, columns=["ticker", "datetime", "open", "high", "low", "close", "volume"])
    frame = frame.rename(columns={"ticker": "symbol"}).copy()
    frame["symbol"] = frame["symbol"].map(_clean_symbol)
    frame = frame[frame["symbol"].isin(symbols)].copy()
    if frame.empty:
        return pd.DataFrame(columns=["symbol", "_dt", "open", "high", "low", "close", "volume"])
    frame["_dt"] = pd.to_datetime(frame["datetime"], errors="coerce")
    minutes = frame["_dt"].dt.hour * 60 + frame["_dt"].dt.minute
    frame = frame[(minutes >= 570) & (minutes < 960)].copy()
    return frame.sort_values(["symbol", "_dt"]).reset_index(drop=True)


def _split_bars(day_frame: pd.DataFrame) -> dict[str, pd.DataFrame]:
    return {str(symbol): group.reset_index(drop=True) for symbol, group in day_frame.groupby("symbol", sort=False)}


def completed_bars(bars: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    if bars.empty:
        return bars.copy()
    cutoff = as_of - timedelta(minutes=BAR_MINUTES)
    return bars[bars["_dt"].le(cutoff)].copy()


def _ret_pct(price: float, base: float) -> float:
    return (float(price) / float(base) - 1.0) * 100.0


def _vwap(frame: pd.DataFrame) -> float | None:
    if frame.empty:
        return None
    volume = pd.to_numeric(frame["volume"], errors="coerce").fillna(0.0)
    total_volume = float(volume.sum())
    if total_volume <= 0:
        return None
    typical = (frame["high"].astype(float) + frame["low"].astype(float) + frame["close"].astype(float)) / 3.0
    return float((typical * volume).sum() / total_volume)


def _window_features(frame: pd.DataFrame, *, prefix: str, bars_needed: int, session_open: float | None) -> dict[str, Any]:
    if len(frame) < bars_needed or session_open is None:
        return {
            f"{prefix}_available": False,
            f"{prefix}_ret_pct": None,
            f"{prefix}_range_pct": None,
            f"{prefix}_volume": None,
        }
    window = frame.tail(bars_needed)
    open_price = float(window["open"].iloc[0])
    close_price = float(window["close"].iloc[-1])
    high_price = float(window["high"].max())
    low_price = float(window["low"].min())
    return {
        f"{prefix}_available": True,
        f"{prefix}_ret_pct": _round(_ret_pct(close_price, open_price)),
        f"{prefix}_range_pct": _round((high_price / low_price - 1.0) * 100.0) if low_price else None,
        f"{prefix}_volume": _round(float(window["volume"].sum()), 0),
    }


def asof_features(
    *,
    bars: pd.DataFrame,
    as_of: pd.Timestamp,
    prior_close: float | None,
    prefix: str = "",
) -> dict[str, Any]:
    key = f"{prefix}_" if prefix else ""
    if bars.empty:
        return {
            f"{key}intraday_available": False,
            f"{key}bars_completed": 0,
            f"{key}session_open": None,
            f"{key}current_price": None,
            f"{key}return_from_open_pct": None,
            f"{key}gap_from_prior_close_pct": None,
            f"{key}high_so_far": None,
            f"{key}low_so_far": None,
            f"{key}mfe_from_open_pct": None,
            f"{key}mae_from_open_pct": None,
            f"{key}volume_so_far": None,
            f"{key}vwap_so_far": None,
            f"{key}distance_from_vwap_pct": None,
            f"{key}last_15m_available": False,
            f"{key}last_15m_ret_pct": None,
            f"{key}last_15m_range_pct": None,
            f"{key}last_15m_volume": None,
            f"{key}last_hour_available": False,
            f"{key}last_hour_ret_pct": None,
            f"{key}last_hour_range_pct": None,
            f"{key}last_hour_volume": None,
            f"{key}ichimoku_15m_available": False,
            f"{key}ichimoku_hour_available": False,
        }
    session_open = float(bars["open"].iloc[0])
    done = completed_bars(bars, as_of)
    current_price = session_open if done.empty else float(done["close"].iloc[-1])
    high_so_far = session_open if done.empty else float(max(session_open, done["high"].max()))
    low_so_far = session_open if done.empty else float(min(session_open, done["low"].min()))
    vwap = _vwap(done)
    row = {
        f"{key}intraday_available": True,
        f"{key}bars_completed": int(len(done)),
        f"{key}session_open": _round(session_open),
        f"{key}current_price": _round(current_price),
        f"{key}return_from_open_pct": _round(_ret_pct(current_price, session_open)),
        f"{key}gap_from_prior_close_pct": _round(_ret_pct(session_open, prior_close)) if prior_close else None,
        f"{key}high_so_far": _round(high_so_far),
        f"{key}low_so_far": _round(low_so_far),
        f"{key}mfe_from_open_pct": _round(_ret_pct(high_so_far, session_open)),
        f"{key}mae_from_open_pct": _round(_ret_pct(low_so_far, session_open)),
        f"{key}volume_so_far": _round(float(done["volume"].sum()), 0) if not done.empty else 0.0,
        f"{key}vwap_so_far": _round(vwap),
        f"{key}distance_from_vwap_pct": _round(_ret_pct(current_price, vwap)) if vwap else None,
    }
    row.update(_window_features(done, prefix=f"{key}last_15m", bars_needed=3, session_open=session_open))
    row.update(_window_features(done, prefix=f"{key}last_hour", bars_needed=12, session_open=session_open))
    # The first #491 artifact exposes coverage flags. Historical 15m/hour Ichimoku warmup is a follow-on enrichment.
    row[f"{key}ichimoku_15m_available"] = False
    row[f"{key}ichimoku_hour_available"] = False
    return row


def position_features(
    *,
    bars: pd.DataFrame,
    as_of: pd.Timestamp,
    entry_time: pd.Timestamp,
    entry_price: float,
) -> dict[str, Any]:
    done = completed_bars(bars, as_of)
    post_entry = done[done["_dt"].gt(entry_time)].copy() if not done.empty else done
    minutes = max(0.0, (as_of - entry_time).total_seconds() / 60.0)
    if post_entry.empty:
        current_price = entry_price
        high = entry_price
        low = entry_price
    else:
        current_price = float(post_entry["close"].iloc[-1])
        high = float(max(entry_price, post_entry["high"].max()))
        low = float(min(entry_price, post_entry["low"].min()))
    peak_ret = _ret_pct(high, entry_price)
    current_ret = _ret_pct(current_price, entry_price)
    return {
        "position_entry_price": _round(entry_price),
        "position_entry_time": entry_time.strftime("%Y-%m-%d %H:%M:%S"),
        "position_minutes_since_entry": _round(minutes, 1),
        "position_bars_completed_since_entry": int(len(post_entry)),
        "position_current_return_pct": _round(current_ret),
        "position_mfe_so_far_pct": _round(peak_ret),
        "position_mae_so_far_pct": _round(_ret_pct(low, entry_price)),
        "position_drawdown_from_peak_pct": _round(peak_ret - current_ret),
    }


def entry_action_label(record: dict[str, Any], *, as_of: pd.Timestamp) -> tuple[str, str]:
    bucket = str(record.get("trade_bucket", "")).lower()
    best_entry_time = _ts(record.get("best_entry_time"))
    if bucket == "bad":
        return "avoid_bad_entry", "candidate classified bad by #482 route labels"
    if bucket == "watch":
        return "wait", "candidate classified watch/neutral by #482 route labels"
    if bucket != "optimal":
        return "wait", "candidate has no positive route label"
    if best_entry_time is None:
        return "wait", "optimal bucket without usable best-entry timestamp"
    if as_of >= best_entry_time:
        return "enter_now", "as-of is at or after oracle best-entry trigger"
    return "wait", "oracle best-entry trigger has not occurred yet"


def management_action_label(record: dict[str, Any], *, current_return_pct: float | None, mae_so_far_pct: float | None) -> tuple[str, str]:
    bucket = str(record.get("trade_bucket", "")).lower()
    is_runner = bool(record.get("best_entry_runner_candidate_20d")) or bool(record.get("best_deployable_runner_preserved_40d"))
    is_optimal = bucket == "optimal"
    is_bad = bucket == "bad" or bool(record.get("best_entry_bad_trade_20d"))
    ret = current_return_pct if current_return_pct is not None else 0.0
    mae = mae_so_far_pct if mae_so_far_pct is not None else 0.0
    if is_bad and (ret <= -1.0 or mae <= -2.0):
        return "exit_loser", "bad route with adverse in-trade state"
    if is_bad:
        return "scratch_or_reduce", "bad route without adverse state yet"
    if is_runner and ret >= 4.0:
        return "do_not_cut_runner", "future runner with meaningful unrealized gain"
    if is_optimal and ret >= 4.0:
        return "protect_profit", "optimal route with target-like unrealized gain"
    if is_optimal or is_runner:
        return "hold_winner", "positive route still developing"
    return "hold_or_wait", "neutral route management state"


def _base_row(record: dict[str, Any], *, row_type: str, checkpoint_name: str, as_of: pd.Timestamp | None) -> dict[str, Any]:
    return {
        "feature_version": FEATURE_VERSION,
        "row_type": row_type,
        "scan_date": record.get("scan_date", ""),
        "entry_session_date": record.get("entry_session_date", ""),
        "symbol": record.get("symbol", ""),
        "opportunity_id": record.get("opportunity_id", ""),
        "checkpoint": checkpoint_name,
        "as_of_timestamp": as_of.strftime("%Y-%m-%d %H:%M:%S") if as_of is not None else "",
        "scanner_source_bucket": record.get("source_bucket", ""),
        "trade_bucket": record.get("trade_bucket", ""),
        "reason_codes": record.get("reason_codes", ""),
        "kumo_signal_seen": bool(record.get("kumo_signal_seen")),
        "kumo_top_n": bool(record.get("kumo_top_n")),
        "kumo_scanner": bool(record.get("kumo_scanner")),
        "kumo_rank_by_score": _round(record.get("kumo_rank_by_score")),
        "kumo_score": _round(record.get("kumo_score")),
        "george_signal_seen": bool(record.get("george_signal_seen")),
        "george_scanner_positive": bool(record.get("george_scanner_positive")),
        "george_watchlist": bool(record.get("george_watchlist")),
        "george_video_mention": bool(record.get("george_video_mention")),
        "george_rank": _round(record.get("george_rank")),
        "george_watchlist_rank": _round(record.get("george_watchlist_rank")),
        "company_sector": record.get("company_sector", ""),
        "company_industry": record.get("company_industry", ""),
        "sector_category": record.get("sector_category", ""),
        "sector_etf_proxy": record.get("sector_etf_proxy", ""),
        "source_tags": record.get("source_tags", ""),
        "prior_model_combined_score": _round(record.get("model_combined_score")),
        "triggered_entry_assumptions": int(record.get("triggered_entry_assumptions", 0) or 0),
        "bad_entry_assumptions": int(record.get("bad_entry_assumptions", 0) or 0),
        "next_open_prior_close": _round(record.get("next_open_prior_close")),
        "next_open_prior_session_high": _round(record.get("next_open_prior_session_high")),
        "next_open_entry_gap_pct": _round(record.get("next_open_entry_gap_pct")),
        "oracle_best_entry_assumption": record.get("best_entry_assumption", ""),
        "oracle_best_entry_time": record.get("best_entry_time", ""),
        "oracle_best_entry_price": _round(record.get("best_entry_price")),
        "oracle_best_entry_ret_20d_close_pct": _round(record.get("best_entry_ret_20d_close_pct")),
        "oracle_best_entry_mfe_20d_pct": _round(record.get("best_entry_mfe_20d_pct")),
        "oracle_best_entry_mae_20d_pct": _round(record.get("best_entry_mae_20d_pct")),
        "oracle_best_entry_outcome_20d": record.get("best_entry_outcome_20d", ""),
        "oracle_best_deployable_exit_policy_id": record.get("best_deployable_exit_policy_id", ""),
        "oracle_best_deployable_exit_reason": record.get("best_deployable_exit_reason", ""),
        "oracle_best_deployable_total_equity_ret_40d_pct": _round(
            record.get("best_deployable_total_equity_ret_40d_pct")
        ),
        "entry_action_label": "",
        "entry_action_reason": "",
        "management_action_label": "",
        "management_action_reason": "",
    }


def rows_for_candidate(
    record: dict[str, Any],
    *,
    symbol_bars: pd.DataFrame,
    etf_bars: pd.DataFrame,
    checkpoints: Sequence[tuple[str, str]] = CHECKPOINTS,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    day = str(record.get("entry_session_date", ""))
    if not day:
        for checkpoint_name, _time_text in checkpoints:
            row = _base_row(record, row_type="entry_decision", checkpoint_name=checkpoint_name, as_of=None)
            row["entry_action_label"] = "missing_intraday"
            row["entry_action_reason"] = "no next parquet calendar date for scan date"
            row.update(asof_features(bars=pd.DataFrame(), as_of=pd.Timestamp("1970-01-01"), prior_close=None))
            row.update(asof_features(bars=pd.DataFrame(), as_of=pd.Timestamp("1970-01-01"), prior_close=None, prefix="etf"))
            rows.append(row)
        return rows

    prior_close = record.get("next_open_prior_close")
    prior_close = None if prior_close is None or pd.isna(prior_close) else float(prior_close)
    best_entry_time = _ts(record.get("best_entry_time"))
    best_entry_price = record.get("best_entry_price")
    best_entry_price = None if pd.isna(best_entry_price) else float(best_entry_price)

    for checkpoint_name, time_text in checkpoints:
        as_of = _checkpoint_timestamp(day, time_text)
        row = _base_row(record, row_type="entry_decision", checkpoint_name=checkpoint_name, as_of=as_of)
        action, reason = entry_action_label(record, as_of=as_of)
        row["entry_action_label"] = action
        row["entry_action_reason"] = reason
        row.update(asof_features(bars=symbol_bars, as_of=as_of, prior_close=prior_close))
        row.update(asof_features(bars=etf_bars, as_of=as_of, prior_close=None, prefix="etf"))
        rows.append(row)

        if best_entry_time is None or best_entry_price is None or as_of < best_entry_time:
            continue
        management = _base_row(record, row_type="position_management", checkpoint_name=checkpoint_name, as_of=as_of)
        management.update(asof_features(bars=symbol_bars, as_of=as_of, prior_close=prior_close))
        management.update(asof_features(bars=etf_bars, as_of=as_of, prior_close=None, prefix="etf"))
        position = position_features(
            bars=symbol_bars,
            as_of=as_of,
            entry_time=best_entry_time,
            entry_price=float(best_entry_price),
        )
        management.update(position)
        mgmt_action, mgmt_reason = management_action_label(
            record,
            current_return_pct=position["position_current_return_pct"],
            mae_so_far_pct=position["position_mae_so_far_pct"],
        )
        management["management_action_label"] = mgmt_action
        management["management_action_reason"] = mgmt_reason
        rows.append(management)
    return rows


def build_decision_panel(
    universe: pd.DataFrame,
    *,
    parquet_root: Path,
    checkpoints: Sequence[tuple[str, str]] = CHECKPOINTS,
    progress_interval: int = 25,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    grouped = list(universe.groupby("entry_session_date", dropna=False, sort=True))
    started = datetime.now(timezone.utc)
    for idx, (entry_day, day_candidates) in enumerate(grouped, start=1):
        entry_day = str(entry_day)
        symbols = set(day_candidates["symbol"].astype(str))
        etfs = {
            _clean_symbol(value)
            for value in day_candidates.get("sector_etf_proxy", pd.Series(dtype=str)).dropna().tolist()
            if _clean_symbol(value)
        }
        day_frame = _read_day_bars(parquet_root, entry_day, symbols | etfs) if entry_day else pd.DataFrame()
        bars_by_symbol = _split_bars(day_frame) if not day_frame.empty else {}
        for record in day_candidates.to_dict("records"):
            symbol = str(record["symbol"])
            etf = _clean_symbol(record.get("sector_etf_proxy"))
            rows.extend(
                rows_for_candidate(
                    record,
                    symbol_bars=bars_by_symbol.get(symbol, pd.DataFrame()),
                    etf_bars=bars_by_symbol.get(etf, pd.DataFrame()),
                    checkpoints=checkpoints,
                )
            )
        if progress_interval and (idx == 1 or idx % progress_interval == 0 or idx == len(grouped)):
            elapsed = (datetime.now(timezone.utc) - started).total_seconds()
            print(
                f"progress {idx}/{len(grouped)} entry days, candidates={len(day_candidates)}, "
                f"rows={len(rows)}, elapsed={elapsed:.1f}s",
                file=sys.stderr,
                flush=True,
            )
    return pd.DataFrame(rows)


def coverage_summary(panel: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for row_type, subset in panel.groupby("row_type", sort=True):
        total = len(subset)
        for field in (
            "intraday_available",
            "last_15m_available",
            "last_hour_available",
            "ichimoku_15m_available",
            "ichimoku_hour_available",
            "etf_intraday_available",
            "etf_last_15m_available",
            "etf_last_hour_available",
        ):
            if field not in subset:
                continue
            available = int(subset[field].astype(bool).sum())
            rows.append(
                {
                    "row_type": row_type,
                    "feature_group": field,
                    "rows": int(total),
                    "available_rows": available,
                    "missing_rows": int(total - available),
                    "available_pct": round(100.0 * available / total, 3) if total else 0.0,
                }
            )
    return pd.DataFrame(rows).sort_values(["row_type", "feature_group"]).reset_index(drop=True)


def label_summary(panel: pd.DataFrame) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    entry = panel[panel["row_type"].eq("entry_decision")]
    if not entry.empty:
        frames.append(
            entry.groupby(["row_type", "entry_action_label"], dropna=False)
            .agg(rows=("symbol", "size"), dates=("scan_date", "nunique"), symbols=("symbol", "nunique"))
            .reset_index()
            .rename(columns={"entry_action_label": "action_label"})
        )
    management = panel[panel["row_type"].eq("position_management")]
    if not management.empty:
        frames.append(
            management.groupby(["row_type", "management_action_label"], dropna=False)
            .agg(rows=("symbol", "size"), dates=("scan_date", "nunique"), symbols=("symbol", "nunique"))
            .reset_index()
            .rename(columns={"management_action_label": "action_label"})
        )
    if not frames:
        return pd.DataFrame(columns=["row_type", "action_label", "rows", "dates", "symbols", "pct"])
    summary = pd.concat(frames, ignore_index=True)
    totals = summary.groupby("row_type")["rows"].transform("sum")
    summary["pct"] = (100.0 * summary["rows"] / totals).round(3)
    return summary.sort_values(["row_type", "rows"], ascending=[True, False]).reset_index(drop=True)


def checkpoint_summary(panel: pd.DataFrame) -> pd.DataFrame:
    rows = (
        panel.groupby(["row_type", "checkpoint"], dropna=False)
        .agg(
            rows=("symbol", "size"),
            intraday_available_pct=("intraday_available", lambda s: round(100.0 * float(s.astype(bool).mean()), 3)),
            avg_bars_completed=("bars_completed", lambda s: round(float(pd.to_numeric(s, errors="coerce").mean()), 3)),
        )
        .reset_index()
    )
    order = {name: idx for idx, (name, _time_text) in enumerate(CHECKPOINTS)}
    rows["_order"] = rows["checkpoint"].map(order).fillna(99)
    return rows.sort_values(["row_type", "_order"]).drop(columns=["_order"]).reset_index(drop=True)


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
    panel: pd.DataFrame,
    coverage: pd.DataFrame,
    labels: pd.DataFrame,
    checkpoints: pd.DataFrame,
    config: DecisionConfig,
) -> None:
    lines = [
        "# Intraday Decision Panel #491",
        "",
        "This artifact converts ranked scanner candidates into as-of decision rows for later",
        "entry/exit policy training. Features are computed from completed 5-minute bars at or",
        "before each checkpoint; oracle route fields are carried as labels only.",
        "",
        "## Inputs",
        "",
        f"- Universe: `{config.universe}`",
        f"- Entry labels: `{config.entry_labels}`",
        f"- Exit labels: `{config.exit_labels}`",
        f"- Parquet root: `{config.parquet_root}`",
        f"- Candidate filter: `{config.candidate_filter}`",
        "",
        "## Output",
        "",
        f"- Rows: `{len(panel)}`",
        f"- Entry-decision rows: `{int(panel['row_type'].eq('entry_decision').sum())}`",
        f"- Position-management rows: `{int(panel['row_type'].eq('position_management').sum())}`",
        f"- Opportunities: `{panel['opportunity_id'].nunique()}`",
        f"- Dates: `{panel['scan_date'].nunique()}`",
        f"- Feature version: `{FEATURE_VERSION}`",
        "",
        "## Label Summary",
        "",
        _markdown_table(labels, ["row_type", "action_label", "rows", "dates", "symbols", "pct"]),
        "",
        "## Checkpoint Summary",
        "",
        _markdown_table(checkpoints, ["row_type", "checkpoint", "rows", "intraday_available_pct", "avg_bars_completed"]),
        "",
        "## Coverage",
        "",
        _markdown_table(coverage, ["row_type", "feature_group", "rows", "available_rows", "missing_rows", "available_pct"]),
        "",
        "## Notes",
        "",
        "- `entry_decision` labels are `enter_now`, `wait`, `avoid_bad_entry`, or `missing_intraday`.",
        "- `position_management` labels are first-pass oracle supervision derived from #482 route buckets",
        "  and the as-of position state. They are intentionally separated from entry rows.",
        "- 15m/hour features are last completed 3-bar and 12-bar windows from the 5-minute feed.",
        "- Ichimoku flags are exposed as coverage columns; historical 15m/hour warmup is not computed",
        "  in this first #491 slice.",
        "",
    ]
    (output_dir / "intraday_decision_panel_report.md").write_text("\n".join(lines), encoding="utf-8")


def write_outputs(*, panel: pd.DataFrame, config: DecisionConfig, output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "README.md").write_text(
        "# intraday_decision_panel_491/\n\n"
        "Contains as-of intraday decision-panel artifacts for issue #491.\n"
        "Keep compact decision rows, coverage summaries, label summaries, examples, and manifests here.\n"
        "Do not store raw parquet, bulky LEAN runs, or trained model artifacts here.\n",
        encoding="utf-8",
    )
    panel_path = output_dir / "intraday_decision_panel.csv.gz"
    _write_gzip_csv(panel, panel_path)
    coverage = coverage_summary(panel)
    labels = label_summary(panel)
    checkpoints = checkpoint_summary(panel)
    examples = panel.sort_values(["scan_date", "symbol", "row_type", "as_of_timestamp"]).head(200)
    coverage.to_csv(output_dir / "coverage_summary.csv", index=False)
    labels.to_csv(output_dir / "label_summary.csv", index=False)
    checkpoints.to_csv(output_dir / "checkpoint_summary.csv", index=False)
    examples.to_csv(output_dir / "sample_rows.csv", index=False)
    write_report(
        output_dir=output_dir,
        panel=panel,
        coverage=coverage,
        labels=labels,
        checkpoints=checkpoints,
        config=config,
    )
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "issue": "https://github.com/FALK-BRAUER/kumo-qc/issues/491",
        "feature_version": FEATURE_VERSION,
        "config": asdict(config),
        "outputs": {
            "intraday_decision_panel.csv.gz": {"rows": int(len(panel)), "columns": list(panel.columns)},
            "coverage_summary.csv": {"rows": int(len(coverage))},
            "label_summary.csv": {"rows": int(len(labels))},
            "checkpoint_summary.csv": {"rows": int(len(checkpoints))},
            "sample_rows.csv": {"rows": int(len(examples))},
            "intraday_decision_panel_report.md": {},
        },
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return {
        "decision_panel": panel_path,
        "coverage_summary": output_dir / "coverage_summary.csv",
        "label_summary": output_dir / "label_summary.csv",
        "checkpoint_summary": output_dir / "checkpoint_summary.csv",
        "sample_rows": output_dir / "sample_rows.csv",
        "report": output_dir / "intraday_decision_panel_report.md",
        "manifest": output_dir / "manifest.json",
    }


def run(
    *,
    universe_path: Path = DEFAULT_UNIVERSE,
    entry_labels_path: Path = DEFAULT_ENTRY_LABELS,
    exit_labels_path: Path = DEFAULT_EXIT_LABELS,
    parquet_root: Path = DEFAULT_PARQUET_ROOT,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    candidate_filter: str = "kumo_or_george",
    limit: int | None = None,
) -> dict[str, Path]:
    config = DecisionConfig(
        universe=str(universe_path),
        entry_labels=str(entry_labels_path),
        exit_labels=str(exit_labels_path),
        parquet_root=str(parquet_root),
        output_dir=str(output_dir),
        candidate_filter=candidate_filter,
        limit=limit,
        checkpoints=CHECKPOINTS,
    )
    calendar = path_labels.parquet_calendar(parquet_root)
    universe = read_universe(universe_path, candidate_filter=candidate_filter, limit=limit)
    universe = attach_entry_days(universe, calendar)
    universe = enrich_with_entry_label_counts(universe, read_entry_labels(entry_labels_path))
    universe = enrich_with_exit_policy_context(universe, read_exit_labels(exit_labels_path))
    panel = build_decision_panel(universe, parquet_root=parquet_root, checkpoints=CHECKPOINTS)
    return write_outputs(panel=panel, config=config, output_dir=output_dir)


def main() -> None:
    args = _args()
    outputs = run(
        universe_path=args.universe,
        entry_labels_path=args.entry_labels,
        exit_labels_path=args.exit_labels,
        parquet_root=args.parquet_root,
        output_dir=args.output_dir,
        candidate_filter=args.candidate_filter,
        limit=args.limit,
    )
    for label, path in outputs.items():
        print(f"{label}: {path}")


if __name__ == "__main__":
    main()
