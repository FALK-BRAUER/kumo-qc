"""Synthesize George/Kumo scanner opportunities into optimal and bad trade artifacts.

This is the #482 bridge artifact. It joins the already-built scanner opportunity panel,
realistic entry replay labels, exit-policy outcomes, and opportunity-ranker predictions into a
single consumer-friendly trade universe.
"""
from __future__ import annotations

import argparse
import gzip
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PANEL = ROOT / "sweeps" / "reports" / "scanner_opportunity_panel_463" / "opportunity_panel.csv.gz"
DEFAULT_ENTRY_LABELS = ROOT / "sweeps" / "reports" / "scanner_entry_replay_465" / "alternate_entry_labels.csv.gz"
DEFAULT_EXIT_LABELS = ROOT / "sweeps" / "reports" / "scanner_exit_policies_466" / "exit_policy_labels.csv.gz"
DEFAULT_RANKER = ROOT / "sweeps" / "reports" / "scanner_opportunity_ranker_467" / "oof_predictions.csv.gz"
DEFAULT_OUTPUT_DIR = ROOT / "sweeps" / "reports" / "scanner_trade_universe_482"

BOOL_COLUMNS = [
    "kumo_scanner",
    "kumo_top_n",
    "george_scanner_positive",
    "george_watchlist",
    "george_video_mention",
    "label_triggered",
    "label_runner_candidate_20d",
    "label_normal_winner_20d",
    "label_bad_trade_20d",
    "label_extreme_path_flag",
]

ENTRY_USECOLS = [
    "scan_date",
    "symbol",
    "opportunity_id",
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
    "entry_assumption",
    "label_entry_date",
    "label_entry_time",
    "label_entry_price",
    "label_triggered",
    "label_trigger_status",
    "label_trigger_reason",
    "label_path_status",
    "label_ret_20d_close_pct",
    "label_mfe_20d_pct",
    "label_mae_20d_pct",
    "label_t4_s2_20d_outcome",
    "label_t8_s4_20d_outcome",
    "label_runner_candidate_20d",
    "label_normal_winner_20d",
    "label_bad_trade_20d",
    "label_extreme_path_flag",
    "label_outcome_20d",
]

PANEL_USECOLS = [
    "scan_date",
    "symbol",
    "company_sector",
    "company_industry",
    "sector_category",
    "sector_etf_proxy",
]

EXIT_USECOLS = [
    "opportunity_id",
    "policy_id",
    "policy_description",
    "deployability",
    "policy_status",
    "exit_reason",
    "exit_day",
    "exit_session",
    "realized_ret_pct",
    "open_mtm_ret_40d_pct",
    "total_equity_ret_40d_pct",
    "exposure_sessions",
    "peak_equity_ret_pct",
    "max_drawdown_ret_pct",
    "giveback_from_peak_pct",
    "partial_taken",
    "runner_preserved_40d",
    "runner_cut_early_40d",
]

RANKER_USECOLS = [
    "opportunity_id",
    "feature_version",
    "feature_hash",
    "fold",
    "oof_available",
    "target_trade_worthy",
    "target_runner",
    "target_fail_risk",
    "baseline_kumo_rank_score",
    "baseline_kumo_score",
    "baseline_rule_score",
    "model_trade_worthy_score",
    "model_runner_score",
    "model_combined_score",
]

OUTPUT_COLUMNS = [
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
    "entry_assumption_count",
    "triggered_entry_count",
    "strict_triggered_entry_count",
    "bad_triggered_entry_count",
    "best_entry_assumption",
    "best_entry_date",
    "best_entry_time",
    "best_entry_price",
    "best_entry_ret_20d_close_pct",
    "best_entry_mfe_20d_pct",
    "best_entry_mae_20d_pct",
    "best_entry_t4_s2_20d_outcome",
    "best_entry_t8_s4_20d_outcome",
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
    "exit_policy_entry_assumption",
    "feature_version",
    "feature_hash",
    "oof_available",
    "target_trade_worthy",
    "target_runner",
    "target_fail_risk",
    "baseline_kumo_rank_score",
    "baseline_kumo_score",
    "baseline_rule_score",
    "model_trade_worthy_score",
    "model_runner_score",
    "model_combined_score",
]

