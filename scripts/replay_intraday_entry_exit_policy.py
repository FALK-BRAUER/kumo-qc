"""Replay #490 intraday policy decisions into trade-level economics."""
from __future__ import annotations

import argparse
import gzip
import io
import json
import sys
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import build_intraday_decision_panel as decision_panel  # noqa: E402
from scripts import train_intraday_entry_exit_policy as policy_train  # noqa: E402

DEFAULT_PANEL = policy_train.DEFAULT_PANEL
DEFAULT_MODEL = policy_train.DEFAULT_OUTPUT_DIR / "model_artifact.json"
DEFAULT_DUAL_HEAD_MODEL = ROOT / "sweeps" / "reports" / "intraday_entry_exit_policy_490_dual_head" / "model_artifact.json"
DEFAULT_PARQUET_ROOT = decision_panel.DEFAULT_PARQUET_ROOT
DEFAULT_OUTPUT_DIR = ROOT / "sweeps" / "reports" / "intraday_policy_replay_490"
DEFAULT_SCAN_TIME_PREDICTIONS = ROOT / "sweeps" / "reports" / "scan_time_scanner_ranker_492" / "oof_predictions.csv.gz"
REPLAY_VERSION = "intraday_policy_replay_490_v1"
ENTRY_POLICY_V2_VARIANT = "entry_policy_v2"
ENTRY_POLICY_V3_VARIANT = "entry_policy_v3"
DUAL_HEAD_VARIANT = "dual_head_policy"
VARIANTS = ("model_policy", ENTRY_POLICY_V2_VARIANT, ENTRY_POLICY_V3_VARIANT, DUAL_HEAD_VARIANT, "baseline_rules")
MODEL_MANAGED_VARIANTS = {"model_policy", ENTRY_POLICY_V2_VARIANT, ENTRY_POLICY_V3_VARIANT, DUAL_HEAD_VARIANT}
V1_MANAGED_VARIANTS = {"model_policy", ENTRY_POLICY_V2_VARIANT, ENTRY_POLICY_V3_VARIANT}
EXIT_ACTIONS = {"exit_loser", "scratch_or_reduce", "protect_profit"}
CHECKPOINT_ORDER = {name: idx for idx, (name, _time_text) in enumerate(decision_panel.CHECKPOINTS)}

ENTRY_V2_MAX_AVOID_PROB = 0.35
ENTRY_V2_MAX_RISK_ENTER_GAP = 0.10
ENTRY_V2_MIN_ENTER_PROB = 0.0
ENTRY_V2_MIN_RETURN_FROM_OPEN_PCT = 0.0
ENTRY_V2_MIN_MAE_FROM_OPEN_PCT = -3.0

ENTRY_V3_MAX_AVOID_PROB = 0.40
ENTRY_V3_MIN_RETURN_FROM_OPEN_PCT = 0.0
ENTRY_V3_MIN_MAE_FROM_OPEN_PCT = -3.0
ENTRY_V3_MIN_SCAN_OPTIMAL_SCORE = 0.15
ENTRY_V3_MAX_SCAN_BAD_RISK_SCORE = -0.20
DUAL_ENTRY_MAX_BAD_RISK_PROB = 0.58
DUAL_ENTRY_MIN_WINNER_PROB = 0.48
DUAL_ENTRY_MIN_READY_PROB = 0.45
DUAL_ENTRY_STRONG_WINNER_PROB = 0.60
DUAL_ENTRY_MAX_STRONG_WINNER_BAD_RISK_PROB = 0.52
DUAL_MGMT_EXIT_RISK_PROB = 0.62
DUAL_MGMT_RUNNER_PRESERVE_PROB = 0.58
SCAN_TIME_PRIOR_COLUMNS = (
    "oof_available_492",
    "model_492_optimal_score",
    "model_492_bad_risk_score",
    "model_492_risk_avoidance_score",
    "model_492_combined_score",
)

PROMOTION_MAX_BAD_ENTRY_RATE_DELTA = -15.0
PROMOTION_MIN_OPTIMAL_ENTRY_RATE = 70.0
PROMOTION_MIN_RUNNER_ENTRY_RATE = 72.0


