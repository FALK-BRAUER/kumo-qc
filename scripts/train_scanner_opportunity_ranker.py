"""Train leakage-safe scanner opportunity rankers (#467)."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
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

from scripts import build_scanner_opportunity_path_labels as path_labels  # noqa: E402

DEFAULT_LABELS = ROOT / "sweeps" / "reports" / "scanner_opportunity_paths_464" / "opportunity_path_labels.csv.gz"
DEFAULT_PANEL = ROOT / "sweeps" / "reports" / "scanner_opportunity_panel_463" / "opportunity_panel.csv.gz"
DEFAULT_OUTPUT_DIR = ROOT / "sweeps" / "reports" / "scanner_opportunity_ranker_467"
DEFAULT_CANDIDATE_FILTER = "kumo_top100_or_george"
FEATURE_VERSION = "scanner_opportunity_scan_time_v1"
MODEL_SCHEMA_VERSION = 1
TARGETS = ("trade_worthy", "runner")
KS = (5, 10, 20, 50)
DENIED_FEATURE_TOKENS = ("george", "label", "future", "ocr", "watchlist", "video", "post", "transcript")

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
    "label_path_status",
    "label_entry_gap_pct",
    "label_ret_20d_close_pct",
    "label_mfe_20d_pct",
    "label_mae_20d_pct",
    "label_ret_40d_close_pct",
    "label_mfe_40d_pct",
    "label_runner_candidate_20d",
    "label_normal_winner_20d",
    "label_bad_trade_20d",
    "label_extreme_path_flag",
    "label_outcome_20d",
]

PANEL_COLUMNS = [
    "scan_date",
    "symbol",
    "kumo_close",
    "kumo_volume",
    "kumo_dollar_vol",
    "kumo_gap_pct",
    "kumo_vol_ratio_20d",
    "company_sector",
    "company_industry",
    "sector_category",
    "sector_etf_proxy",
]

BASE_FEATURES = [
    "kumo_rank_by_score",
    "kumo_rank_inverse",
    "kumo_score",
    "kumo_gap_pct",
    "kumo_gap_abs",
    "kumo_gap_positive",
    "kumo_gap_negative_abs",
    "kumo_vol_ratio_20d",
    "kumo_dollar_vol_log",
    "kumo_volume_log",
    "kumo_close_log",
    "rank_le_10",
    "rank_le_20",
    "rank_le_50",
    "score_ge_7",
    "score_ge_8",
    "gap_between_minus2_5",
    "gap_gt_8",
    "gap_lt_minus5",
    "has_sector_proxy",
    "is_kumo_top_n",
    "is_kumo_scanner",
]

PANEL_RANK_SPECS = (
    ("kumo_score", "score", False),
    ("kumo_rank_by_score", "rank", True),
    ("kumo_gap_pct", "gap", False),
    ("kumo_gap_abs", "gap_abs", True),
    ("kumo_vol_ratio_20d", "relvol", False),
    ("kumo_dollar_vol_log", "dollar_vol", False),
)


@dataclass(frozen=True)
class Standardizer:
    mean: np.ndarray
    scale: np.ndarray


@dataclass(frozen=True)
class LinearModel:
    coef: np.ndarray
    intercept: float


@dataclass(frozen=True)
class RankerConfig:
    labels: str
    panel: str
    output_dir: str
    candidate_filter: str
    n_folds: int
    min_train_folds: int
    max_iter: int
    learning_rate: float
    l2: float
    negatives_per_positive: int
    limit: int | None


@dataclass(frozen=True)
class FoldModel:
    target: str
    fold: int
    valid_start: str
    valid_end: str
    train_rows: int
    valid_rows: int
    model: LinearModel
    standardizer: Standardizer


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--panel", type=Path, default=DEFAULT_PANEL)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--candidate-filter", choices=CANDIDATE_FILTERS, default=DEFAULT_CANDIDATE_FILTER)
    parser.add_argument("--n-folds", type=int, default=6)
    parser.add_argument("--min-train-folds", type=int, default=1)
    parser.add_argument("--max-iter", type=int, default=250)
    parser.add_argument("--learning-rate", type=float, default=0.02)
    parser.add_argument("--l2", type=float, default=0.01)
    parser.add_argument("--negatives-per-positive", type=int, default=25)
    parser.add_argument("--limit", type=int, default=None, help="Optional row limit after filtering.")
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


def _safe_log1p(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    return np.log1p(values.clip(lower=0.0))


def feature_hash(feature_names: Sequence[str]) -> str:
    payload = {
        "feature_version": FEATURE_VERSION,
        "feature_names": list(feature_names),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def validate_feature_names(feature_names: Sequence[str]) -> None:
    denied = [
        feature
        for feature in feature_names
        if any(token in feature.lower() for token in DENIED_FEATURE_TOKENS)
    ]
    if denied:
        raise ValueError(f"scan-time feature set contains denied leakage features: {denied}")


def read_panel(labels_path: Path, panel_path: Path, *, candidate_filter: str, limit: int | None) -> pd.DataFrame:
    if not labels_path.exists():
        raise FileNotFoundError(labels_path)
    if not panel_path.exists():
        raise FileNotFoundError(panel_path)
    labels = pd.read_csv(labels_path, usecols=lambda column: column in set(LABEL_COLUMNS), low_memory=False)
    labels["scan_date"] = labels["scan_date"].map(_parse_day)
    labels["symbol"] = labels["symbol"].map(_clean_symbol)
    for column in BOOL_COLUMNS:
        labels[column] = _bool_series(labels[column])

    panel = pd.read_csv(panel_path, usecols=lambda column: column in set(PANEL_COLUMNS), low_memory=False)
    panel["scan_date"] = panel["scan_date"].map(_parse_day)
    panel["symbol"] = panel["symbol"].map(_clean_symbol)
    panel = panel.drop_duplicates(["scan_date", "symbol"], keep="first")
    frame = labels.merge(panel, on=["scan_date", "symbol"], how="left")
    frame = frame[frame["label_path_status"].astype(str).str.startswith("available")].copy()
    frame = filter_candidates(frame, candidate_filter)
    if limit is not None:
        frame = frame.head(limit).copy()
    frame["opportunity_id"] = frame["scan_date"] + "|" + frame["symbol"]
    frame["true_runner_40d"] = (
        frame["label_runner_candidate_20d"]
        | _num(frame, "label_mfe_40d_pct").ge(25.0)
        | _num(frame, "label_ret_40d_close_pct").ge(15.0)
    )
    frame["target_trade_worthy"] = (
        (frame["label_runner_candidate_20d"] | frame["label_normal_winner_20d"])
        & ~frame["label_bad_trade_20d"]
        & _num(frame, "label_ret_20d_close_pct").notna()
    )
    frame["target_runner"] = frame["true_runner_40d"]
    frame["target_fail_risk"] = frame["label_bad_trade_20d"]
    return frame.sort_values(["scan_date", "symbol"]).reset_index(drop=True)


def filter_candidates(frame: pd.DataFrame, candidate_filter: str) -> pd.DataFrame:
    rank = _num(frame, "kumo_rank_by_score")
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


def add_scan_time_features(frame: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    out = frame.copy()
    rank = _num(out, "kumo_rank_by_score")
    score = _num(out, "kumo_score")
    gap = _num(out, "kumo_gap_pct")
    out["kumo_rank_by_score"] = rank
    out["kumo_rank_inverse"] = -rank
    out["kumo_score"] = score
    out["kumo_gap_pct"] = gap
    out["kumo_gap_abs"] = gap.abs()
    out["kumo_gap_positive"] = gap.clip(lower=0.0)
    out["kumo_gap_negative_abs"] = (-gap).clip(lower=0.0)
    out["kumo_vol_ratio_20d"] = _num(out, "kumo_vol_ratio_20d")
    out["kumo_dollar_vol_log"] = _safe_log1p(out.get("kumo_dollar_vol", pd.Series(np.nan, index=out.index)))
    out["kumo_volume_log"] = _safe_log1p(out.get("kumo_volume", pd.Series(np.nan, index=out.index)))
    out["kumo_close_log"] = _safe_log1p(out.get("kumo_close", pd.Series(np.nan, index=out.index)))
    out["rank_le_10"] = rank.le(10).astype(float)
    out["rank_le_20"] = rank.le(20).astype(float)
    out["rank_le_50"] = rank.le(50).astype(float)
    out["score_ge_7"] = score.ge(7).astype(float)
    out["score_ge_8"] = score.ge(8).astype(float)
    out["gap_between_minus2_5"] = gap.between(-2, 5).astype(float)
    out["gap_gt_8"] = gap.gt(8).astype(float)
    out["gap_lt_minus5"] = gap.lt(-5).astype(float)
    out["has_sector_proxy"] = out.get("sector_etf_proxy", pd.Series("", index=out.index)).astype(str).str.len().gt(0).astype(float)
    out["is_kumo_top_n"] = out["kumo_top_n"].astype(float)
    out["is_kumo_scanner"] = out["kumo_scanner"].astype(float)
    out = add_panel_rank_features(out)
    features = list(BASE_FEATURES) + [
        feature
        for _source, prefix, _ascending in PANEL_RANK_SPECS
        for feature in (f"{prefix}_rank_in_day", f"{prefix}_pctile_in_day")
    ]
    validate_feature_names(features)
    return out, features


def add_panel_rank_features(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    group = out["scan_date"].astype(str)
    for source, prefix, ascending in PANEL_RANK_SPECS:
        values = _num(out, source)
        out[f"{prefix}_rank_in_day"] = values.groupby(group).rank(method="average", ascending=ascending)
        pct_ascending = not ascending
        out[f"{prefix}_pctile_in_day"] = values.groupby(group).rank(pct=True, ascending=pct_ascending)
    return out


def build_feature_matrix(frame: pd.DataFrame, feature_names: Sequence[str]) -> np.ndarray:
    columns = [_num(frame, feature).to_numpy(dtype=float) for feature in feature_names]
    if not columns:
        return np.empty((len(frame), 0), dtype=float)
    return np.column_stack(columns).astype(float)


def fit_standardizer(x_train: np.ndarray) -> Standardizer:
    if x_train.shape[1] == 0:
        return Standardizer(mean=np.empty(0), scale=np.empty(0))
    clean = np.where(np.isfinite(x_train), x_train, np.nan)
    with np.errstate(invalid="ignore"):
        mean = np.nanmean(clean, axis=0)
    mean = np.where(np.isfinite(mean), mean, 0.0)
    filled = np.where(np.isfinite(x_train), x_train, mean)
    scale = filled.std(axis=0)
    scale = np.where(np.isfinite(scale) & (scale > 1e-9), scale, 1.0)
    return Standardizer(mean=mean, scale=scale)


def apply_standardizer(x: np.ndarray, standardizer: Standardizer) -> np.ndarray:
    if x.shape[1] == 0:
        return x
    filled = np.where(np.isfinite(x), x, standardizer.mean)
    return np.asarray((filled - standardizer.mean) / standardizer.scale, dtype=float)


def _sigmoid(values: np.ndarray) -> np.ndarray:
    clipped = np.clip(values, -40.0, 40.0)
    return np.asarray(1.0 / (1.0 + np.exp(-clipped)), dtype=float)


def _sample_pairwise_diffs(
    x: np.ndarray,
    y: np.ndarray,
    dates: Sequence[str],
    *,
    negatives_per_positive: int,
) -> np.ndarray:
    diffs: list[np.ndarray] = []
    date_values = np.asarray([str(date) for date in dates], dtype=object)
    neg_limit = max(1, int(negatives_per_positive))
    for date in sorted(set(date_values.tolist())):
        date_mask = date_values == date
        pos_idx = np.flatnonzero(date_mask & (y >= 0.5))
        neg_idx = np.flatnonzero(date_mask & (y < 0.5))
        if len(pos_idx) == 0 or len(neg_idx) == 0:
            continue
        if len(neg_idx) > neg_limit:
            selector = np.linspace(0, len(neg_idx) - 1, neg_limit, dtype=int)
            neg_idx = neg_idx[selector]
        for pos in pos_idx:
            diffs.append(x[pos] - x[neg_idx])
    if not diffs:
        return np.empty((0, x.shape[1]), dtype=float)
    diff_matrix = np.vstack(diffs).astype(float)
    return np.clip(np.nan_to_num(diff_matrix, nan=0.0, posinf=0.0, neginf=0.0), -10.0, 10.0)


def fit_pairwise_linear_ranker(
    x: np.ndarray,
    y: np.ndarray,
    dates: Sequence[str],
    *,
    max_iter: int,
    learning_rate: float,
    l2: float,
    negatives_per_positive: int,
) -> LinearModel:
    if len(y) == 0 or x.shape[1] == 0 or y.min() == y.max():
        return LinearModel(coef=np.zeros(x.shape[1], dtype=float), intercept=0.0)
    diffs = _sample_pairwise_diffs(x, y, dates, negatives_per_positive=negatives_per_positive)
    if len(diffs) == 0:
        return LinearModel(coef=np.zeros(x.shape[1], dtype=float), intercept=0.0)
    coef = np.zeros(x.shape[1], dtype=float)
    denom = float(len(diffs))
    for _ in range(max_iter):
        with np.errstate(over="ignore", divide="ignore", invalid="ignore"):
            margin_raw = diffs @ coef
        margin = np.clip(np.nan_to_num(margin_raw, nan=0.0, posinf=40.0, neginf=-40.0), -40.0, 40.0)
        pred = _sigmoid(margin)
        with np.errstate(over="ignore", divide="ignore", invalid="ignore"):
            grad_coef = -(diffs.T @ (1.0 - pred)) / denom + l2 * coef
        grad_coef = np.nan_to_num(grad_coef, nan=0.0, posinf=0.0, neginf=0.0)
        grad_norm = float(np.linalg.norm(grad_coef))
        if grad_norm > 10.0:
            grad_coef *= 10.0 / grad_norm
        coef -= learning_rate * grad_coef
        coef = np.clip(np.nan_to_num(coef, nan=0.0, posinf=0.0, neginf=0.0), -20.0, 20.0)
    return LinearModel(coef=coef, intercept=0.0)


def predict_score(model: LinearModel, x: np.ndarray) -> np.ndarray:
    with np.errstate(over="ignore", divide="ignore", invalid="ignore"):
        scores = np.asarray(x @ model.coef + model.intercept, dtype=float)
    return np.nan_to_num(scores, nan=0.0, posinf=0.0, neginf=0.0)


def make_walk_forward_splits(dates: Sequence[str], *, n_folds: int, min_train_folds: int) -> list[dict[str, Any]]:
    unique_dates = sorted(set(str(date) for date in dates))
    if not unique_dates:
        return []
    fold_count = max(2, min(int(n_folds), len(unique_dates)))
    chunks = [list(arr.tolist()) for arr in np.array_split(np.array(unique_dates, dtype=object), fold_count)]
    splits: list[dict[str, Any]] = []
    for idx in range(max(1, int(min_train_folds)), len(chunks)):
        train_dates = {str(day) for chunk in chunks[:idx] for day in chunk}
        valid_dates = {str(day) for day in chunks[idx]}
        if not train_dates or not valid_dates:
            continue
        splits.append(
            {
                "fold": idx,
                "train_dates": train_dates,
                "valid_dates": valid_dates,
                "valid_start": min(valid_dates),
                "valid_end": max(valid_dates),
            }
        )
    return splits


def fit_oof_rankers(
    panel: pd.DataFrame,
    feature_names: Sequence[str],
    *,
    config: RankerConfig,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    x_raw = build_feature_matrix(panel, feature_names)
    predictions = panel.copy()
    predictions["feature_version"] = FEATURE_VERSION
    predictions["feature_hash"] = feature_hash(feature_names)
    predictions["oof_available"] = False
    predictions["fold"] = np.nan
    for target in TARGETS:
        predictions[f"model_{target}_score"] = np.nan

    y_by_target = {
        "trade_worthy": predictions["target_trade_worthy"].astype(float).to_numpy(dtype=float),
        "runner": predictions["target_runner"].astype(float).to_numpy(dtype=float),
    }
    splits = make_walk_forward_splits(
        predictions["scan_date"].astype(str).tolist(),
        n_folds=config.n_folds,
        min_train_folds=config.min_train_folds,
    )
    fold_rows: list[dict[str, Any]] = []
    models_by_target: dict[str, list[FoldModel]] = {target: [] for target in TARGETS}
    for split in splits:
        valid_mask = predictions["scan_date"].isin(split["valid_dates"]).to_numpy(dtype=bool)
        train_mask = predictions["scan_date"].isin(split["train_dates"]).to_numpy(dtype=bool)
        standardizer = fit_standardizer(x_raw[train_mask])
        x_train = apply_standardizer(x_raw[train_mask], standardizer)
        x_valid = apply_standardizer(x_raw[valid_mask], standardizer)
        train_dates = predictions.loc[train_mask, "scan_date"].astype(str).tolist()
        for target in TARGETS:
            y_train = y_by_target[target][train_mask]
            model = fit_pairwise_linear_ranker(
                x_train,
                y_train,
                train_dates,
                max_iter=config.max_iter,
                learning_rate=config.learning_rate,
                l2=config.l2,
                negatives_per_positive=config.negatives_per_positive,
            )
            scores = predict_score(model, x_valid)
            predictions.loc[valid_mask, f"model_{target}_score"] = scores
            models_by_target[target].append(
                FoldModel(
                    target=target,
                    fold=int(split["fold"]),
                    valid_start=str(split["valid_start"]),
                    valid_end=str(split["valid_end"]),
                    train_rows=int(train_mask.sum()),
                    valid_rows=int(valid_mask.sum()),
                    model=model,
                    standardizer=standardizer,
                )
            )
            fold_rows.append(
                {
                    "target": target,
                    "fold": int(split["fold"]),
                    "train_start": min(split["train_dates"]),
                    "train_end": max(split["train_dates"]),
                    "valid_start": split["valid_start"],
                    "valid_end": split["valid_end"],
                    "train_rows": int(train_mask.sum()),
                    "valid_rows": int(valid_mask.sum()),
                    "train_positive_pct": round(100.0 * float(y_train.mean()), 3) if len(y_train) else 0.0,
                    "coef_nonzero": int(np.count_nonzero(np.abs(model.coef) > 1e-12)),
                }
            )
        predictions.loc[valid_mask, "oof_available"] = True
        predictions.loc[valid_mask, "fold"] = int(split["fold"])

    predictions["model_combined_score"] = (
        0.70 * predictions["model_trade_worthy_score"] + 0.30 * predictions["model_runner_score"]
    )
    predictions["baseline_kumo_rank_score"] = -_num(predictions, "kumo_rank_by_score")
    predictions["baseline_kumo_score"] = _num(predictions, "kumo_score")
    predictions["baseline_rule_score"] = (
        _num(predictions, "kumo_score").fillna(0.0)
        + 0.35 * predictions["gap_between_minus2_5"].astype(float)
        - 0.50 * predictions["gap_gt_8"].astype(float)
        - 0.35 * predictions["gap_lt_minus5"].astype(float)
        + 0.20 * predictions["rank_le_20"].astype(float)
    )
    coef_summary = coefficient_summary(models_by_target, list(feature_names))
    final_artifact = fit_final_artifact(panel, feature_names, config=config)
    return predictions, pd.DataFrame(fold_rows), coef_summary, final_artifact


def coefficient_summary(models_by_target: dict[str, list[FoldModel]], feature_names: list[str]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for target, fold_models in models_by_target.items():
        if not fold_models:
            continue
        coefs = np.vstack([fold.model.coef for fold in fold_models])
        for idx, feature in enumerate(feature_names):
            rows.append(
                {
                    "target": target,
                    "feature": feature,
                    "coef_mean": round(float(coefs[:, idx].mean()), 6),
                    "coef_abs_mean": round(float(np.abs(coefs[:, idx]).mean()), 6),
                    "coef_std": round(float(coefs[:, idx].std()), 6),
                }
            )
    return pd.DataFrame(rows).sort_values(["target", "coef_abs_mean"], ascending=[True, False]).reset_index(drop=True)


def fit_final_artifact(panel: pd.DataFrame, feature_names: Sequence[str], *, config: RankerConfig) -> dict[str, Any]:
    x_raw = build_feature_matrix(panel, feature_names)
    standardizer = fit_standardizer(x_raw)
    x = apply_standardizer(x_raw, standardizer)
    dates = panel["scan_date"].astype(str).tolist()
    models: dict[str, Any] = {}
    for target, column in {"trade_worthy": "target_trade_worthy", "runner": "target_runner"}.items():
        y = panel[column].astype(float).to_numpy(dtype=float)
        model = fit_pairwise_linear_ranker(
            x,
            y,
            dates,
            max_iter=config.max_iter,
            learning_rate=config.learning_rate,
            l2=config.l2,
            negatives_per_positive=config.negatives_per_positive,
        )
        models[target] = {
            "coef": [round(float(value), 10) for value in model.coef.tolist()],
            "intercept": round(float(model.intercept), 10),
        }
    return {
        "schema_version": MODEL_SCHEMA_VERSION,
        "model_type": "linear_pairwise_ranker",
        "feature_version": FEATURE_VERSION,
        "feature_hash": feature_hash(feature_names),
        "feature_names": list(feature_names),
        "standardizer": {
            "mean": [round(float(value), 10) for value in standardizer.mean.tolist()],
            "scale": [round(float(value), 10) for value in standardizer.scale.tolist()],
        },
        "models": models,
        "combined_score": {"trade_worthy_weight": 0.70, "runner_weight": 0.30},
        "training_rows": int(len(panel)),
        "training_dates": [str(panel["scan_date"].min()), str(panel["scan_date"].max())],
    }


def _dcg(values: Sequence[float]) -> float:
    return float(sum((2.0**value - 1.0) / np.log2(idx + 2.0) for idx, value in enumerate(values)))


def topk_metrics(predictions: pd.DataFrame, *, target_col: str, score_col: str, ks: Sequence[int] = KS) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    frame = predictions[predictions[score_col].notna()].copy()
    for k in ks:
        selected_total = 0
        positives_total = 0
        hits_total = 0
        ndcgs: list[float] = []
        ret_values: list[float] = []
        mfe_values: list[float] = []
        bad_values: list[float] = []
        date_count = 0
        for _date, group in frame.groupby("scan_date", sort=True):
            positives = int(group[target_col].astype(bool).sum())
            if positives == 0:
                continue
            ranked = group.sort_values(score_col, ascending=False).head(k)
            selected = len(ranked)
            hits = int(ranked[target_col].astype(bool).sum())
            ideal = [1.0] * min(k, positives)
            actual = ranked[target_col].astype(float).tolist()
            ndcgs.append(_dcg(actual) / _dcg(ideal) if ideal else 0.0)
            selected_total += selected
            positives_total += positives
            hits_total += hits
            date_count += 1
            ret_values.extend(pd.to_numeric(ranked["label_ret_20d_close_pct"], errors="coerce").dropna().tolist())
            mfe_values.extend(pd.to_numeric(ranked["label_mfe_20d_pct"], errors="coerce").dropna().tolist())
            bad_values.extend(ranked["label_bad_trade_20d"].astype(float).tolist())
        rows.append(
            {
                "target": target_col.replace("target_", ""),
                "score": score_col,
                "k": int(k),
                "dates": int(date_count),
                "selected_rows": int(selected_total),
                "positive_rows": int(positives_total),
                "hit_rows": int(hits_total),
                "recall_pct": round(100.0 * hits_total / positives_total, 3) if positives_total else 0.0,
                "precision_pct": round(100.0 * hits_total / selected_total, 3) if selected_total else 0.0,
                "ndcg_mean": round(float(np.mean(ndcgs)), 4) if ndcgs else 0.0,
                "avg_ret20_topk_pct": round(float(np.mean(ret_values)), 4) if ret_values else None,
                "avg_mfe20_topk_pct": round(float(np.mean(mfe_values)), 4) if mfe_values else None,
                "bad_trade_pct_topk": round(100.0 * float(np.mean(bad_values)), 3) if bad_values else 0.0,
            }
        )
    return pd.DataFrame(rows)


def build_metric_summary(predictions: pd.DataFrame) -> pd.DataFrame:
    score_cols = [
        "baseline_kumo_rank_score",
        "baseline_kumo_score",
        "baseline_rule_score",
        "model_trade_worthy_score",
        "model_runner_score",
        "model_combined_score",
    ]
    frames: list[pd.DataFrame] = []
    oof = predictions[predictions["oof_available"]].copy()
    for target in ("target_trade_worthy", "target_runner"):
        for score in score_cols:
            source = oof if score.startswith("model_") else oof
            frames.append(topk_metrics(source, target_col=target, score_col=score))
    return pd.concat(frames, ignore_index=True)


def monthly_stability(predictions: pd.DataFrame, *, k: int = 10) -> pd.DataFrame:
    frame = predictions[predictions["oof_available"]].copy()
    frame["month"] = frame["scan_date"].astype(str).str.slice(0, 7)
    rows: list[dict[str, Any]] = []
    for score in ("baseline_kumo_rank_score", "baseline_rule_score", "model_combined_score"):
        for month, month_frame in frame.groupby("month", sort=True):
            selected = []
            for _date, group in month_frame.groupby("scan_date", sort=True):
                selected.append(group.sort_values(score, ascending=False).head(k))
            if not selected:
                continue
            top = pd.concat(selected, ignore_index=True)
            rows.append(
                {
                    "month": month,
                    "score": score,
                    "selected_rows": int(len(top)),
                    "trade_worthy_precision_pct": round(100.0 * float(top["target_trade_worthy"].mean()), 3),
                    "runner_precision_pct": round(100.0 * float(top["target_runner"].mean()), 3),
                    "avg_ret20_top10_pct": round(float(pd.to_numeric(top["label_ret_20d_close_pct"], errors="coerce").mean()), 4),
                    "bad_trade_pct": round(100.0 * float(top["label_bad_trade_20d"].mean()), 3),
                }
            )
    return pd.DataFrame(rows)


def prediction_output(predictions: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "scan_date",
        "symbol",
        "opportunity_id",
        "feature_version",
        "feature_hash",
        "fold",
        "oof_available",
        "kumo_scanner",
        "kumo_top_n",
        "george_scanner_positive",
        "george_watchlist",
        "source_tags",
        "kumo_rank_by_score",
        "kumo_score",
        "target_trade_worthy",
        "target_runner",
        "target_fail_risk",
        "label_ret_20d_close_pct",
        "label_mfe_20d_pct",
        "label_bad_trade_20d",
        "baseline_kumo_rank_score",
        "baseline_kumo_score",
        "baseline_rule_score",
        "model_trade_worthy_score",
        "model_runner_score",
        "model_combined_score",
    ]
    return predictions.loc[:, columns].copy()


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
    predictions: pd.DataFrame,
    metrics: pd.DataFrame,
    fold_summary: pd.DataFrame,
    coef_summary: pd.DataFrame,
    config: RankerConfig,
) -> None:
    top10 = metrics[(metrics["k"] == 10) & (metrics["target"] == "trade_worthy")].sort_values(
        ["precision_pct", "recall_pct"],
        ascending=False,
    )
    runner10 = metrics[(metrics["k"] == 10) & (metrics["target"] == "runner")].sort_values(
        ["precision_pct", "recall_pct"],
        ascending=False,
    )
    lines = [
        "# Scanner Opportunity Ranker #467",
        "",
        "This report trains dependency-free pairwise linear rankers on future-path labels using",
        "only scan-time features. Validation is expanding-window by scan date; no random split is used.",
        "",
        "## Inputs",
        "",
        f"- Labels: `{config.labels}`",
        f"- Panel metadata: `{config.panel}`",
        f"- Candidate filter: `{config.candidate_filter}`",
        "",
        "## Coverage",
        "",
        f"- Rows: `{len(predictions)}`",
        f"- Dates: `{predictions['scan_date'].nunique()}`",
        f"- OOF rows: `{int(predictions['oof_available'].sum())}`",
        f"- Feature version: `{FEATURE_VERSION}`",
        f"- Feature hash: `{predictions['feature_hash'].iloc[0] if len(predictions) else ''}`",
        "",
        "## Top-10 Trade-Worthy Ranking",
        "",
        _markdown_table(
            top10,
            [
                "score",
                "selected_rows",
                "hit_rows",
                "recall_pct",
                "precision_pct",
                "ndcg_mean",
                "avg_ret20_topk_pct",
                "bad_trade_pct_topk",
            ],
        ),
        "",
        "## Top-10 Runner Ranking",
        "",
        _markdown_table(
            runner10,
            [
                "score",
                "selected_rows",
                "hit_rows",
                "recall_pct",
                "precision_pct",
                "ndcg_mean",
                "avg_ret20_topk_pct",
                "bad_trade_pct_topk",
            ],
        ),
        "",
        "## Fold Summary",
        "",
        _markdown_table(
            fold_summary,
            [
                "target",
                "fold",
                "train_start",
                "train_end",
                "valid_start",
                "valid_end",
                "train_rows",
                "valid_rows",
                "train_positive_pct",
                "coef_nonzero",
            ],
        ),
        "",
        "## Feature Diagnostics",
        "",
        _markdown_table(
            coef_summary,
            ["target", "feature", "coef_mean", "coef_abs_mean", "coef_std"],
            limit=30,
        ),
        "",
        "## Integration Notes",
        "",
        "- `oof_predictions.csv.gz` contains date, symbol, labels, source flags, feature hash/version,",
        "  baseline scores, and OOF model predictions.",
        "- `model_artifact.json` is a compact linear ranker artifact for #468 conversion/testing; it is",
        "  not wired into LEAN/QC yet.",
        "- Feature names are guarded against George/source/future-label tokens.",
        "",
    ]
    (output_dir / "opportunity_ranker_report.md").write_text("\n".join(lines), encoding="utf-8")


def write_outputs(
    *,
    predictions: pd.DataFrame,
    fold_summary: pd.DataFrame,
    metrics: pd.DataFrame,
    monthly: pd.DataFrame,
    coef_summary: pd.DataFrame,
    model_artifact: dict[str, Any],
    config: RankerConfig,
    output_dir: Path,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "README.md").write_text(
        "# scanner_opportunity_ranker_467/\n\n"
        "Leakage-safe opportunity-ranker research for issue #467. Keep compact OOF predictions, "
        "metrics, diagnostics, and integration-friendly JSON here; do not store bulky run folders.\n",
        encoding="utf-8",
    )
    oof_path = output_dir / "oof_predictions.csv.gz"
    _write_gzip_csv(prediction_output(predictions), oof_path)
    fold_summary.to_csv(output_dir / "fold_summary.csv", index=False)
    metrics.to_csv(output_dir / "topk_metrics.csv", index=False)
    monthly.to_csv(output_dir / "monthly_stability.csv", index=False)
    coef_summary.to_csv(output_dir / "feature_importance.csv", index=False)
    (output_dir / "model_artifact.json").write_text(json.dumps(model_artifact, indent=2) + "\n", encoding="utf-8")
    write_report(
        output_dir=output_dir,
        predictions=predictions,
        metrics=metrics,
        fold_summary=fold_summary,
        coef_summary=coef_summary,
        config=config,
    )
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "issue": "https://github.com/FALK-BRAUER/kumo-qc/issues/467",
        "config": asdict(config),
        "feature_version": FEATURE_VERSION,
        "feature_hash": model_artifact["feature_hash"],
        "outputs": {
            "oof_predictions.csv.gz": {"rows": int(len(predictions))},
            "fold_summary.csv": {"rows": int(len(fold_summary))},
            "topk_metrics.csv": {"rows": int(len(metrics))},
            "monthly_stability.csv": {"rows": int(len(monthly))},
            "feature_importance.csv": {"rows": int(len(coef_summary))},
            "model_artifact.json": {"schema_version": MODEL_SCHEMA_VERSION},
            "opportunity_ranker_report.md": {},
        },
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return {
        "oof_predictions": oof_path,
        "fold_summary": output_dir / "fold_summary.csv",
        "topk_metrics": output_dir / "topk_metrics.csv",
        "monthly_stability": output_dir / "monthly_stability.csv",
        "feature_importance": output_dir / "feature_importance.csv",
        "model_artifact": output_dir / "model_artifact.json",
        "report": output_dir / "opportunity_ranker_report.md",
        "manifest": output_dir / "manifest.json",
    }


def run(
    *,
    labels_path: Path = DEFAULT_LABELS,
    panel_path: Path = DEFAULT_PANEL,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    candidate_filter: str = DEFAULT_CANDIDATE_FILTER,
    n_folds: int = 6,
    min_train_folds: int = 1,
    max_iter: int = 250,
    learning_rate: float = 0.02,
    l2: float = 0.01,
    negatives_per_positive: int = 25,
    limit: int | None = None,
) -> dict[str, Path]:
    config = RankerConfig(
        labels=str(labels_path),
        panel=str(panel_path),
        output_dir=str(output_dir),
        candidate_filter=candidate_filter,
        n_folds=n_folds,
        min_train_folds=min_train_folds,
        max_iter=max_iter,
        learning_rate=learning_rate,
        l2=l2,
        negatives_per_positive=negatives_per_positive,
        limit=limit,
    )
    panel = read_panel(labels_path, panel_path, candidate_filter=candidate_filter, limit=limit)
    panel, feature_names = add_scan_time_features(panel)
    predictions, fold_summary, coef_summary, model_artifact = fit_oof_rankers(panel, feature_names, config=config)
    metrics = build_metric_summary(predictions)
    monthly = monthly_stability(predictions)
    return write_outputs(
        predictions=predictions,
        fold_summary=fold_summary,
        metrics=metrics,
        monthly=monthly,
        coef_summary=coef_summary,
        model_artifact=model_artifact,
        config=config,
        output_dir=output_dir,
    )


def main() -> None:
    args = _args()
    outputs = run(
        labels_path=args.labels,
        panel_path=args.panel,
        output_dir=args.output_dir,
        candidate_filter=args.candidate_filter,
        n_folds=args.n_folds,
        min_train_folds=args.min_train_folds,
        max_iter=args.max_iter,
        learning_rate=args.learning_rate,
        l2=args.l2,
        negatives_per_positive=args.negatives_per_positive,
        limit=args.limit,
    )
    for label, path in outputs.items():
        print(f"{label}: {path}")


if __name__ == "__main__":
    main()