STRICT_ENTRY_ASSUMPTIONS = {"first_hour_confirm", "prior_session_high_breakout", "pullback_1pct_reclaim"}
CLASSIFICATION_VERSION = "scanner_trade_universe_v1"


@dataclass(frozen=True)
class BuildConfig:
    panel: str
    entry_labels: str
    exit_labels: str
    ranker_predictions: str
    output_dir: str
    limit: int | None
    classification_version: str


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", type=Path, default=DEFAULT_PANEL)
    parser.add_argument("--entry-labels", type=Path, default=DEFAULT_ENTRY_LABELS)
    parser.add_argument("--exit-labels", type=Path, default=DEFAULT_EXIT_LABELS)
    parser.add_argument("--ranker-predictions", type=Path, default=DEFAULT_RANKER)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--limit", type=int, default=None, help="Optional input opportunity limit for smoke runs.")
    return parser.parse_args()


def _read_csv(path: Path, *, usecols: list[str]) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    return pd.read_csv(path, usecols=lambda column: column in set(usecols), low_memory=False)


def _write_csv_gz(frame: pd.DataFrame, path: Path) -> None:
    with gzip.open(path, "wt", encoding="utf-8", newline="") as fh:
        frame.to_csv(fh, index=False)


def _clean_symbol(value: Any) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip().upper()


def _clean_date(value: Any) -> str:
    if pd.isna(value):
        return ""
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return ""
    return parsed.strftime("%Y-%m-%d")


def _bool_series(series: pd.Series | None, *, index: pd.Index) -> pd.Series:
    if series is None:
        return pd.Series(False, index=index)
    return series.astype(str).str.strip().str.lower().isin({"1", "true", "yes", "y"})