@dataclass(frozen=True)
class ReplayConfig:
    panel: str
    model_artifact: str
    dual_head_model_artifact: str
    parquet_root: str
    scan_time_predictions: str
    output_dir: str
    limit_opportunities: int | None
    variants: tuple[str, ...]


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", type=Path, default=DEFAULT_PANEL)
    parser.add_argument("--model-artifact", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--dual-head-model-artifact", type=Path, default=DEFAULT_DUAL_HEAD_MODEL)
    parser.add_argument("--parquet-root", type=Path, default=DEFAULT_PARQUET_ROOT)
    parser.add_argument("--scan-time-predictions", type=Path, default=DEFAULT_SCAN_TIME_PREDICTIONS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--limit-opportunities", type=int, default=None)
    parser.add_argument("--variants", nargs="+", choices=VARIANTS, default=list(VARIANTS))
    return parser.parse_args()


def _num(value: Any, default: float | None = None) -> float | None:
    if value is None or pd.isna(value):
        return default
    return float(value)


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


def _bool(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def read_model_artifact(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(path)
    artifact = json.loads(path.read_text(encoding="utf-8"))
    if "policies" not in artifact:
        raise ValueError(f"model artifact missing policies: {path}")
    return artifact


def fold_model_for_date(policy_artifact: dict[str, Any], scan_date: str) -> dict[str, Any] | None:
    day = str(scan_date)[:10]
    for fold in policy_artifact.get("fold_models", []):
        if str(fold["valid_start"]) <= day <= str(fold["valid_end"]):
            return fold
    return None


def _score_with_fold(frame: pd.DataFrame, policy_artifact: dict[str, Any], fold: dict[str, Any]) -> pd.DataFrame:
    feature_names = list(policy_artifact["feature_names"])
    enriched, built_features = policy_train.add_policy_features(frame)
    if built_features != feature_names:
        raise ValueError("policy replay feature list does not match #490 model artifact")
    x_raw = policy_train.build_feature_matrix(enriched, feature_names)
    standardizer = policy_train.Standardizer(
        mean=np.array(fold["standardizer"]["mean"], dtype=float),
        scale=np.array(fold["standardizer"]["scale"], dtype=float),
    )
    model = policy_train.SoftmaxModel(
        coef=np.array(fold["coef"], dtype=float),
        intercept=np.array(fold["intercept"], dtype=float),
        classes=tuple(policy_artifact["classes"]),
    )
    probs = policy_train.predict_proba(model, policy_train.apply_standardizer(x_raw, standardizer))
    pred_idx = probs.argmax(axis=1)
    scored = frame.copy()
    scored["policy_oof_available"] = True
    scored["policy_fold"] = int(fold["fold"])
    scored["policy_action"] = [model.classes[idx] for idx in pred_idx]
    scored["policy_confidence"] = probs.max(axis=1)
    for idx, action in enumerate(model.classes):
        scored[f"policy_prob_{action}"] = probs[:, idx]
    return scored


def score_policy_rows(frame: pd.DataFrame, artifact: dict[str, Any], policy_name: str) -> pd.DataFrame:
    policy_artifact = artifact["policies"][policy_name]
    scored_parts: list[pd.DataFrame] = []
    base = frame.copy()
    base["policy_oof_available"] = False
    base["policy_fold"] = np.nan
    base["policy_action"] = ""
    base["policy_confidence"] = np.nan
    for action in policy_artifact["classes"]:
        base[f"policy_prob_{action}"] = np.nan

    for fold in policy_artifact.get("fold_models", []):
        mask = base["scan_date"].astype(str).str.slice(0, 10).between(str(fold["valid_start"]), str(fold["valid_end"]))
        if not mask.any():
            continue
        scored_parts.append(_score_with_fold(base.loc[mask].copy(), policy_artifact, fold))
        base = base.loc[~mask].copy()
    if len(base):
        scored_parts.append(base)
    if not scored_parts:
        return base
    return pd.concat(scored_parts, ignore_index=True).sort_values(["opportunity_id", "checkpoint"]).reset_index(drop=True)


def add_head_scores(frame: pd.DataFrame, artifact: dict[str, Any], *, head_name: str, prefix: str) -> pd.DataFrame:
    scored = score_policy_rows(frame, artifact, head_name)
    policy_artifact = artifact["policies"][head_name]
    rename = {
        "policy_oof_available": f"{prefix}_available",
        "policy_fold": f"{prefix}_fold",
        "policy_action": f"{prefix}_action",
        "policy_confidence": f"{prefix}_confidence",
    }
    for action in policy_artifact["classes"]:
        rename[f"policy_prob_{action}"] = f"{prefix}_prob_{action}"
    return scored.rename(columns=rename)


def read_entry_rows(panel_path: Path, *, limit_opportunities: int | None = None) -> pd.DataFrame:
    panel = policy_train.read_panel(panel_path)
    entry = panel[panel["row_type"].eq("entry_decision")].copy()
    entry = entry[entry["entry_action_label"].isin(policy_train.ENTRY_ACTIONS)].copy()
    entry = entry[_bool_series(entry.get("intraday_available", pd.Series(False, index=entry.index)))].copy()
    entry["checkpoint_order"] = entry["checkpoint"].map(CHECKPOINT_ORDER).fillna(999).astype(int)
    entry["as_of_timestamp"] = entry["as_of_timestamp"].astype(str)
    if limit_opportunities is not None:
        keep = entry["opportunity_id"].drop_duplicates().head(limit_opportunities)
        entry = entry[entry["opportunity_id"].isin(set(keep))].copy()
    return entry.sort_values(["entry_session_date", "opportunity_id", "checkpoint_order"]).reset_index(drop=True)


def read_scan_time_predictions(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    frame = pd.read_csv(path)
    required = {"opportunity_id", *SCAN_TIME_PRIOR_COLUMNS}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"scan-time predictions missing columns: {missing}")
    return frame.loc[:, ["opportunity_id", *SCAN_TIME_PRIOR_COLUMNS]].drop_duplicates("opportunity_id")


def add_scan_time_priors(entry_rows: pd.DataFrame, scan_time_predictions_path: Path) -> pd.DataFrame:
    priors = read_scan_time_predictions(scan_time_predictions_path)
    out = entry_rows.merge(priors, on="opportunity_id", how="left")
    out["oof_available_492"] = _bool_series(out.get("oof_available_492", pd.Series(False, index=out.index)))
    for column in SCAN_TIME_PRIOR_COLUMNS:
        if column == "oof_available_492":
            continue
        out[column] = pd.to_numeric(out.get(column, pd.Series(np.nan, index=out.index)), errors="coerce")
    return out


def _bool_series(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip().str.lower().isin({"1", "true", "yes", "y"})


def add_entry_actions(entry_rows: pd.DataFrame, artifact: dict[str, Any], dual_head_artifact: dict[str, Any] | None = None) -> pd.DataFrame:
    scored = score_policy_rows(entry_rows, artifact, "entry_policy")
    scored = scored.rename(
        columns={
            "policy_oof_available": "entry_model_available",
            "policy_fold": "entry_model_fold",
            "policy_action": "entry_model_action",
            "policy_confidence": "entry_model_confidence",
        }
    )
    scored["baseline_entry_action"] = policy_train.baseline_entry_action(scored)
    scored["entry_policy_v2_action"] = entry_policy_v2_action(scored)
    scored["entry_policy_v3_action"] = entry_policy_v3_action(scored)
    if dual_head_artifact is not None:
        scored = add_dual_head_entry_actions(scored, dual_head_artifact)
    return scored


def entry_policy_v2_action(frame: pd.DataFrame) -> pd.Series:
    """Recover winners by overriding v1 avoid/wait only when model risk is not decisive."""
    model_action = frame.get("entry_model_action", pd.Series("", index=frame.index)).astype(str)
    baseline_action = frame.get("baseline_entry_action", policy_train.baseline_entry_action(frame)).astype(str)
    avoid_prob = pd.to_numeric(frame.get("policy_prob_avoid_bad_entry", pd.Series(np.nan, index=frame.index)), errors="coerce")
    enter_prob = pd.to_numeric(frame.get("policy_prob_enter_now", pd.Series(np.nan, index=frame.index)), errors="coerce")
    ret_from_open = pd.to_numeric(frame.get("return_from_open_pct", pd.Series(np.nan, index=frame.index)), errors="coerce")
    mae_from_open = pd.to_numeric(frame.get("mae_from_open_pct", pd.Series(np.nan, index=frame.index)), errors="coerce")

    winner_preserve = (
        baseline_action.eq("enter_now")
        & avoid_prob.le(ENTRY_V2_MAX_AVOID_PROB)
        & (avoid_prob - enter_prob).le(ENTRY_V2_MAX_RISK_ENTER_GAP)
        & enter_prob.ge(ENTRY_V2_MIN_ENTER_PROB)
        & ret_from_open.ge(ENTRY_V2_MIN_RETURN_FROM_OPEN_PCT)
        & mae_from_open.ge(ENTRY_V2_MIN_MAE_FROM_OPEN_PCT)
    )
    enter_now = model_action.eq("enter_now") | winner_preserve
    avoid = model_action.eq("avoid_bad_entry") & ~winner_preserve
    return pd.Series(np.select([enter_now, avoid], ["enter_now", "avoid_bad_entry"], default="wait"), index=frame.index)


def entry_policy_v3_action(frame: pd.DataFrame) -> pd.Series:
    """Extend v2 only for scan-confirmed winner recovery; never discard v2 winners."""
    model_action = frame.get("entry_model_action", pd.Series("", index=frame.index)).astype(str)
    baseline_action = frame.get("baseline_entry_action", policy_train.baseline_entry_action(frame)).astype(str)
    v2_action = frame.get("entry_policy_v2_action", entry_policy_v2_action(frame)).astype(str)
    avoid_prob = pd.to_numeric(frame.get("policy_prob_avoid_bad_entry", pd.Series(np.nan, index=frame.index)), errors="coerce")
    ret_from_open = pd.to_numeric(frame.get("return_from_open_pct", pd.Series(np.nan, index=frame.index)), errors="coerce")
    mae_from_open = pd.to_numeric(frame.get("mae_from_open_pct", pd.Series(np.nan, index=frame.index)), errors="coerce")
    scan_oof = _bool_series(frame.get("oof_available_492", pd.Series(False, index=frame.index)))
    scan_optimal_score = pd.to_numeric(frame.get("model_492_optimal_score", pd.Series(np.nan, index=frame.index)), errors="coerce")
    scan_bad_risk_score = pd.to_numeric(frame.get("model_492_bad_risk_score", pd.Series(np.nan, index=frame.index)), errors="coerce")

    scan_recovery = (
        v2_action.ne("enter_now")
        & baseline_action.eq("enter_now")
        & avoid_prob.le(ENTRY_V3_MAX_AVOID_PROB)
        & ret_from_open.ge(ENTRY_V3_MIN_RETURN_FROM_OPEN_PCT)
        & mae_from_open.ge(ENTRY_V3_MIN_MAE_FROM_OPEN_PCT)
        & scan_oof
        & scan_optimal_score.ge(ENTRY_V3_MIN_SCAN_OPTIMAL_SCORE)
        & scan_bad_risk_score.le(ENTRY_V3_MAX_SCAN_BAD_RISK_SCORE)
    )
    enter_now = v2_action.eq("enter_now") | scan_recovery
    avoid = model_action.eq("avoid_bad_entry") & ~enter_now
    return pd.Series(np.select([enter_now, avoid], ["enter_now", "avoid_bad_entry"], default="wait"), index=frame.index)


def add_dual_head_entry_actions(entry_rows: pd.DataFrame, dual_head_artifact: dict[str, Any]) -> pd.DataFrame:
    scored = entry_rows.copy()
    for head_name, prefix in (
        ("entry_bad_risk_head", "entry_bad_risk"),
        ("entry_winner_preservation_head", "entry_winner_preservation"),
        ("entry_ready_head", "entry_ready"),
    ):
        scored = add_head_scores(scored, dual_head_artifact, head_name=head_name, prefix=prefix)
    scored["dual_head_entry_action"] = dual_head_entry_action(scored)
    return scored


def dual_head_entry_action(frame: pd.DataFrame) -> pd.Series:
    bad_risk = pd.to_numeric(
        frame.get("entry_bad_risk_prob_bad_entry_risk", pd.Series(np.nan, index=frame.index)),
        errors="coerce",
    )
    winner = pd.to_numeric(
        frame.get("entry_winner_preservation_prob_winner_preserve", pd.Series(np.nan, index=frame.index)),
        errors="coerce",
    )
    ready = pd.to_numeric(
        frame.get("entry_ready_prob_entry_ready", pd.Series(np.nan, index=frame.index)),
        errors="coerce",
    )
    baseline_action = frame.get("baseline_entry_action", policy_train.baseline_entry_action(frame)).astype(str)
    all_heads_available = (
        frame.get("entry_bad_risk_available", pd.Series(False, index=frame.index)).astype(bool)
        & frame.get("entry_winner_preservation_available", pd.Series(False, index=frame.index)).astype(bool)
        & frame.get("entry_ready_available", pd.Series(False, index=frame.index)).astype(bool)
    )
    enter_by_heads = (
        all_heads_available
        & ready.ge(DUAL_ENTRY_MIN_READY_PROB)
        & winner.ge(DUAL_ENTRY_MIN_WINNER_PROB)
        & bad_risk.le(DUAL_ENTRY_MAX_BAD_RISK_PROB)
    )
    enter_by_preservation = (
        all_heads_available
        & baseline_action.eq("enter_now")
        & winner.ge(DUAL_ENTRY_STRONG_WINNER_PROB)
        & bad_risk.le(DUAL_ENTRY_MAX_STRONG_WINNER_BAD_RISK_PROB)
    )
    enter_now = enter_by_heads | enter_by_preservation
    avoid = all_heads_available & bad_risk.gt(DUAL_ENTRY_MAX_BAD_RISK_PROB) & ~enter_now
    return pd.Series(np.select([enter_now, avoid], ["enter_now", "avoid_bad_entry"], default="wait"), index=frame.index)


def entry_action_column(variant: str) -> str:
    if variant == "model_policy":
        return "entry_model_action"
    if variant == ENTRY_POLICY_V2_VARIANT:
        return "entry_policy_v2_action"
    if variant == ENTRY_POLICY_V3_VARIANT:
        return "entry_policy_v3_action"
    if variant == DUAL_HEAD_VARIANT:
        return "dual_head_entry_action"
    if variant == "baseline_rules":
        return "baseline_entry_action"
    raise ValueError(f"unknown replay variant: {variant}")


def selected_entries(entry_rows: pd.DataFrame, *, variant: str) -> pd.DataFrame:
    action_col = entry_action_column(variant)
    rows: list[dict[str, Any]] = []
    for opportunity_id, group in entry_rows.groupby("opportunity_id", sort=False):
        candidate = group.sort_values("checkpoint_order")
        eligible = bool(candidate["entry_model_available"].astype(bool).any())
        first = candidate.iloc[0].to_dict()
        row = {
            "variant": variant,
            "opportunity_id": opportunity_id,
            "scan_date": first.get("scan_date", ""),
            "entry_session_date": first.get("entry_session_date", ""),
            "symbol": first.get("symbol", ""),
            "scanner_source_bucket": first.get("scanner_source_bucket", ""),
            "trade_bucket": str(first.get("trade_bucket", "")).lower(),
            "oracle_best_entry_outcome_20d": first.get("oracle_best_entry_outcome_20d", ""),
            "oracle_best_deployable_total_equity_ret_40d_pct": first.get(
                "oracle_best_deployable_total_equity_ret_40d_pct", np.nan
            ),
            "kumo_rank_by_score": first.get("kumo_rank_by_score", np.nan),
            "kumo_score": first.get("kumo_score", np.nan),
            "george_signal_seen": bool(first.get("george_signal_seen")),
            "eligible": eligible,
            "entered": False,
            "skip_reason": "",
        }
        if not eligible:
            row["skip_reason"] = "no_oof_entry_model_for_date"
            rows.append(row)
            continue
        trigger = candidate[candidate[action_col].eq("enter_now")].head(1)
        if trigger.empty:
            row["skip_reason"] = "no_enter_now_signal"
            rows.append(row)
            continue
        entry = trigger.iloc[0].to_dict()
        row.update(
            {
                "entered": True,
                "entry_checkpoint": entry["checkpoint"],
                "entry_checkpoint_order": int(entry["checkpoint_order"]),
                "entry_timestamp": entry["as_of_timestamp"],
                "entry_price": _round(entry.get("current_price")),
                "entry_action": entry.get(action_col, ""),
                "entry_confidence": _round(entry.get("entry_model_confidence")),
                "entry_model_fold": entry.get("entry_model_fold", np.nan),
                "entry_policy_prob_avoid_bad_entry": _round(entry.get("policy_prob_avoid_bad_entry")),
                "entry_policy_prob_enter_now": _round(entry.get("policy_prob_enter_now")),
                "entry_scan_time_oof_available": bool(entry.get("oof_available_492", False)),
                "entry_scan_time_optimal_score": _round(entry.get("model_492_optimal_score")),
                "entry_scan_time_bad_risk_score": _round(entry.get("model_492_bad_risk_score")),
                "entry_scan_time_combined_score": _round(entry.get("model_492_combined_score")),
                "entry_dual_bad_risk_prob": _round(entry.get("entry_bad_risk_prob_bad_entry_risk")),
                "entry_dual_winner_preserve_prob": _round(entry.get("entry_winner_preservation_prob_winner_preserve")),
                "entry_dual_ready_prob": _round(entry.get("entry_ready_prob_entry_ready")),
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


def _read_day_symbol_bars(parquet_root: Path, day: str, symbols: Iterable[str]) -> dict[str, pd.DataFrame]:
    clean_symbols = {decision_panel._clean_symbol(symbol) for symbol in symbols if decision_panel._clean_symbol(symbol)}
    day_frame = decision_panel._read_day_bars(parquet_root, day, clean_symbols) if day else pd.DataFrame()
    return decision_panel._split_bars(day_frame) if not day_frame.empty else {}


def build_management_decision_rows(
    entry_rows: pd.DataFrame,
    selected: pd.DataFrame,
    *,
    parquet_root: Path,
) -> pd.DataFrame:
    selected = selected[selected["entered"]].copy()
    if selected.empty:
        return pd.DataFrame()
    entry_rows_by_opp = {opp: group.sort_values("checkpoint_order") for opp, group in entry_rows.groupby("opportunity_id", sort=False)}
    rows: list[dict[str, Any]] = []
    for entry_day, day_entries in selected.groupby("entry_session_date", sort=True):
        bars_by_symbol = _read_day_symbol_bars(parquet_root, str(entry_day), day_entries["symbol"].astype(str).tolist())
        for selection in day_entries.to_dict("records"):
            opportunity_id = selection["opportunity_id"]
            symbol = str(selection["symbol"])
            bars = bars_by_symbol.get(symbol, pd.DataFrame())
            entry_time = _ts(selection.get("entry_timestamp"))
            entry_price = _num(selection.get("entry_price"))
            if entry_time is None or entry_price is None or bars.empty:
                continue
            candidate_rows = entry_rows_by_opp[opportunity_id]
            entry_order = int(selection["entry_checkpoint_order"])
            max_order = int(candidate_rows["checkpoint_order"].max())
            if entry_order >= max_order:
                candidate_rows = candidate_rows[candidate_rows["checkpoint_order"].ge(entry_order)]
            else:
                candidate_rows = candidate_rows[candidate_rows["checkpoint_order"].gt(entry_order)]
            for _, candidate in candidate_rows.iterrows():
                as_of = _ts(candidate["as_of_timestamp"])
                if as_of is None:
                    continue
                row = candidate.to_dict()
                row.update(
                    {
                        "variant": selection["variant"],
                        "row_type": "position_management",
                        "entry_action_label": "",
                        "management_action_label": "",
                        "entry_checkpoint": selection["entry_checkpoint"],
                        "entry_checkpoint_order": selection["entry_checkpoint_order"],
                        "entry_timestamp": selection["entry_timestamp"],
                        "entry_price": selection["entry_price"],
                    }
                )
                row.update(
                    decision_panel.position_features(
                        bars=bars,
                        as_of=as_of,
                        entry_time=entry_time,
                        entry_price=float(entry_price),
                    )
                )
                rows.append(row)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(["variant", "opportunity_id", "checkpoint_order"]).reset_index(drop=True)


def add_dual_head_management_actions(management_rows: pd.DataFrame, dual_head_artifact: dict[str, Any]) -> pd.DataFrame:
    scored = management_rows.copy()
    for head_name, prefix in (
        ("management_exit_risk_head", "management_exit_risk"),
        ("management_runner_preservation_head", "management_runner_preservation"),
    ):
        scored = add_head_scores(scored, dual_head_artifact, head_name=head_name, prefix=prefix)
    scored["management_model_action"] = dual_head_management_action(scored)
    scored["management_model_available"] = (
        scored.get("management_exit_risk_available", pd.Series(False, index=scored.index)).astype(bool)
        & scored.get("management_runner_preservation_available", pd.Series(False, index=scored.index)).astype(bool)
    )
    scored["management_model_fold"] = scored.get("management_exit_risk_fold", pd.Series(np.nan, index=scored.index))
    scored["management_model_confidence"] = scored[
        ["management_exit_risk_confidence", "management_runner_preservation_confidence"]
    ].max(axis=1)
    return scored


def dual_head_management_action(frame: pd.DataFrame) -> pd.Series:
    exit_risk = pd.to_numeric(
        frame.get("management_exit_risk_prob_exit_risk", pd.Series(np.nan, index=frame.index)),
        errors="coerce",
    )
    preserve = pd.to_numeric(
        frame.get("management_runner_preservation_prob_runner_preserve", pd.Series(np.nan, index=frame.index)),
        errors="coerce",
    )
    ret = pd.to_numeric(frame.get("position_current_return_pct", pd.Series(np.nan, index=frame.index)), errors="coerce").fillna(0.0)
    drawdown = pd.to_numeric(frame.get("position_drawdown_from_peak_pct", pd.Series(np.nan, index=frame.index)), errors="coerce").fillna(0.0)
    available = (
        frame.get("management_exit_risk_available", pd.Series(False, index=frame.index)).astype(bool)
        & frame.get("management_runner_preservation_available", pd.Series(False, index=frame.index)).astype(bool)
    )
    do_not_cut_runner = available & preserve.ge(DUAL_MGMT_RUNNER_PRESERVE_PROB) & ret.ge(4.0)
    hold_winner = available & preserve.ge(DUAL_MGMT_RUNNER_PRESERVE_PROB) & ret.ge(1.0)
    protect_profit = available & exit_risk.ge(DUAL_MGMT_EXIT_RISK_PROB) & preserve.lt(DUAL_MGMT_RUNNER_PRESERVE_PROB) & ret.ge(3.0) & drawdown.ge(1.5)
    exit_loser = available & exit_risk.ge(DUAL_MGMT_EXIT_RISK_PROB) & preserve.lt(DUAL_MGMT_RUNNER_PRESERVE_PROB) & ret.lt(3.0)
    return pd.Series(
        np.select(
            [do_not_cut_runner, hold_winner, protect_profit, exit_loser],
            ["do_not_cut_runner", "hold_winner", "protect_profit", "exit_loser"],
            default="hold_or_wait",
        ),
        index=frame.index,
    )


def add_management_actions(
    management_rows: pd.DataFrame,
    artifact: dict[str, Any],
    dual_head_artifact: dict[str, Any] | None = None,
) -> pd.DataFrame:
    if management_rows.empty:
        return management_rows.copy()
    scored = management_rows.copy()
    scored["baseline_management_action"] = policy_train.baseline_management_action(scored)
    model_rows = scored[scored["variant"].isin(V1_MANAGED_VARIANTS)].copy()
    dual_rows = scored[scored["variant"].eq(DUAL_HEAD_VARIANT)].copy()
    other_rows = scored[~scored["variant"].isin(MODEL_MANAGED_VARIANTS)].copy()
    if not model_rows.empty:
        model_scored = score_policy_rows(model_rows, artifact, "management_policy").rename(
            columns={
                "policy_oof_available": "management_model_available",
                "policy_fold": "management_model_fold",
                "policy_action": "management_model_action",
                "policy_confidence": "management_model_confidence",
            }
        )
    else:
        model_scored = model_rows.assign(
            management_model_available=False,
            management_model_fold=np.nan,
            management_model_action="",
            management_model_confidence=np.nan,
        )
    if not dual_rows.empty and dual_head_artifact is not None:
        dual_scored = add_dual_head_management_actions(dual_rows, dual_head_artifact)
    else:
        dual_scored = dual_rows.assign(
            management_model_available=False,
            management_model_fold=np.nan,
            management_model_action="",
            management_model_confidence=np.nan,
        )
    if not other_rows.empty:
        other_rows = other_rows.assign(
            management_model_available=False,
            management_model_fold=np.nan,
            management_model_action="",
            management_model_confidence=np.nan,
        )
    return pd.concat([model_scored, dual_scored, other_rows], ignore_index=True).sort_values(
        ["variant", "opportunity_id", "checkpoint_order"]
    )


def finalize_candidate_outcomes(selected: pd.DataFrame, management_rows: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    management_by_key = {
        (variant, opportunity_id): group.sort_values("checkpoint_order")
        for (variant, opportunity_id), group in management_rows.groupby(["variant", "opportunity_id"], sort=False)
    } if not management_rows.empty else {}
    for selection in selected.to_dict("records"):
        row = dict(selection)
        if not row.get("entered"):
            rows.append(row)
            continue
        group = management_by_key.get((row["variant"], row["opportunity_id"]), pd.DataFrame())
        if group.empty:
            row.update({"entered": False, "skip_reason": "missing_intraday_bars_after_entry"})
            rows.append(row)
            continue
        if row["variant"] in MODEL_MANAGED_VARIANTS:
            action_col = "management_model_action"
            available_col = "management_model_available"
            action_rows = group[group[available_col].astype(bool)].copy()
        else:
            action_col = "baseline_management_action"
            action_rows = group.copy()
        exit_rows = action_rows[action_rows[action_col].isin(EXIT_ACTIONS)].head(1)
        if exit_rows.empty:
            exit_row = group.sort_values("checkpoint_order").tail(1).iloc[0]
            exit_action = "close_mark"
            exit_reason = "no_exit_action_before_close"
        else:
            exit_row = exit_rows.iloc[0]
            exit_action = str(exit_row[action_col])
            exit_reason = "policy_exit_action"
        row.update(
            {
                "exit_checkpoint": exit_row.get("checkpoint", ""),
                "exit_timestamp": exit_row.get("as_of_timestamp", ""),
                "exit_price": _round(exit_row.get("current_price")),
                "exit_action": exit_action,
                "exit_reason": exit_reason,
                "management_model_available": bool(exit_row.get("management_model_available", False)),
                "management_model_confidence": _round(exit_row.get("management_model_confidence")),
                "hold_minutes": _round(exit_row.get("position_minutes_since_entry"), 1),
                "realized_intraday_ret_pct": _round(exit_row.get("position_current_return_pct")),
                "mfe_intraday_pct": _round(exit_row.get("position_mfe_so_far_pct")),
                "mae_intraday_pct": _round(exit_row.get("position_mae_so_far_pct")),
                "drawdown_from_peak_pct": _round(exit_row.get("position_drawdown_from_peak_pct")),
            }
        )
        rows.append(row)
    out = pd.DataFrame(rows)
    out["is_bad_bucket"] = out["trade_bucket"].eq("bad")
    out["is_optimal_bucket"] = out["trade_bucket"].eq("optimal")
    out["is_runner_candidate"] = out["oracle_best_entry_outcome_20d"].astype(str).str.contains("runner", case=False, na=False)
    return out


def _rate(numerator: int | float, denominator: int | float) -> float:
    return round(100.0 * float(numerator) / float(denominator), 3) if denominator else 0.0


def _numeric_column(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame:
        return pd.Series(dtype=float)
    return pd.to_numeric(frame[column], errors="coerce")


def summary_metrics(outcomes: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for variant, group in outcomes.groupby("variant", sort=True):
        eligible = group[group["eligible"].astype(bool)].copy()
        trades = eligible[eligible["entered"].astype(bool)].copy()
        bad = eligible[eligible["is_bad_bucket"]]
        optimal = eligible[eligible["is_optimal_bucket"]]
        runners = eligible[eligible["is_runner_candidate"]]
        returns = _numeric_column(trades, "realized_intraday_ret_pct")
        mfe = _numeric_column(trades, "mfe_intraday_pct")
        mae = _numeric_column(trades, "mae_intraday_pct")
        rows.append(
            {
                "variant": variant,
                "eligible_candidates": int(len(eligible)),
                "trades": int(len(trades)),
                "entry_rate_pct": _rate(len(trades), len(eligible)),
                "bad_candidates": int(len(bad)),
                "bad_entries": int(bad["entered"].astype(bool).sum()) if len(bad) else 0,
                "bad_entry_rate_pct": _rate(bad["entered"].astype(bool).sum(), len(bad)) if len(bad) else 0.0,
                "optimal_candidates": int(len(optimal)),
                "optimal_entries": int(optimal["entered"].astype(bool).sum()) if len(optimal) else 0,
                "optimal_entry_rate_pct": _rate(optimal["entered"].astype(bool).sum(), len(optimal)) if len(optimal) else 0.0,
                "runner_candidates": int(len(runners)),
                "runner_entries": int(runners["entered"].astype(bool).sum()) if len(runners) else 0,
                "runner_entry_rate_pct": _rate(runners["entered"].astype(bool).sum(), len(runners)) if len(runners) else 0.0,
                "sum_intraday_ret_pct": round(float(returns.sum()), 4) if len(returns) else 0.0,
                "avg_intraday_ret_pct": round(float(returns.mean()), 4) if len(returns) else 0.0,
                "median_intraday_ret_pct": round(float(returns.median()), 4) if len(returns) else 0.0,
                "win_rate_pct": _rate(int(returns.gt(0).sum()), int(returns.notna().sum())),
                "avg_mfe_pct": round(float(mfe.mean()), 4) if len(mfe) else 0.0,
                "avg_mae_pct": round(float(mae.mean()), 4) if len(mae) else 0.0,
                "close_mark_exits": int(trades.get("exit_action", pd.Series(dtype=str)).eq("close_mark").sum()),
                "exit_loser_exits": int(trades.get("exit_action", pd.Series(dtype=str)).eq("exit_loser").sum()),
                "scratch_or_reduce_exits": int(trades.get("exit_action", pd.Series(dtype=str)).eq("scratch_or_reduce").sum()),
                "protect_profit_exits": int(trades.get("exit_action", pd.Series(dtype=str)).eq("protect_profit").sum()),
            }
        )
    return pd.DataFrame(rows)


def grouped_metrics(outcomes: pd.DataFrame, *, group_col: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    eligible = outcomes[outcomes["eligible"].astype(bool)].copy()
    for (variant, group_value), group in eligible.groupby(["variant", group_col], dropna=False, sort=True):
        trades = group[group["entered"].astype(bool)].copy()
        returns = _numeric_column(trades, "realized_intraday_ret_pct")
        rows.append(
            {
                "variant": variant,
                "group_col": group_col,
                "group_value": group_value,
                "eligible_candidates": int(len(group)),
                "trades": int(len(trades)),
                "entry_rate_pct": _rate(len(trades), len(group)),
                "bad_entry_rate_pct": _rate(
                    group[group["is_bad_bucket"]]["entered"].astype(bool).sum(),
                    int(group["is_bad_bucket"].sum()),
                )
                if int(group["is_bad_bucket"].sum())
                else 0.0,
                "avg_intraday_ret_pct": round(float(returns.mean()), 4) if len(returns) else 0.0,
                "win_rate_pct": _rate(int(returns.gt(0).sum()), int(returns.notna().sum())),
            }
        )
    return pd.DataFrame(
        rows,
        columns=[
            "variant",
            "group_col",
            "group_value",
            "eligible_candidates",
            "trades",
            "entry_rate_pct",
            "bad_entry_rate_pct",
            "avg_intraday_ret_pct",
            "win_rate_pct",
        ],
    )


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


def _summary_read(summary: pd.DataFrame) -> list[str]:
    if summary.empty or not {"model_policy", "baseline_rules"}.issubset(set(summary["variant"])):
        return ["- Not enough variant coverage to compare model policy against baseline rules."]
    baseline = summary[summary["variant"].eq("baseline_rules")].iloc[0]
    lines: list[str] = []
    for variant in ("model_policy", ENTRY_POLICY_V2_VARIANT, ENTRY_POLICY_V3_VARIANT, DUAL_HEAD_VARIANT):
        if variant not in set(summary["variant"]):
            continue
        row = summary[summary["variant"].eq(variant)].iloc[0]
        bad_delta = float(row["bad_entry_rate_pct"]) - float(baseline["bad_entry_rate_pct"])
        optimal_delta = float(row["optimal_entry_rate_pct"]) - float(baseline["optimal_entry_rate_pct"])
        runner_delta = float(row["runner_entry_rate_pct"]) - float(baseline["runner_entry_rate_pct"])
        return_delta = float(row["sum_intraday_ret_pct"]) - float(baseline["sum_intraday_ret_pct"])
        avg_delta = float(row["avg_intraday_ret_pct"]) - float(baseline["avg_intraday_ret_pct"])
        lines.extend(
            [
                f"- `{variant}` trades `{int(row['trades'])}` candidates versus baseline `{int(baseline['trades'])}`.",
                f"- `{variant}` bad-entry rate changes by `{bad_delta:.3f}` points versus baseline.",
                f"- `{variant}` optimal-entry rate changes by `{optimal_delta:.3f}` points; runner-entry rate changes by `{runner_delta:.3f}` points.",
                f"- `{variant}` same-day summed return changes by `{return_delta:.4f}` points; average trade return changes by `{avg_delta:.4f}` points.",
            ]
        )
    for variant in (ENTRY_POLICY_V2_VARIANT, ENTRY_POLICY_V3_VARIANT, DUAL_HEAD_VARIANT):
        if variant not in set(summary["variant"]):
            continue
        gate = promotion_gate(summary, variant=variant)
        lines.append(
            f"- Promotion gate for `{variant}`: `{gate['status']}` "
            f"(bad delta `{gate['bad_entry_delta_pct']}`, optimal capture `{gate['optimal_entry_rate_pct']}`, "
            f"runner capture `{gate['runner_entry_rate_pct']}`)."
        )
    lines.append("- Read: useful diagnostic signal, not a promotion result until replayed through local LEAN order semantics.")
    return lines


def promotion_gate(summary: pd.DataFrame, *, variant: str) -> dict[str, Any]:
    if summary.empty or variant not in set(summary["variant"]) or "baseline_rules" not in set(summary["variant"]):
        return {
            "variant": variant,
            "status": "missing_metrics",
            "bad_entry_delta_pct": None,
            "optimal_entry_rate_pct": None,
            "runner_entry_rate_pct": None,
        }
    baseline = summary[summary["variant"].eq("baseline_rules")].iloc[0]
    row = summary[summary["variant"].eq(variant)].iloc[0]
    bad_delta = round(float(row["bad_entry_rate_pct"]) - float(baseline["bad_entry_rate_pct"]), 3)
    optimal_rate = round(float(row["optimal_entry_rate_pct"]), 3)
    runner_rate = round(float(row["runner_entry_rate_pct"]), 3)
    passed = (
        bad_delta <= PROMOTION_MAX_BAD_ENTRY_RATE_DELTA
        and optimal_rate >= PROMOTION_MIN_OPTIMAL_ENTRY_RATE
        and runner_rate >= PROMOTION_MIN_RUNNER_ENTRY_RATE
    )
    return {
        "variant": variant,
        "status": "promote" if passed else "iterate",
        "bad_entry_delta_pct": bad_delta,
        "optimal_entry_rate_pct": optimal_rate,
        "runner_entry_rate_pct": runner_rate,
        "thresholds": {
            "max_bad_entry_rate_delta": PROMOTION_MAX_BAD_ENTRY_RATE_DELTA,
            "min_optimal_entry_rate": PROMOTION_MIN_OPTIMAL_ENTRY_RATE,
            "min_runner_entry_rate": PROMOTION_MIN_RUNNER_ENTRY_RATE,
        },
    }


def write_outputs(
    *,
    outcomes: pd.DataFrame,
    management_rows: pd.DataFrame,
    summary: pd.DataFrame,
    grouped: pd.DataFrame,
    config: ReplayConfig,
    output_dir: Path,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "README.md").write_text(
        "# intraday_policy_replay_490/\n\n"
        "Contains #490 replay-shaped economics for intraday entry/exit policies.\n"
        "Keep candidate outcomes, trade ledgers, summary metrics, reports, and manifests here.\n"
        "Do not store raw intraday parquet data or QC Cloud backtest folders here.\n",
        encoding="utf-8",
    )
    trade_ledger = outcomes[outcomes["entered"].astype(bool)].copy()
    _write_gzip_csv(trade_ledger, output_dir / "trade_ledger.csv.gz")
    _write_gzip_csv(outcomes, output_dir / "candidate_outcomes.csv.gz")
    summary.to_csv(output_dir / "summary_metrics.csv", index=False)
    grouped.to_csv(output_dir / "grouped_metrics.csv", index=False)
    source_metrics = grouped[grouped["group_col"].eq("scanner_source_bucket")].copy()
    month_metrics = grouped[grouped["group_col"].eq("month")].copy()
    source_metrics.to_csv(output_dir / "source_bucket_metrics.csv", index=False)
    month_metrics.to_csv(output_dir / "month_metrics.csv", index=False)
    if not management_rows.empty:
        _write_gzip_csv(management_rows, output_dir / "management_decision_rows.csv.gz")

    lines = [
        "# Intraday Policy Replay Economics #490",
        "",
        "This is the correction pass after the #490 supervised baseline: it turns predicted actions into a same-day trade ledger.",
        "Entry/exit prices are completed-bar checkpoint marks from the #491 intraday panel, not broker fill simulation.",
        "",
        "## Inputs",
        "",
        f"- Panel: `{config.panel}`",
        f"- Model artifact: `{config.model_artifact}`",
        f"- Dual-head model artifact: `{config.dual_head_model_artifact}`",
        f"- Scan-time predictions: `{config.scan_time_predictions}`",
        f"- Parquet root: `{config.parquet_root}`",
        "",
        "## Summary",
        "",
        _markdown_table(
            summary,
            [
                "variant",
                "eligible_candidates",
                "trades",
                "entry_rate_pct",
                "bad_entry_rate_pct",
                "optimal_entry_rate_pct",
                "runner_entry_rate_pct",
                "sum_intraday_ret_pct",
                "avg_intraday_ret_pct",
                "win_rate_pct",
            ],
        ),
        "",
        "## Result Read",
        "",
        "\n".join(_summary_read(summary)),
        "",
        "## Grouped Diagnostics",
        "",
        _markdown_table(
            grouped,
            [
                "variant",
                "group_col",
                "group_value",
                "eligible_candidates",
                "trades",
                "entry_rate_pct",
                "bad_entry_rate_pct",
                "avg_intraday_ret_pct",
                "win_rate_pct",
            ],
            limit=80,
        ),
        "",
        "## Read",
        "",
        "- This evaluates economic behavior from decisions; it is still not QC Cloud or multi-day LEAN parity.",
        "- The replay is same-day checkpoint based, so it can expose bad entry/exiting behavior but not full swing trade lifecycle.",
        "- A promotable policy still needs local LEAN integration under #484 and George-fair labels under #489.",
        "",
    ]
    (output_dir / "intraday_policy_replay_report.md").write_text("\n".join(lines), encoding="utf-8")
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "issue": "https://github.com/FALK-BRAUER/kumo-qc/issues/490",
        "replay_version": REPLAY_VERSION,
        "config": asdict(config),
        "entry_policy_v2": {
            "max_avoid_prob": ENTRY_V2_MAX_AVOID_PROB,
            "max_risk_enter_gap": ENTRY_V2_MAX_RISK_ENTER_GAP,
            "min_enter_prob": ENTRY_V2_MIN_ENTER_PROB,
            "min_return_from_open_pct": ENTRY_V2_MIN_RETURN_FROM_OPEN_PCT,
            "min_mae_from_open_pct": ENTRY_V2_MIN_MAE_FROM_OPEN_PCT,
        },
        "entry_policy_v3": {
            "max_avoid_prob": ENTRY_V3_MAX_AVOID_PROB,
            "min_return_from_open_pct": ENTRY_V3_MIN_RETURN_FROM_OPEN_PCT,
            "min_mae_from_open_pct": ENTRY_V3_MIN_MAE_FROM_OPEN_PCT,
            "min_scan_optimal_score": ENTRY_V3_MIN_SCAN_OPTIMAL_SCORE,
            "max_scan_bad_risk_score": ENTRY_V3_MAX_SCAN_BAD_RISK_SCORE,
        },
        "dual_head_policy": {
            "entry_max_bad_risk_prob": DUAL_ENTRY_MAX_BAD_RISK_PROB,
            "entry_min_winner_prob": DUAL_ENTRY_MIN_WINNER_PROB,
            "entry_min_ready_prob": DUAL_ENTRY_MIN_READY_PROB,
            "entry_strong_winner_prob": DUAL_ENTRY_STRONG_WINNER_PROB,
            "entry_max_strong_winner_bad_risk_prob": DUAL_ENTRY_MAX_STRONG_WINNER_BAD_RISK_PROB,
            "management_exit_risk_prob": DUAL_MGMT_EXIT_RISK_PROB,
            "management_runner_preserve_prob": DUAL_MGMT_RUNNER_PRESERVE_PROB,
        },
        "promotion_gate": promotion_gate(summary, variant=DUAL_HEAD_VARIANT),
        "promotion_gates": {
            ENTRY_POLICY_V2_VARIANT: promotion_gate(summary, variant=ENTRY_POLICY_V2_VARIANT),
            ENTRY_POLICY_V3_VARIANT: promotion_gate(summary, variant=ENTRY_POLICY_V3_VARIANT),
            DUAL_HEAD_VARIANT: promotion_gate(summary, variant=DUAL_HEAD_VARIANT),
        },
        "outputs": {
            "candidate_outcomes.csv.gz": {"rows": int(len(outcomes))},
            "trade_ledger.csv.gz": {"rows": int(len(trade_ledger))},
            "management_decision_rows.csv.gz": {"rows": int(len(management_rows))},
            "summary_metrics.csv": {"rows": int(len(summary))},
            "grouped_metrics.csv": {"rows": int(len(grouped))},
            "source_bucket_metrics.csv": {"rows": int(len(source_metrics))},
            "month_metrics.csv": {"rows": int(len(month_metrics))},
            "intraday_policy_replay_report.md": {},
        },
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return {
        "candidate_outcomes": output_dir / "candidate_outcomes.csv.gz",
        "trade_ledger": output_dir / "trade_ledger.csv.gz",
        "management_decision_rows": output_dir / "management_decision_rows.csv.gz",
        "summary_metrics": output_dir / "summary_metrics.csv",
        "grouped_metrics": output_dir / "grouped_metrics.csv",
        "report": output_dir / "intraday_policy_replay_report.md",
        "manifest": output_dir / "manifest.json",
    }


def run(
    *,
    panel_path: Path = DEFAULT_PANEL,
    model_artifact_path: Path = DEFAULT_MODEL,
    dual_head_model_artifact_path: Path = DEFAULT_DUAL_HEAD_MODEL,
    parquet_root: Path = DEFAULT_PARQUET_ROOT,
    scan_time_predictions_path: Path = DEFAULT_SCAN_TIME_PREDICTIONS,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    limit_opportunities: int | None = None,
    variants: Sequence[str] = VARIANTS,
) -> dict[str, Path]:
    config = ReplayConfig(
        panel=str(panel_path),
        model_artifact=str(model_artifact_path),
        dual_head_model_artifact=str(dual_head_model_artifact_path),
        parquet_root=str(parquet_root),
        scan_time_predictions=str(scan_time_predictions_path),
        output_dir=str(output_dir),
        limit_opportunities=limit_opportunities,
        variants=tuple(variants),
    )
    artifact = read_model_artifact(model_artifact_path)
    dual_head_artifact = read_model_artifact(dual_head_model_artifact_path) if DUAL_HEAD_VARIANT in variants else None
    entry_rows = read_entry_rows(panel_path, limit_opportunities=limit_opportunities)
    print(f"loaded entry rows={len(entry_rows)} opportunities={entry_rows['opportunity_id'].nunique()}", file=sys.stderr, flush=True)
    if ENTRY_POLICY_V3_VARIANT in variants:
        entry_rows = add_scan_time_priors(entry_rows, scan_time_predictions_path)
        print(f"joined scan-time #492 priors from {scan_time_predictions_path}", file=sys.stderr, flush=True)
    entry_rows = add_entry_actions(entry_rows, artifact, dual_head_artifact=dual_head_artifact)
    selected = pd.concat([selected_entries(entry_rows, variant=variant) for variant in variants], ignore_index=True)
    print(f"selected rows={len(selected)} trades={int(selected['entered'].astype(bool).sum())}", file=sys.stderr, flush=True)
    management_rows = build_management_decision_rows(entry_rows, selected, parquet_root=parquet_root)
    print(f"management replay rows={len(management_rows)}", file=sys.stderr, flush=True)
    management_rows = add_management_actions(management_rows, artifact, dual_head_artifact=dual_head_artifact)
    outcomes = finalize_candidate_outcomes(selected, management_rows)
    summary = summary_metrics(outcomes)
    grouped = pd.concat(
        [
            grouped_metrics(outcomes, group_col="scanner_source_bucket"),
            grouped_metrics(outcomes.assign(month=outcomes["scan_date"].astype(str).str.slice(0, 7)), group_col="month"),
        ],
        ignore_index=True,
    )
    return write_outputs(
        outcomes=outcomes,
        management_rows=management_rows,
        summary=summary,
        grouped=grouped,
        config=config,
        output_dir=output_dir,
    )


def main() -> None:
    args = _args()
    outputs = run(
        panel_path=args.panel,
        model_artifact_path=args.model_artifact,
        dual_head_model_artifact_path=args.dual_head_model_artifact,
        parquet_root=args.parquet_root,
        scan_time_predictions_path=args.scan_time_predictions,
        output_dir=args.output_dir,
        limit_opportunities=args.limit_opportunities,
        variants=tuple(args.variants),
    )
    for label, path in outputs.items():
        print(f"{label}: {path}")


if __name__ == "__main__":
    main()
