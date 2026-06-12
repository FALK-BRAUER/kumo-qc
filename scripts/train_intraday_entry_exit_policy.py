"""Train intraday entry and management policies from #491 decision rows (#490)."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import re
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import train_scanner_opportunity_ranker as base_ranker  # noqa: E402

DEFAULT_PANEL = ROOT / "sweeps" / "reports" / "intraday_decision_panel_491" / "intraday_decision_panel.csv.gz"
DEFAULT_OUTPUT_DIR = ROOT / "sweeps" / "reports" / "intraday_entry_exit_policy_490"
FEATURE_VERSION = "intraday_entry_exit_policy_490_v1"
MODEL_SCHEMA_VERSION = 1
ENTRY_ACTIONS = ("avoid_bad_entry", "enter_now", "wait")
MANAGEMENT_ACTIONS = (
    "do_not_cut_runner",
    "exit_loser",
    "hold_or_wait",
    "hold_winner",
    "protect_profit",
    "scratch_or_reduce",
)
CHECKPOINTS = ("open", "after_15m", "after_30m", "first_hour", "midday", "close")
SOURCE_BUCKETS = ("both_george_and_kumo", "george_only", "kumo_only", "kumo_with_george_video_context")
SECTOR_VALUES = (
    "ai_semis",
    "communication_services",
    "consumer_cyclical",
    "consumer_defensive",
    "energy",
    "financials",
    "healthcare",
    "industrials",
    "materials",
    "real_estate",
    "tech",
    "utilities",
)
DENIED_FEATURE_TOKENS = (
    "oracle",
    "label",
    "reason",
    "outcome",
    "best",
    "deployable",
    "trade_bucket",
    "action",
    "future",
    "assumption",
    "triggered",
    "next_open",
    "ret_20d",
    "mfe_20d",
    "mae_20d",
    "source_tags",
)

BASE_NUMERIC_FEATURES = [
    "kumo_rank_by_score",
    "kumo_score",
    "george_rank",
    "george_watchlist_rank",
    "bars_completed",
    "session_open",
    "current_price",
    "return_from_open_pct",
    "gap_from_prior_close_pct",
    "mfe_from_open_pct",
    "mae_from_open_pct",
    "volume_so_far_log",
    "distance_from_vwap_pct",
    "last_15m_ret_pct",
    "last_15m_range_pct",
    "last_15m_volume_log",
    "last_hour_ret_pct",
    "last_hour_range_pct",
    "last_hour_volume_log",
    "etf_bars_completed",
    "etf_return_from_open_pct",
    "etf_mfe_from_open_pct",
    "etf_mae_from_open_pct",
    "etf_volume_so_far_log",
    "etf_distance_from_vwap_pct",
    "etf_last_15m_ret_pct",
    "etf_last_15m_range_pct",
    "etf_last_15m_volume_log",
    "etf_last_hour_ret_pct",
    "etf_last_hour_range_pct",
    "etf_last_hour_volume_log",
    "position_minutes_since_entry",
    "position_bars_completed_since_entry",
    "position_current_return_pct",
    "position_mfe_so_far_pct",
    "position_mae_so_far_pct",
    "position_drawdown_from_peak_pct",
]
BOOL_FEATURES = [
    "kumo_signal_seen",
    "kumo_top_n",
    "kumo_scanner",
    "george_signal_seen",
    "george_scanner_positive",
    "george_watchlist",
    "george_video_mention",
    "intraday_available",
    "last_15m_available",
    "last_hour_available",
    "etf_intraday_available",
    "etf_last_15m_available",
    "etf_last_hour_available",
    "ichimoku_15m_available",
    "ichimoku_hour_available",
    "etf_ichimoku_15m_available",
    "etf_ichimoku_hour_available",
]


@dataclass(frozen=True)
class Standardizer:
    mean: np.ndarray
    scale: np.ndarray


@dataclass(frozen=True)
class SoftmaxModel:
    coef: np.ndarray
    intercept: np.ndarray
    classes: tuple[str, ...]


@dataclass(frozen=True)
class PolicyConfig:
    panel: str
    output_dir: str
    n_folds: int
    min_train_folds: int
    max_iter: int
    learning_rate: float
    l2: float
    limit: int | None


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", type=Path, default=DEFAULT_PANEL)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--n-folds", type=int, default=6)
    parser.add_argument("--min-train-folds", type=int, default=1)
    parser.add_argument("--max-iter", type=int, default=140)
    parser.add_argument("--learning-rate", type=float, default=0.05)
    parser.add_argument("--l2", type=float, default=0.01)
    parser.add_argument("--limit", type=int, default=None, help="Optional row limit after loading.")
    return parser.parse_args()


def _bool_series(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip().str.lower().isin({"1", "true", "yes", "y"})


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame:
        return pd.Series(np.nan, index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce")


def _safe_log1p(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    return np.log1p(values.clip(lower=0.0))


def _slug(value: Any) -> str:
    raw = "" if pd.isna(value) else str(value).strip().lower()
    return re.sub(r"[^a-z0-9]+", "_", raw).strip("_")


def validate_feature_names(feature_names: Sequence[str]) -> None:
    denied = [
        feature
        for feature in feature_names
        if any(token in feature.lower() for token in DENIED_FEATURE_TOKENS)
    ]
    if denied:
        raise ValueError(f"intraday policy feature set contains denied leakage features: {denied}")


def feature_hash(feature_names: Sequence[str]) -> str:
    payload = {"feature_version": FEATURE_VERSION, "feature_names": list(feature_names)}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def read_panel(path: Path, *, limit: int | None = None) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    frame = pd.read_csv(path, low_memory=False)
    if limit is not None:
        frame = frame.head(limit).copy()
    frame["scan_date"] = frame["scan_date"].astype(str).str.slice(0, 10)
    frame["symbol"] = frame["symbol"].astype(str).str.upper()
    frame["row_type"] = frame["row_type"].astype(str)
    frame["entry_action_label"] = frame["entry_action_label"].fillna("").astype(str)
    frame["management_action_label"] = frame["management_action_label"].fillna("").astype(str)
    for column in BOOL_FEATURES:
        if column in frame:
            frame[column] = _bool_series(frame[column])
    return frame


def add_policy_features(frame: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    out = frame.copy()
    for column in ("volume_so_far", "last_15m_volume", "last_hour_volume", "etf_volume_so_far", "etf_last_15m_volume", "etf_last_hour_volume"):
        out[f"{column}_log"] = _safe_log1p(out.get(column, pd.Series(np.nan, index=out.index)))

    features = list(BASE_NUMERIC_FEATURES)
    for column in BOOL_FEATURES:
        out[f"is_{column}"] = out[column].astype(float) if column in out else 0.0
        features.append(f"is_{column}")

    checkpoint = out.get("checkpoint", pd.Series("", index=out.index)).map(_slug)
    for value in CHECKPOINTS:
        feature = f"checkpoint_{value}"
        out[feature] = checkpoint.eq(value).astype(float)
        features.append(feature)

    source = out.get("scanner_source_bucket", pd.Series("", index=out.index)).map(_slug)
    for value in SOURCE_BUCKETS:
        feature = f"source_bucket_{value}"
        out[feature] = source.eq(value).astype(float)
        features.append(feature)

    sector = out.get("sector_category", pd.Series("", index=out.index)).map(_slug)
    for value in SECTOR_VALUES:
        feature = f"sector_{value}"
        out[feature] = sector.eq(value).astype(float)
        features.append(feature)

    validate_feature_names(features)
    return out, features


def build_feature_matrix(frame: pd.DataFrame, feature_names: Sequence[str]) -> np.ndarray:
    columns = [_num(frame, feature).to_numpy(dtype=float) for feature in feature_names]
    if not columns:
        return np.empty((len(frame), 0), dtype=float)
    return np.column_stack(columns).astype(float)


def fit_standardizer(x_train: np.ndarray) -> Standardizer:
    if x_train.shape[1] == 0:
        return Standardizer(mean=np.empty(0), scale=np.empty(0))
    clean = np.where(np.isfinite(x_train), x_train, np.nan)
    valid = np.isfinite(clean)
    counts = valid.sum(axis=0)
    sums = np.nansum(clean, axis=0)
    mean = np.divide(sums, counts, out=np.zeros_like(sums, dtype=float), where=counts > 0)
    filled = np.where(np.isfinite(x_train), x_train, mean)
    scale = filled.std(axis=0)
    scale = np.where(np.isfinite(scale) & (scale > 1e-9), scale, 1.0)
    return Standardizer(mean=mean, scale=scale)


def apply_standardizer(x: np.ndarray, standardizer: Standardizer) -> np.ndarray:
    if x.shape[1] == 0:
        return x
    filled = np.where(np.isfinite(x), x, standardizer.mean)
    scaled = np.asarray((filled - standardizer.mean) / standardizer.scale, dtype=float)
    scaled = np.nan_to_num(scaled, nan=0.0, posinf=0.0, neginf=0.0)
    return np.clip(scaled, -10.0, 10.0)


def _softmax(logits: np.ndarray) -> np.ndarray:
    shifted = logits - np.nanmax(logits, axis=1, keepdims=True)
    exp = np.exp(np.clip(shifted, -40.0, 40.0))
    denom = exp.sum(axis=1, keepdims=True)
    denom = np.where(denom > 0, denom, 1.0)
    return exp / denom


def _class_weights(y: np.ndarray, n_classes: int) -> np.ndarray:
    counts = np.bincount(y, minlength=n_classes).astype(float)
    weights = np.ones(n_classes, dtype=float)
    nonzero = counts > 0
    if nonzero.any():
        weights[nonzero] = np.sqrt(counts[nonzero].sum() / (counts[nonzero] * nonzero.sum()))
    return np.clip(weights, 0.25, 5.0)


def fit_softmax_linear(
    x: np.ndarray,
    y: np.ndarray,
    classes: Sequence[str],
    *,
    max_iter: int,
    learning_rate: float,
    l2: float,
) -> SoftmaxModel:
    n_classes = len(classes)
    if len(y) == 0 or x.shape[1] == 0:
        return SoftmaxModel(coef=np.zeros((x.shape[1], n_classes)), intercept=np.zeros(n_classes), classes=tuple(classes))
    coef = np.zeros((x.shape[1], n_classes), dtype=float)
    intercept = np.zeros(n_classes, dtype=float)
    one_hot = np.zeros((len(y), n_classes), dtype=float)
    one_hot[np.arange(len(y)), y] = 1.0
    weights = _class_weights(y, n_classes)
    sample_weight = weights[y]
    denom = float(sample_weight.sum()) if sample_weight.sum() > 0 else float(len(y))
    for _ in range(max_iter):
        with np.errstate(over="ignore", divide="ignore", invalid="ignore"):
            logits = np.nan_to_num(x @ coef + intercept, nan=0.0, posinf=40.0, neginf=-40.0)
        probs = _softmax(logits)
        error = (probs - one_hot) * sample_weight[:, None]
        with np.errstate(over="ignore", divide="ignore", invalid="ignore"):
            grad_coef = np.nan_to_num((x.T @ error) / denom + l2 * coef, nan=0.0, posinf=0.0, neginf=0.0)
        grad_intercept = error.sum(axis=0) / denom
        grad_norm = float(np.linalg.norm(grad_coef))
        if grad_norm > 25.0:
            grad_coef *= 25.0 / grad_norm
        coef -= learning_rate * grad_coef
        intercept -= learning_rate * grad_intercept
        coef = np.clip(np.nan_to_num(coef, nan=0.0, posinf=0.0, neginf=0.0), -20.0, 20.0)
        intercept = np.clip(np.nan_to_num(intercept, nan=0.0, posinf=0.0, neginf=0.0), -20.0, 20.0)
    return SoftmaxModel(coef=coef, intercept=intercept, classes=tuple(classes))


def predict_proba(model: SoftmaxModel, x: np.ndarray) -> np.ndarray:
    if len(x) == 0:
        return np.empty((0, len(model.classes)))
    with np.errstate(over="ignore", divide="ignore", invalid="ignore"):
        logits = np.nan_to_num(x @ model.coef + model.intercept, nan=0.0, posinf=40.0, neginf=-40.0)
    return _softmax(logits)


def make_walk_forward_splits(dates: Sequence[str], *, n_folds: int, min_train_folds: int) -> list[dict[str, Any]]:
    return base_ranker.make_walk_forward_splits(dates, n_folds=n_folds, min_train_folds=min_train_folds)


def baseline_entry_action(frame: pd.DataFrame) -> pd.Series:
    ret = _num(frame, "return_from_open_pct").fillna(0.0)
    mae = _num(frame, "mae_from_open_pct").fillna(0.0)
    dist_vwap = _num(frame, "distance_from_vwap_pct").fillna(0.0)
    score = _num(frame, "kumo_score").fillna(0.0)
    checkpoint = frame["checkpoint"].astype(str)
    avoid = mae.le(-2.0) | ret.le(-1.5)
    enter = checkpoint.isin(["after_30m", "first_hour", "midday", "close"]) & ret.ge(0.0) & dist_vwap.ge(-0.25) & score.ge(7.0)
    return pd.Series(np.select([avoid, enter], ["avoid_bad_entry", "enter_now"], default="wait"), index=frame.index)


def baseline_management_action(frame: pd.DataFrame) -> pd.Series:
    ret = _num(frame, "position_current_return_pct").fillna(0.0)
    mae = _num(frame, "position_mae_so_far_pct").fillna(0.0)
    drawdown = _num(frame, "position_drawdown_from_peak_pct").fillna(0.0)
    exit_loser = ret.le(-2.0) | mae.le(-3.0)
    protect = ret.ge(4.0) & drawdown.ge(2.0)
    hold_winner = ret.ge(1.0)
    return pd.Series(
        np.select([exit_loser, protect, hold_winner], ["exit_loser", "protect_profit", "hold_winner"], default="hold_or_wait"),
        index=frame.index,
    )


def policy_subset(panel: pd.DataFrame, policy_name: str) -> tuple[pd.DataFrame, tuple[str, ...], str]:
    if policy_name == "entry_policy":
        frame = panel[panel["row_type"].eq("entry_decision")].copy()
        frame = frame[frame["entry_action_label"].isin(ENTRY_ACTIONS)].copy()
        frame["label_action"] = frame["entry_action_label"]
        return frame, ENTRY_ACTIONS, "entry_action_label"
    if policy_name == "management_policy":
        frame = panel[panel["row_type"].eq("position_management")].copy()
        frame = frame[frame["management_action_label"].isin(MANAGEMENT_ACTIONS)].copy()
        frame["label_action"] = frame["management_action_label"]
        return frame, MANAGEMENT_ACTIONS, "management_action_label"
    raise ValueError(f"unknown policy: {policy_name}")


def fit_oof_policy(
    panel: pd.DataFrame,
    feature_names: Sequence[str],
    *,
    policy_name: str,
    config: PolicyConfig,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    frame, classes, _label_column = policy_subset(panel, policy_name)
    class_to_idx = {label: idx for idx, label in enumerate(classes)}
    x_raw = build_feature_matrix(frame, feature_names)
    y = frame["label_action"].map(class_to_idx).to_numpy(dtype=int)
    predictions = frame.copy()
    predictions["policy_name"] = policy_name
    predictions["feature_version_490"] = FEATURE_VERSION
    predictions["feature_hash_490"] = feature_hash(feature_names)
    predictions["oof_available_490"] = False
    predictions["fold_490"] = np.nan
    predictions["predicted_action"] = ""
    predictions["predicted_confidence"] = np.nan
    for action in classes:
        predictions[f"prob_{action}"] = np.nan
    predictions["baseline_action"] = (
        baseline_entry_action(predictions) if policy_name == "entry_policy" else baseline_management_action(predictions)
    )

    splits = make_walk_forward_splits(predictions["scan_date"].tolist(), n_folds=config.n_folds, min_train_folds=config.min_train_folds)
    print(
        f"{policy_name}: rows={len(predictions)}, classes={','.join(classes)}, folds={len(splits)}, features={len(feature_names)}",
        file=sys.stderr,
        flush=True,
    )
    fold_rows: list[dict[str, Any]] = []
    coef_rows: list[dict[str, Any]] = []
    models: list[dict[str, Any]] = []
    for split in splits:
        train_mask = predictions["scan_date"].isin(split["train_dates"]).to_numpy(dtype=bool)
        valid_mask = predictions["scan_date"].isin(split["valid_dates"]).to_numpy(dtype=bool)
        print(
            f"{policy_name}: fitting fold {int(split['fold'])} "
            f"train={int(train_mask.sum())} valid={int(valid_mask.sum())} "
            f"valid_dates={split['valid_start']}..{split['valid_end']}",
            file=sys.stderr,
            flush=True,
        )
        standardizer = fit_standardizer(x_raw[train_mask])
        x_train = apply_standardizer(x_raw[train_mask], standardizer)
        x_valid = apply_standardizer(x_raw[valid_mask], standardizer)
        model = fit_softmax_linear(
            x_train,
            y[train_mask],
            classes,
            max_iter=config.max_iter,
            learning_rate=config.learning_rate,
            l2=config.l2,
        )
        probs = predict_proba(model, x_valid)
        pred_idx = probs.argmax(axis=1)
        valid_indices = predictions.index[valid_mask]
        predictions.loc[valid_indices, "oof_available_490"] = True
        predictions.loc[valid_indices, "fold_490"] = int(split["fold"])
        predictions.loc[valid_indices, "predicted_action"] = [classes[idx] for idx in pred_idx]
        predictions.loc[valid_indices, "predicted_confidence"] = probs.max(axis=1)
        for idx, action in enumerate(classes):
            predictions.loc[valid_indices, f"prob_{action}"] = probs[:, idx]
        y_train = y[train_mask]
        fold_rows.append(
            {
                "policy_name": policy_name,
                "fold": int(split["fold"]),
                "train_start": min(split["train_dates"]),
                "train_end": max(split["train_dates"]),
                "valid_start": split["valid_start"],
                "valid_end": split["valid_end"],
                "train_rows": int(train_mask.sum()),
                "valid_rows": int(valid_mask.sum()),
                "train_classes": ";".join(f"{classes[idx]}={int((y_train == idx).sum())}" for idx in range(len(classes))),
            }
        )
        for class_idx, action in enumerate(classes):
            for feature_idx, feature in enumerate(feature_names):
                coef_rows.append(
                    {
                        "policy_name": policy_name,
                        "fold": int(split["fold"]),
                        "action": action,
                        "feature": feature,
                        "coef": round(float(model.coef[feature_idx, class_idx]), 6),
                    }
                )
        models.append(
            {
                "fold": int(split["fold"]),
                "valid_start": split["valid_start"],
                "valid_end": split["valid_end"],
                "standardizer": {
                    "mean": [round(float(v), 10) for v in standardizer.mean.tolist()],
                    "scale": [round(float(v), 10) for v in standardizer.scale.tolist()],
                },
                "coef": [[round(float(v), 10) for v in row] for row in model.coef.tolist()],
                "intercept": [round(float(v), 10) for v in model.intercept.tolist()],
            }
        )
    artifact = {
        "schema_version": MODEL_SCHEMA_VERSION,
        "policy_name": policy_name,
        "model_type": "softmax_linear_oof_folds",
        "feature_version": FEATURE_VERSION,
        "feature_hash": feature_hash(feature_names),
        "feature_names": list(feature_names),
        "classes": list(classes),
        "fold_models": models,
    }
    return predictions, pd.DataFrame(fold_rows), pd.DataFrame(coef_rows), artifact


def action_metrics(predictions: pd.DataFrame, *, pred_col: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    frame = predictions[predictions["oof_available_490"]].copy()
    actions = sorted(set(frame["label_action"].dropna()) | set(frame[pred_col].dropna()))
    for action in actions:
        label_is_action = frame["label_action"].eq(action)
        pred_is_action = frame[pred_col].eq(action)
        tp = int((label_is_action & pred_is_action).sum())
        fp = int((~label_is_action & pred_is_action).sum())
        fn = int((label_is_action & ~pred_is_action).sum())
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2.0 * precision * recall / (precision + recall) if precision + recall else 0.0
        rows.append(
            {
                "policy_name": str(frame["policy_name"].iloc[0]) if len(frame) else "",
                "score_type": pred_col,
                "action": action,
                "support": int(frame["label_action"].eq(action).sum()),
                "predicted": int(frame[pred_col].eq(action).sum()),
                "precision_pct": round(100.0 * precision, 3),
                "recall_pct": round(100.0 * recall, 3),
                "f1": round(float(f1), 4),
            }
        )
    return pd.DataFrame(rows)


def summary_metrics(predictions: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    frame = predictions[predictions["oof_available_490"]].copy()
    for pred_col in ("predicted_action", "baseline_action"):
        metrics = action_metrics(predictions, pred_col=pred_col)
        rows.append(
            {
                "policy_name": str(frame["policy_name"].iloc[0]) if len(frame) else "",
                "score_type": pred_col,
                "rows": int(len(frame)),
                "accuracy_pct": round(100.0 * float(frame["label_action"].eq(frame[pred_col]).mean()), 3) if len(frame) else 0.0,
                "macro_f1": round(float(metrics["f1"].mean()), 4) if not metrics.empty else 0.0,
            }
        )
    return pd.DataFrame(rows)


def grouped_summary(predictions: pd.DataFrame, *, group_col: str) -> pd.DataFrame:
    frame = predictions[predictions["oof_available_490"]].copy()
    rows: list[dict[str, Any]] = []
    for group_value, group in frame.groupby(group_col, dropna=False, sort=True):
        rows.append(
            {
                "policy_name": str(group["policy_name"].iloc[0]),
                "group_col": group_col,
                "group_value": group_value,
                "rows": int(len(group)),
                "model_accuracy_pct": round(100.0 * float(group["label_action"].eq(group["predicted_action"]).mean()), 3),
                "baseline_accuracy_pct": round(100.0 * float(group["label_action"].eq(group["baseline_action"]).mean()), 3),
            }
        )
    return pd.DataFrame(rows)


def feature_importance(coefs: pd.DataFrame) -> pd.DataFrame:
    if coefs.empty:
        return pd.DataFrame(columns=["policy_name", "action", "feature", "coef_mean", "coef_abs_mean"])
    return (
        coefs.groupby(["policy_name", "action", "feature"], dropna=False)
        .agg(coef_mean=("coef", "mean"), coef_abs_mean=("coef", lambda s: float(np.abs(s).mean())))
        .reset_index()
        .assign(coef_mean=lambda df: df["coef_mean"].round(6), coef_abs_mean=lambda df: df["coef_abs_mean"].round(6))
        .sort_values(["policy_name", "action", "coef_abs_mean"], ascending=[True, True, False])
        .reset_index(drop=True)
    )


def prediction_output(predictions: pd.DataFrame) -> pd.DataFrame:
    base_cols = [
        "policy_name",
        "feature_version_490",
        "feature_hash_490",
        "oof_available_490",
        "fold_490",
        "scan_date",
        "symbol",
        "opportunity_id",
        "row_type",
        "scanner_source_bucket",
        "checkpoint",
        "as_of_timestamp",
        "kumo_rank_by_score",
        "kumo_score",
        "george_signal_seen",
        "george_rank",
        "label_action",
        "predicted_action",
        "predicted_confidence",
        "baseline_action",
    ]
    prob_cols = [column for column in predictions.columns if column.startswith("prob_")]
    return predictions.loc[:, [column for column in base_cols + prob_cols if column in predictions]].copy()


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
    summary: pd.DataFrame,
    action: pd.DataFrame,
    grouped: pd.DataFrame,
    folds: pd.DataFrame,
    importance: pd.DataFrame,
    config: PolicyConfig,
) -> None:
    lines = [
        "# Intraday Entry/Exit Policy #490",
        "",
        "This trains first-pass dependency-free softmax policies on the #491 intraday decision panel.",
        "Entry and position-management policies are trained separately with expanding-window date validation.",
        "",
        "## Inputs",
        "",
        f"- Panel: `{config.panel}`",
        "",
        "## Summary Metrics",
        "",
        _markdown_table(summary, ["policy_name", "score_type", "rows", "accuracy_pct", "macro_f1"]),
        "",
        "## Action Metrics",
        "",
        _markdown_table(action, ["policy_name", "score_type", "action", "support", "predicted", "precision_pct", "recall_pct", "f1"], limit=80),
        "",
        "## Source/Month/Fold Diagnostics",
        "",
        _markdown_table(grouped, ["policy_name", "group_col", "group_value", "rows", "model_accuracy_pct", "baseline_accuracy_pct"], limit=80),
        "",
        "## Fold Summary",
        "",
        _markdown_table(folds, ["policy_name", "fold", "train_start", "train_end", "valid_start", "valid_end", "train_rows", "valid_rows"], limit=40),
        "",
        "## Feature Diagnostics",
        "",
        _markdown_table(importance, ["policy_name", "action", "feature", "coef_mean", "coef_abs_mean"], limit=60),
        "",
        "## Read",
        "",
        "- Decision: iterate, do not promote yet.",
        "- This is a first supervised policy baseline, not a deployment recommendation.",
        "- Core features intentionally exclude route-label assumption counts and upstream learned opportunity scores.",
        "- The report should be read against fold/month diagnostics before trusting aggregate metrics.",
        "- Promotion requires local replay against actual order semantics and a cleaner Ichimoku/historical context pass.",
        "- Feature names are guarded against oracle/future/label leakage.",
        "",
    ]
    (output_dir / "intraday_entry_exit_policy_report.md").write_text("\n".join(lines), encoding="utf-8")


def write_outputs(
    *,
    predictions: pd.DataFrame,
    folds: pd.DataFrame,
    summary: pd.DataFrame,
    action: pd.DataFrame,
    grouped: pd.DataFrame,
    importance: pd.DataFrame,
    artifact: dict[str, Any],
    config: PolicyConfig,
    output_dir: Path,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "README.md").write_text(
        "# intraday_entry_exit_policy_490/\n\n"
        "Contains first-pass intraday entry/exit policy training artifacts for issue #490.\n"
        "Keep compact OOF predictions, metrics, diagnostics, model JSON, and reports here.\n"
        "Do not store raw parquet data, bulky replay runs, or QC Cloud artifacts here.\n",
        encoding="utf-8",
    )
    pred_path = output_dir / "oof_predictions.csv.gz"
    _write_gzip_csv(prediction_output(predictions), pred_path)
    folds.to_csv(output_dir / "fold_summary.csv", index=False)
    summary.to_csv(output_dir / "summary_metrics.csv", index=False)
    action.to_csv(output_dir / "action_metrics.csv", index=False)
    grouped.to_csv(output_dir / "grouped_metrics.csv", index=False)
    importance.to_csv(output_dir / "feature_importance.csv", index=False)
    (output_dir / "model_artifact.json").write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
    write_report(output_dir=output_dir, summary=summary, action=action, grouped=grouped, folds=folds, importance=importance, config=config)
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "issue": "https://github.com/FALK-BRAUER/kumo-qc/issues/490",
        "feature_version": FEATURE_VERSION,
        "config": asdict(config),
        "outputs": {
            "oof_predictions.csv.gz": {"rows": int(len(predictions))},
            "fold_summary.csv": {"rows": int(len(folds))},
            "summary_metrics.csv": {"rows": int(len(summary))},
            "action_metrics.csv": {"rows": int(len(action))},
            "grouped_metrics.csv": {"rows": int(len(grouped))},
            "feature_importance.csv": {"rows": int(len(importance))},
            "model_artifact.json": {"schema_version": MODEL_SCHEMA_VERSION},
            "intraday_entry_exit_policy_report.md": {},
        },
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return {
        "oof_predictions": pred_path,
        "fold_summary": output_dir / "fold_summary.csv",
        "summary_metrics": output_dir / "summary_metrics.csv",
        "action_metrics": output_dir / "action_metrics.csv",
        "grouped_metrics": output_dir / "grouped_metrics.csv",
        "feature_importance": output_dir / "feature_importance.csv",
        "model_artifact": output_dir / "model_artifact.json",
        "report": output_dir / "intraday_entry_exit_policy_report.md",
        "manifest": output_dir / "manifest.json",
    }


def run(
    *,
    panel_path: Path = DEFAULT_PANEL,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    n_folds: int = 6,
    min_train_folds: int = 1,
    max_iter: int = 140,
    learning_rate: float = 0.05,
    l2: float = 0.01,
    limit: int | None = None,
) -> dict[str, Path]:
    config = PolicyConfig(
        panel=str(panel_path),
        output_dir=str(output_dir),
        n_folds=n_folds,
        min_train_folds=min_train_folds,
        max_iter=max_iter,
        learning_rate=learning_rate,
        l2=l2,
        limit=limit,
    )
    panel = read_panel(panel_path, limit=limit)
    print(f"loaded panel rows={len(panel)} from {panel_path}", file=sys.stderr, flush=True)
    panel, feature_names = add_policy_features(panel)
    print(f"built feature matrix columns={len(feature_names)} hash={feature_hash(feature_names)}", file=sys.stderr, flush=True)
    prediction_frames: list[pd.DataFrame] = []
    fold_frames: list[pd.DataFrame] = []
    coef_frames: list[pd.DataFrame] = []
    artifacts: dict[str, Any] = {
        "schema_version": MODEL_SCHEMA_VERSION,
        "feature_version": FEATURE_VERSION,
        "feature_hash": feature_hash(feature_names),
        "feature_names": feature_names,
        "policies": {},
    }
    for policy_name in ("entry_policy", "management_policy"):
        print(f"starting {policy_name}", file=sys.stderr, flush=True)
        preds, folds, coefs, artifact = fit_oof_policy(panel, feature_names, policy_name=policy_name, config=config)
        print(f"finished {policy_name}", file=sys.stderr, flush=True)
        prediction_frames.append(preds)
        fold_frames.append(folds)
        coef_frames.append(coefs)
        artifacts["policies"][policy_name] = artifact
    predictions = pd.concat(prediction_frames, ignore_index=True)
    folds = pd.concat(fold_frames, ignore_index=True)
    coefs = pd.concat(coef_frames, ignore_index=True)
    summary = pd.concat([summary_metrics(frame) for frame in prediction_frames], ignore_index=True)
    action = pd.concat(
        [action_metrics(frame, pred_col=pred_col) for frame in prediction_frames for pred_col in ("predicted_action", "baseline_action")],
        ignore_index=True,
    )
    grouped = pd.concat(
        [
            grouped_summary(frame.assign(month=frame["scan_date"].astype(str).str.slice(0, 7)), group_col=group_col)
            for frame in prediction_frames
            for group_col in ("scanner_source_bucket", "month", "fold_490")
        ],
        ignore_index=True,
    )
    importance = feature_importance(coefs)
    return write_outputs(
        predictions=predictions,
        folds=folds,
        summary=summary,
        action=action,
        grouped=grouped,
        importance=importance,
        artifact=artifacts,
        config=config,
        output_dir=output_dir,
    )


def main() -> None:
    args = _args()
    outputs = run(
        panel_path=args.panel,
        output_dir=args.output_dir,
        n_folds=args.n_folds,
        min_train_folds=args.min_train_folds,
        max_iter=args.max_iter,
        learning_rate=args.learning_rate,
        l2=args.l2,
        limit=args.limit,
    )
    for label, path in outputs.items():
        print(f"{label}: {path}")


if __name__ == "__main__":
    main()