def _bool_value(value: Any) -> bool:
    if pd.isna(value):
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _num(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round(value: Any, digits: int = 4) -> float | None:
    parsed = _num(value)
    if parsed is None:
        return None
    return round(parsed, digits)


def _is_available_path(value: Any) -> bool:
    return str(value or "").startswith("available")


def _first_non_empty(values: pd.Series) -> Any:
    for value in values:
        if pd.isna(value):
            continue
        text = str(value).strip()
        if text and text.lower() != "nan":
            return value
    return None


def read_entry_labels(path: Path, *, limit: int | None = None) -> pd.DataFrame:
    frame = _read_csv(path, usecols=ENTRY_USECOLS)
    frame["scan_date"] = frame["scan_date"].map(_clean_date)
    frame["symbol"] = frame["symbol"].map(_clean_symbol)
    frame = frame[(frame["scan_date"] != "") & (frame["symbol"] != "")].copy()
    frame["opportunity_id"] = frame.get("opportunity_id", frame["scan_date"] + "|" + frame["symbol"])
    frame["opportunity_id"] = frame["opportunity_id"].fillna(frame["scan_date"] + "|" + frame["symbol"])
    if limit is not None:
        keep_ids = frame["opportunity_id"].drop_duplicates().head(limit)
        frame = frame[frame["opportunity_id"].isin(set(keep_ids))].copy()
    for column in BOOL_COLUMNS:
        if column in frame.columns:
            frame[column] = _bool_series(frame[column], index=frame.index)
    for column in [
        "kumo_rank_by_score",
        "kumo_score",
        "george_rank",
        "george_watchlist_rank",
        "label_entry_price",
        "label_ret_20d_close_pct",
        "label_mfe_20d_pct",
        "label_mae_20d_pct",
    ]:
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.reset_index(drop=True)


def read_panel_metadata(path: Path) -> pd.DataFrame:
    frame = _read_csv(path, usecols=PANEL_USECOLS)
    frame["scan_date"] = frame["scan_date"].map(_clean_date)
    frame["symbol"] = frame["symbol"].map(_clean_symbol)
    frame = frame[(frame["scan_date"] != "") & (frame["symbol"] != "")].copy()
    frame["opportunity_id"] = frame["scan_date"] + "|" + frame["symbol"]
    return frame.drop_duplicates("opportunity_id", keep="first")


def read_optional_frame(path: Path, *, usecols: list[str]) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return _read_csv(path, usecols=usecols)


def _eligible_entry_rows(group: pd.DataFrame) -> pd.DataFrame:
    triggered = group["label_triggered"] if "label_triggered" in group.columns else pd.Series(False, index=group.index)
    available = group["label_path_status"].map(_is_available_path)
    return group[triggered & available].copy()


def select_best_entry(group: pd.DataFrame) -> pd.Series | None:
    eligible = _eligible_entry_rows(group)
    if eligible.empty:
        return None
    ranked = eligible.sort_values(
        by=["label_ret_20d_close_pct", "label_mfe_20d_pct", "label_mae_20d_pct"],
        ascending=[False, False, False],
        na_position="last",
    )
    return ranked.iloc[0]


def _next_open_entry(group: pd.DataFrame) -> pd.Series | None:
    next_open = group[group["entry_assumption"].astype(str).eq("next_open")]
    if next_open.empty:
        return None
    return next_open.iloc[0]


def aggregate_entries(entries: pd.DataFrame) -> pd.DataFrame:
    base_columns = [
        "opportunity_id",
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
    base = entries[base_columns].drop_duplicates("opportunity_id", keep="first").copy()

    available = entries["label_path_status"].map(_is_available_path)
    eligible = entries[entries["label_triggered"].astype(bool) & available].copy()
    assumption_count = entries.groupby("opportunity_id")["entry_assumption"].nunique().rename("entry_assumption_count")
    triggered_count = eligible.groupby("opportunity_id").size().rename("triggered_entry_count")
    strict_count = (
        eligible[eligible["entry_assumption"].astype(str).isin(STRICT_ENTRY_ASSUMPTIONS)]
        .groupby("opportunity_id")
        .size()
        .rename("strict_triggered_entry_count")
    )
    bad_count = (
        eligible[eligible["label_bad_trade_20d"].astype(bool)]
        .groupby("opportunity_id")
        .size()
        .rename("bad_triggered_entry_count")
    )
    counts = pd.concat([assumption_count, triggered_count, strict_count, bad_count], axis=1).fillna(0).astype(int)
    base = base.merge(counts.reset_index(), on="opportunity_id", how="left")
    for column in [
        "entry_assumption_count",
        "triggered_entry_count",
        "strict_triggered_entry_count",
        "bad_triggered_entry_count",
    ]:
        base[column] = base[column].fillna(0).astype(int)

    if eligible.empty:
        best = pd.DataFrame(columns=["opportunity_id"])
    else:
        best = (
            eligible.sort_values(
                by=["opportunity_id", "label_ret_20d_close_pct", "label_mfe_20d_pct", "label_mae_20d_pct"],
                ascending=[True, False, False, False],
                na_position="last",
            )
            .drop_duplicates("opportunity_id", keep="first")
            .copy()
        )
    best_columns = {
        "entry_assumption": "best_entry_assumption",
        "label_entry_date": "best_entry_date",
        "label_entry_time": "best_entry_time",
        "label_entry_price": "best_entry_price",
        "label_ret_20d_close_pct": "best_entry_ret_20d_close_pct",
        "label_mfe_20d_pct": "best_entry_mfe_20d_pct",
        "label_mae_20d_pct": "best_entry_mae_20d_pct",
        "label_t4_s2_20d_outcome": "best_entry_t4_s2_20d_outcome",
        "label_t8_s4_20d_outcome": "best_entry_t8_s4_20d_outcome",
        "label_runner_candidate_20d": "best_entry_runner_candidate_20d",
        "label_normal_winner_20d": "best_entry_normal_winner_20d",
        "label_bad_trade_20d": "best_entry_bad_trade_20d",
        "label_outcome_20d": "best_entry_outcome_20d",
    }
    best = best[["opportunity_id", *best_columns.keys()]].rename(columns=best_columns)
    base = base.merge(best, on="opportunity_id", how="left")

    next_open = entries[entries["entry_assumption"].astype(str).eq("next_open")].copy()
    next_open_columns = {
        "label_triggered": "next_open_triggered",
        "label_ret_20d_close_pct": "next_open_ret_20d_close_pct",
        "label_mfe_20d_pct": "next_open_mfe_20d_pct",
        "label_mae_20d_pct": "next_open_mae_20d_pct",
        "label_bad_trade_20d": "next_open_bad_trade_20d",
    }
    next_open = (
        next_open.drop_duplicates("opportunity_id", keep="first")[["opportunity_id", *next_open_columns.keys()]]
        .rename(columns=next_open_columns)
        .copy()
    )
    base = base.merge(next_open, on="opportunity_id", how="left")

    defaults: dict[str, Any] = {
        "best_entry_assumption": "",
        "best_entry_date": "",
        "best_entry_time": "",
        "best_entry_price": None,
        "best_entry_ret_20d_close_pct": None,
        "best_entry_mfe_20d_pct": None,
        "best_entry_mae_20d_pct": None,
        "best_entry_t4_s2_20d_outcome": "",
        "best_entry_t8_s4_20d_outcome": "",
        "best_entry_runner_candidate_20d": False,
        "best_entry_normal_winner_20d": False,
        "best_entry_bad_trade_20d": False,
        "best_entry_outcome_20d": "no_realistic_entry",
        "next_open_triggered": False,
        "next_open_ret_20d_close_pct": None,
        "next_open_mfe_20d_pct": None,
        "next_open_mae_20d_pct": None,
        "next_open_bad_trade_20d": False,
    }
    for column, value in defaults.items():
        if column not in base.columns:
            base[column] = value
        elif value is None:
            continue
        else:
            base.loc[base[column].isna(), column] = value
    for column in [
        "best_entry_runner_candidate_20d",
        "best_entry_normal_winner_20d",
        "best_entry_bad_trade_20d",
        "next_open_triggered",
        "next_open_bad_trade_20d",
    ]:
        base[column] = base[column].astype(bool)
    return base


def _rank_exit_rows(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.sort_values(
        by=["total_equity_ret_40d_pct", "realized_ret_pct", "exposure_sessions"],
        ascending=[False, False, True],
        na_position="last",
    )


def aggregate_exits(exits: pd.DataFrame) -> pd.DataFrame:
    if exits.empty:
        return pd.DataFrame(columns=["opportunity_id"])
    for column in ["total_equity_ret_40d_pct", "realized_ret_pct", "exposure_sessions"]:
        if column in exits.columns:
            exits[column] = pd.to_numeric(exits[column], errors="coerce")
    base = exits[["opportunity_id"]].drop_duplicates().copy()
    base["exit_policy_entry_assumption"] = "next_open_path_labels"
    available = exits[exits["total_equity_ret_40d_pct"].notna()].copy()

    deployable = available[
        available["deployability"].astype(str).isin({"lean_and_qc_ready", "lean_and_qc_ready_if_sector_proxy_available"})
        & ~available["policy_status"].astype(str).eq("missing_policy_data")
    ].copy()
    if not deployable.empty:
        best_deployable = _rank_exit_rows(deployable).drop_duplicates("opportunity_id", keep="first")
        best_deployable = best_deployable[
            [
                "opportunity_id",
                "policy_id",
                "exit_reason",
                "policy_status",
                "total_equity_ret_40d_pct",
                "realized_ret_pct",
                "exposure_sessions",
                "runner_preserved_40d",
            ]
        ].rename(
            columns={
                "policy_id": "best_deployable_exit_policy_id",
                "exit_reason": "best_deployable_exit_reason",
                "policy_status": "best_deployable_exit_status",
                "total_equity_ret_40d_pct": "best_deployable_total_equity_ret_40d_pct",
                "realized_ret_pct": "best_deployable_realized_ret_pct",
                "exposure_sessions": "best_deployable_exposure_sessions",
                "runner_preserved_40d": "best_deployable_runner_preserved_40d",
            }
        )
        base = base.merge(best_deployable, on="opportunity_id", how="left")

    if not available.empty:
        oracle = _rank_exit_rows(available).drop_duplicates("opportunity_id", keep="first")
        oracle = oracle[["opportunity_id", "policy_id", "total_equity_ret_40d_pct"]].rename(
            columns={
                "policy_id": "oracle_best_exit_policy_id",
                "total_equity_ret_40d_pct": "oracle_best_total_equity_ret_40d_pct",
            }
        )
        base = base.merge(oracle, on="opportunity_id", how="left")

    hold = available[available["policy_id"].astype(str).eq("hold_40d_mtm")].drop_duplicates("opportunity_id", keep="first")
    if not hold.empty:
        hold = hold[["opportunity_id", "total_equity_ret_40d_pct"]].rename(
            columns={"total_equity_ret_40d_pct": "hold_40d_total_equity_ret_40d_pct"}
        )
        base = base.merge(hold, on="opportunity_id", how="left")

    defaults: dict[str, Any] = {
        "best_deployable_exit_policy_id": "",
        "best_deployable_exit_reason": "",
        "best_deployable_exit_status": "",
        "best_deployable_total_equity_ret_40d_pct": None,
        "best_deployable_realized_ret_pct": None,
        "best_deployable_exposure_sessions": None,
        "best_deployable_runner_preserved_40d": False,
        "oracle_best_exit_policy_id": "",
        "oracle_best_total_equity_ret_40d_pct": None,
        "hold_40d_total_equity_ret_40d_pct": None,
    }
    for column, value in defaults.items():
        if column not in base.columns:
            base[column] = value
        elif value is not None:
            base[column] = base[column].fillna(value)
    base["best_deployable_runner_preserved_40d"] = _bool_series(
        base["best_deployable_runner_preserved_40d"], index=base.index
    )
    for column in [
        "best_deployable_total_equity_ret_40d_pct",
        "best_deployable_realized_ret_pct",
        "best_deployable_exposure_sessions",
        "oracle_best_total_equity_ret_40d_pct",
        "hold_40d_total_equity_ret_40d_pct",
    ]:
        base[column] = pd.to_numeric(base[column], errors="coerce").round(4)
    return base


def read_ranker(path: Path) -> pd.DataFrame:
    ranker = read_optional_frame(path, usecols=RANKER_USECOLS)
    if ranker.empty:
        return ranker
    for column in ["oof_available", "target_trade_worthy", "target_runner", "target_fail_risk"]:
        if column in ranker.columns:
            ranker[column] = _bool_series(ranker[column], index=ranker.index)
    return ranker.drop_duplicates("opportunity_id", keep="first")


def add_source_buckets(universe: pd.DataFrame) -> pd.DataFrame:
    frame = universe.copy()
    frame["george_signal_seen"] = frame["george_scanner_positive"].astype(bool) | frame["george_watchlist"].astype(bool)
    frame["kumo_signal_seen"] = frame["kumo_scanner"].astype(bool)
    frame["george_video_only_context"] = frame["george_video_mention"].astype(bool) & ~frame["george_signal_seen"]
    frame["both_george_and_kumo"] = frame["george_signal_seen"] & frame["kumo_signal_seen"]

    def bucket(row: pd.Series) -> str:
        if bool(row["both_george_and_kumo"]):
            return "both_george_and_kumo"
        if bool(row["george_signal_seen"]) and not bool(row["kumo_signal_seen"]):
            return "george_only"
        if bool(row["kumo_signal_seen"]) and not bool(row["george_signal_seen"]):
            if bool(row["george_video_only_context"]):
                return "kumo_with_george_video_context"
            return "kumo_only"
        if bool(row["george_video_only_context"]):
            return "george_video_only_context"
        return "other"

    frame["source_bucket"] = frame.apply(bucket, axis=1)
    return frame


def classify_trade(row: pd.Series) -> tuple[str, str]:
    reasons: list[str] = []
    visible_signal = bool(row.get("george_signal_seen", False)) or bool(row.get("kumo_signal_seen", False))
    triggered_entries = int(row.get("triggered_entry_count", 0) or 0)
    best_ret = _num(row.get("best_entry_ret_20d_close_pct"))
    best_mfe = _num(row.get("best_entry_mfe_20d_pct"))
    best_mae = _num(row.get("best_entry_mae_20d_pct"))
    deployable_total = _num(row.get("best_deployable_exit_total_equity_ret_40d_pct"))
    target_before_stop = row.get("best_entry_t4_s2_20d_outcome") == "target_before_stop"
    stop_before_target = row.get("best_entry_t4_s2_20d_outcome") == "stop_before_target"
    best_bad = bool(row.get("best_entry_bad_trade_20d", False))
    best_runner = bool(row.get("best_entry_runner_candidate_20d", False))
    best_normal = bool(row.get("best_entry_normal_winner_20d", False))

    if not visible_signal:
        reasons.append("no_scanner_or_watchlist_signal")
    if triggered_entries == 0:
        reasons.append("no_realistic_entry_triggered")
        return "watch", ";".join(reasons)
    reasons.append("realistic_entry_triggered")

    if best_bad:
        reasons.append("best_entry_bad_trade")
    if best_mae is not None and best_mae <= -8:
        reasons.append("mae20_le_minus8")
    if stop_before_target:
        reasons.append("stop_before_target4_2")
    if deployable_total is not None and deployable_total <= -6:
        reasons.append("deployable_exit_total_le_minus6")

    if any(
        [
            best_bad,
            best_mae is not None and best_mae <= -8,
            stop_before_target,
            deployable_total is not None and deployable_total <= -6,
        ]
    ):
        return "bad", ";".join(reasons)

    if best_ret is not None and best_ret >= 4:
        reasons.append("ret20_ge_4")
    if best_mfe is not None and best_mfe >= 8:
        reasons.append("mfe20_ge_8")
    if target_before_stop:
        reasons.append("target4_before_stop2")
    if deployable_total is not None and deployable_total >= 4:
        reasons.append("deployable_exit_total_ge_4")
    if best_runner:
        reasons.append("runner_candidate")
    if best_normal:
        reasons.append("normal_winner")

    favorable_path = any(
        [
            best_ret is not None and best_ret >= 4,
            best_mfe is not None and best_mfe >= 8,
            target_before_stop,
            deployable_total is not None and deployable_total >= 4,
        ]
    )
    if visible_signal and favorable_path and (best_runner or best_normal or target_before_stop):
        return "optimal", ";".join(reasons)
    return "watch", ";".join(reasons)


def add_trade_classification(universe: pd.DataFrame) -> pd.DataFrame:
    frame = universe.copy()
    classifications = frame.apply(classify_trade, axis=1)
    frame["trade_bucket"] = [item[0] for item in classifications]
    frame["reason_codes"] = [item[1] for item in classifications]
    frame["classification_version"] = CLASSIFICATION_VERSION
    return frame


def build_trade_universe(
    *,
    entries: pd.DataFrame,
    panel: pd.DataFrame,
    exits: pd.DataFrame,
    ranker: pd.DataFrame,
) -> pd.DataFrame:
    universe = aggregate_entries(entries)
    if not panel.empty:
        universe = universe.merge(panel.drop(columns=["scan_date", "symbol"], errors="ignore"), on="opportunity_id", how="left")
    exit_summary = aggregate_exits(exits)
    if not exit_summary.empty:
        universe = universe.merge(exit_summary, on="opportunity_id", how="left")
    else:
        universe["exit_policy_entry_assumption"] = ""
    if not ranker.empty:
        universe = universe.merge(ranker, on="opportunity_id", how="left")
    universe = add_source_buckets(universe)
    universe = add_trade_classification(universe)
    for column in OUTPUT_COLUMNS:
        if column not in universe.columns:
            universe[column] = None
    return universe[OUTPUT_COLUMNS + ["classification_version"]].sort_values(["scan_date", "symbol"]).reset_index(drop=True)


def source_summary(universe: pd.DataFrame) -> pd.DataFrame:
    frame = universe.copy()
    frame["is_optimal"] = frame["trade_bucket"].eq("optimal")
    frame["is_bad"] = frame["trade_bucket"].eq("bad")
    frame["is_watch"] = frame["trade_bucket"].eq("watch")
    frame["has_trigger"] = frame["triggered_entry_count"].fillna(0).astype(int).gt(0)
    grouped = frame.groupby("source_bucket", dropna=False)
    summary = grouped.agg(
        opportunities=("opportunity_id", "count"),
        triggered_rows=("has_trigger", "sum"),
        optimal_rows=("is_optimal", "sum"),
        bad_rows=("is_bad", "sum"),
        watch_rows=("is_watch", "sum"),
        avg_best_entry_ret20_pct=("best_entry_ret_20d_close_pct", "mean"),
        avg_best_deployable_exit_total40_pct=("best_deployable_total_equity_ret_40d_pct", "mean"),
    ).reset_index()
    for column, numerator in [
        ("trigger_rate_pct", "triggered_rows"),
        ("optimal_pct", "optimal_rows"),
        ("bad_pct", "bad_rows"),
        ("watch_pct", "watch_rows"),
    ]:
        summary[column] = (summary[numerator] / summary["opportunities"] * 100.0).round(3)
    numeric_cols = ["avg_best_entry_ret20_pct", "avg_best_deployable_exit_total40_pct"]
    summary[numeric_cols] = summary[numeric_cols].round(4)
    return summary.sort_values(["opportunities", "source_bucket"], ascending=[False, True]).reset_index(drop=True)


def _bucket_rows(universe: pd.DataFrame, *, bucket: str, limit: int | None = None) -> pd.DataFrame:
    frame = universe[universe["trade_bucket"].eq(bucket)].copy()
    if frame.empty:
        return frame
    sort_columns = ["best_entry_ret_20d_close_pct", "best_entry_mfe_20d_pct"]
    ascending = [bucket == "bad", bucket == "bad"]
    if bucket == "bad":
        sort_columns = ["best_entry_mae_20d_pct", "best_deployable_total_equity_ret_40d_pct"]
        ascending = [True, True]
    sorted_frame = frame.sort_values(sort_columns, ascending=ascending, na_position="last")
    if limit is not None:
        return sorted_frame.head(limit)
    return sorted_frame


def _markdown_table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "_No rows._"
    text_frame = frame.fillna("").astype(str)
    columns = list(text_frame.columns)
    header = "| " + " | ".join(columns) + " |"
    separator = "| " + " | ".join(["---"] * len(columns)) + " |"
    rows = ["| " + " | ".join(str(row[column]) for column in columns) + " |" for _, row in text_frame.iterrows()]
    return "\n".join([header, separator, *rows])


def write_report(
    *,
    universe: pd.DataFrame,
    summary: pd.DataFrame,
    output_dir: Path,
    config: BuildConfig,
) -> None:
    bucket_counts = universe["trade_bucket"].value_counts().rename_axis("trade_bucket").reset_index(name="rows")
    lines = [
        "# Scanner Trade Universe #482",
        "",
        "This report synthesizes George/Kumo scanner opportunities with realistic-entry replay,",
        "exit-policy outcomes, and ranker scores.",
        "",
        "## Inputs",
        "",
        f"- Panel: `{config.panel}`",
        f"- Entry labels: `{config.entry_labels}`",
        f"- Exit labels: `{config.exit_labels}`",
        f"- Ranker predictions: `{config.ranker_predictions}`",
        "",
        "## Coverage",
        "",
        f"- Opportunities: `{len(universe)}`",
        f"- Dates: `{universe['scan_date'].nunique()}`",
        f"- Symbols: `{universe['symbol'].nunique()}`",
        f"- Classification version: `{config.classification_version}`",
        "",
        "## Trade Buckets",
        "",
        _markdown_table(bucket_counts),
        "",
        "## Source Summary",
        "",
        _markdown_table(summary),
        "",
        "## Caveats",
        "",
        "- `best_entry_*` is selected from #465 realistic entry replay assumptions.",
        "- `best_deployable_exit_*` currently comes from #466 exit-policy labels, which were built",
        "  on next-open path labels. The artifact marks this with `exit_policy_entry_assumption`.",
        "- `optimal` and `bad` are research labels, not a live trading rule.",
    ]
    (output_dir / "scanner_trade_universe_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_readme(output_dir: Path) -> None:
    text = (
        "# scanner_trade_universe_482/\n\n"
        "Generated scanner trade-universe artifacts for issue #482.\n"
        "Keep compact CSV summaries, manifest, and reports here.\n"
        "Do not place raw intraday data or bulky sweep run directories here.\n"
    )
    (output_dir / "README.md").write_text(text, encoding="utf-8")


def build(config: BuildConfig) -> dict[str, Any]:
    output_dir = Path(config.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    entries = read_entry_labels(Path(config.entry_labels), limit=config.limit)
    panel = read_panel_metadata(Path(config.panel))
    exits = read_optional_frame(Path(config.exit_labels), usecols=EXIT_USECOLS)
    ranker = read_ranker(Path(config.ranker_predictions))

    universe = build_trade_universe(entries=entries, panel=panel, exits=exits, ranker=ranker)
    summary = source_summary(universe)
    optimal = _bucket_rows(universe, bucket="optimal")
    bad = _bucket_rows(universe, bucket="bad")

    _write_csv_gz(universe, output_dir / "scanner_trade_universe.csv.gz")
    optimal.to_csv(output_dir / "optimal_trades.csv", index=False)
    bad.to_csv(output_dir / "bad_trades.csv", index=False)
    summary.to_csv(output_dir / "source_summary.csv", index=False)
    write_readme(output_dir)
    write_report(universe=universe, summary=summary, output_dir=output_dir, config=config)

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "issue": "https://github.com/FALK-BRAUER/kumo-qc/issues/482",
        "config": asdict(config),
        "outputs": {
            "scanner_trade_universe.csv.gz": {"rows": int(len(universe))},
            "optimal_trades.csv": {"rows": int(len(optimal))},
            "bad_trades.csv": {"rows": int(len(bad))},
            "source_summary.csv": {"rows": int(len(summary))},
            "scanner_trade_universe_report.md": {},
        },
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    args = _args()
    config = BuildConfig(
        panel=str(args.panel),
        entry_labels=str(args.entry_labels),
        exit_labels=str(args.exit_labels),
        ranker_predictions=str(args.ranker_predictions),
        output_dir=str(args.output_dir),
        limit=args.limit,
        classification_version=CLASSIFICATION_VERSION,
    )
    manifest = build(config)
    print(json.dumps(manifest["outputs"], indent=2))


if __name__ == "__main__":
    main()
