"""Train scan-time scanner ranking models from #482 optimal/bad labels."""
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

DEFAULT_UNIVERSE = ROOT / "sweeps" / "reports" / "scanner_trade_universe_482" / "scanner_trade_universe.csv.gz"
DEFAULT_PANEL = ROOT / "sweeps" / "reports" / "scanner_opportunity_panel_463" / "opportunity_panel.csv.gz"
DEFAULT_OUTPUT_DIR = ROOT / "sweeps" / "reports" / "scan_time_scanner_ranker_492"
FEATURE_VERSION = "scan_time_scanner_ranker_492_v1"
MODEL_SCHEMA_VERSION = 1
TARGETS = ("optimal", "bad_risk")
KS = (5, 10, 20, 50)
BLEND_RISK_WEIGHTS = (0.25, 0.50, 0.75)
DENIED_FEATURE_TOKENS = (
    "george",
    "label",
    "future",
    "ocr",
    "watchlist",
    "video",
    "post",
    "transcript",
    "entry",
    "exit",
    "ret",
    "mfe",
    "mae",
    "outcome",
    "oracle",
    "deployable",
    "bucket",
    "target",
)
CANDIDATE_FILTERS = ("kumo_ranked", "kumo_seen", "kumo_top_n")
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
    "target_trade_worthy",
    "target_runner",
    "target_fail_risk",
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
    "company_sector",
    "company_industry",
    "sector_category",
    "sector_etf_proxy",
    "source_tags",
    "best_entry_ret_20d_close_pct",
    "best_entry_mfe_20d_pct",
    "best_entry_mae_20d_pct",
    "best_deployable_total_equity_ret_40d_pct",
    "hold_40d_total_equity_ret_40d_pct",
    "target_trade_worthy",
    "target_runner",
    "target_fail_risk",
    "baseline_kumo_rank_score",
    "baseline_kumo_score",
    "baseline_rule_score",
    "model_trade_worthy_score",
    "model_runner_score",
    "model_combined_score",
}
PANEL_COLUMNS = {
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
}
BASE_FEATURES = [
    "kumo_rank_by_score",
    "kumo_rank_inverse",
    "kumo_rank_pct_in_day",
    "kumo_score",
    "score_pct_in_day",
    "kumo_gap_pct",
    "kumo_gap_abs",
    "gap_pct_in_day",
    "gap_abs_pct_in_day",
    "kumo_gap_positive",
    "kumo_gap_negative_abs",
    "kumo_vol_ratio_20d",
    "relvol_pct_in_day",
    "kumo_dollar_vol_log",
    "dollar_vol_pct_in_day",
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
    "has_company_sector",
    "has_company_industry",
    "has_sector_proxy",
    "is_kumo_top_n",
    "score_x_rank_pct",
    "score_x_gap_ok",
    "relvol_x_gap_ok",
]
SECTOR_FEATURE_PREFIX = "sector_cat_"
SECTOR_VALUES = (
    "communication_services",
    "consumer_cyclical",
    "consumer_defensive",
    "energy",
    "financials",
    "healthcare",
    "industrials",
    "materials",
    "real_estate",
    "technology",
    "utilities",
)


@dataclass(frozen=True)
class RankerConfig:
    universe: str
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
    model: base_ranker.LinearModel
    standardizer: base_ranker.Standardizer


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--universe", type=Path, default=DEFAULT_UNIVERSE)
    parser.add_argument("--panel", type=Path, default=DEFAULT_PANEL)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--candidate-filter", choices=CANDIDATE_FILTERS, default="kumo_ranked")
    parser.add_argument("--n-folds", type=int, default=6)
    parser.add_argument("--min-train-folds", type=int, default=1)
    parser.add_argument("--max-iter", type=int, default=180)
    parser.add_argument("--learning-rate", type=float, default=0.02)
    parser.add_argument("--l2", type=float, default=0.01)
    parser.add_argument("--negatives-per-positive", type=int, default=25)
    parser.add_argument("--limit", type=int, default=None, help="Optional row limit after filtering.")
    return parser.parse_args()


def _parse_day(value: Any) -> str:
    if pd.isna(value):
        return ""
    return str(value)[:10]


def _clean_symbol(value: Any) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip().upper()


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


def feature_hash(feature_names: Sequence[str]) -> str:
    payload = {"feature_version": FEATURE_VERSION, "feature_names": list(feature_names)}
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


def _normalize_booleans(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    for column in BOOL_COLUMNS:
        if column in out:
            out[column] = _bool_series(out[column])
    return out


def read_trade_universe(
    universe_path: Path,
    panel_path: Path,
    *,
    candidate_filter: str,
    limit: int | None,
) -> pd.DataFrame:
    if not universe_path.exists():
        raise FileNotFoundError(universe_path)
    if not panel_path.exists():
        raise FileNotFoundError(panel_path)
    frame = pd.read_csv(universe_path, usecols=lambda column: column in UNIVERSE_COLUMNS, low_memory=False)
    frame["scan_date"] = frame["scan_date"].map(_parse_day)
    frame["symbol"] = frame["symbol"].map(_clean_symbol)
    frame = _normalize_booleans(frame)
    frame["trade_bucket"] = frame["trade_bucket"].astype(str).str.strip().str.lower()
    frame = frame[frame["trade_bucket"].isin({"optimal", "bad", "watch"})].copy()

    panel = pd.read_csv(panel_path, usecols=lambda column: column in PANEL_COLUMNS, low_memory=False)
    panel["scan_date"] = panel["scan_date"].map(_parse_day)
    panel["symbol"] = panel["symbol"].map(_clean_symbol)
    panel = panel.drop_duplicates(["scan_date", "symbol"], keep="first")
    frame = frame.merge(panel, on=["scan_date", "symbol"], how="left", suffixes=("", "_panel"))
    for column in ("company_sector", "company_industry", "sector_category", "sector_etf_proxy"):
        panel_column = f"{column}_panel"
        if panel_column in frame:
            frame[column] = frame[column].where(frame[column].notna(), frame[panel_column])
            frame = frame.drop(columns=[panel_column])

    rank = _num(frame, "kumo_rank_by_score")
    filters = {
        "kumo_ranked": frame["kumo_signal_seen"] & rank.notna(),
        "kumo_seen": frame["kumo_signal_seen"],
        "kumo_top_n": frame["kumo_signal_seen"] & frame["kumo_top_n"],
    }
    frame = frame[filters[candidate_filter]].copy()
    if limit is not None:
        frame = frame.head(limit).copy()
    frame["opportunity_id"] = frame["scan_date"] + "|" + frame["symbol"]
    return prepare_labels(frame).sort_values(["scan_date", "symbol"]).reset_index(drop=True)


def prepare_labels(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    bucket = out["trade_bucket"].astype(str).str.strip().str.lower()
    out["target_optimal"] = bucket.eq("optimal")
    out["target_bad_risk"] = bucket.eq("bad")
    out["target_watch"] = bucket.eq("watch")
    out["target_relevance"] = np.select(
        [out["target_optimal"], out["target_watch"], out["target_bad_risk"]],
        [2.0, 0.5, 0.0],
        default=0.0,
    )
    return out


def _pct_rank_by_day(values: pd.Series, dates: pd.Series, *, ascending: bool) -> pd.Series:
    return values.groupby(dates.astype(str)).rank(pct=True, ascending=ascending)


def add_scan_time_features(frame: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    out = frame.copy()
    rank = _num(out, "kumo_rank_by_score")
    score = _num(out, "kumo_score")
    gap = _num(out, "kumo_gap_pct")
    relvol = _num(out, "kumo_vol_ratio_20d")
    dollar_vol_log = _safe_log1p(out.get("kumo_dollar_vol", pd.Series(np.nan, index=out.index)))
    volume_log = _safe_log1p(out.get("kumo_volume", pd.Series(np.nan, index=out.index)))
    close_log = _safe_log1p(out.get("kumo_close", pd.Series(np.nan, index=out.index)))
    dates = out["scan_date"].astype(str)

    out["kumo_rank_by_score"] = rank
    out["kumo_rank_inverse"] = -rank
    out["kumo_rank_pct_in_day"] = _pct_rank_by_day(rank, dates, ascending=True)
    out["kumo_score"] = score
    out["score_pct_in_day"] = _pct_rank_by_day(score, dates, ascending=False)
    out["kumo_gap_pct"] = gap
    out["kumo_gap_abs"] = gap.abs()
    out["gap_pct_in_day"] = _pct_rank_by_day(gap, dates, ascending=False)
    out["gap_abs_pct_in_day"] = _pct_rank_by_day(gap.abs(), dates, ascending=True)
    out["kumo_gap_positive"] = gap.clip(lower=0.0)
    out["kumo_gap_negative_abs"] = (-gap).clip(lower=0.0)
    out["kumo_vol_ratio_20d"] = relvol
    out["relvol_pct_in_day"] = _pct_rank_by_day(relvol, dates, ascending=False)
    out["kumo_dollar_vol_log"] = dollar_vol_log
    out["dollar_vol_pct_in_day"] = _pct_rank_by_day(dollar_vol_log, dates, ascending=False)
    out["kumo_volume_log"] = volume_log
    out["kumo_close_log"] = close_log
    out["rank_le_10"] = rank.le(10).astype(float)
    out["rank_le_20"] = rank.le(20).astype(float)
    out["rank_le_50"] = rank.le(50).astype(float)
    out["score_ge_7"] = score.ge(7).astype(float)
    out["score_ge_8"] = score.ge(8).astype(float)
    out["gap_between_minus2_5"] = gap.between(-2, 5).astype(float)
    out["gap_gt_8"] = gap.gt(8).astype(float)
    out["gap_lt_minus5"] = gap.lt(-5).astype(float)
    out["has_company_sector"] = out.get("company_sector", pd.Series("", index=out.index)).astype(str).str.len().gt(0).astype(float)
    out["has_company_industry"] = (
        out.get("company_industry", pd.Series("", index=out.index)).astype(str).str.len().gt(0).astype(float)
    )
    out["has_sector_proxy"] = out.get("sector_etf_proxy", pd.Series("", index=out.index)).astype(str).str.len().gt(0).astype(float)
    out["is_kumo_top_n"] = out["kumo_top_n"].astype(float)
    out["score_x_rank_pct"] = score.fillna(0.0) * (1.0 - out["kumo_rank_pct_in_day"].fillna(1.0))
    out["score_x_gap_ok"] = score.fillna(0.0) * out["gap_between_minus2_5"].fillna(0.0)
    out["relvol_x_gap_ok"] = relvol.fillna(0.0) * out["gap_between_minus2_5"].fillna(0.0)

    sector_slug = out.get("sector_category", pd.Series("", index=out.index)).map(_slug)
    sector_features: list[str] = []
    for sector in SECTOR_VALUES:
        feature = f"{SECTOR_FEATURE_PREFIX}{sector}"
        out[feature] = sector_slug.eq(sector).astype(float)
        sector_features.append(feature)

    features = list(BASE_FEATURES) + sector_features
    validate_feature_names(features)
    return out, features


def build_feature_matrix(frame: pd.DataFrame, feature_names: Sequence[str]) -> np.ndarray:
    columns = [_num(frame, feature).to_numpy(dtype=float) for feature in feature_names]
    if not columns:
        return np.empty((len(frame), 0), dtype=float)
    return np.column_stack(columns).astype(float)


def make_walk_forward_splits(dates: Sequence[str], *, n_folds: int, min_train_folds: int) -> list[dict[str, Any]]:
    return base_ranker.make_walk_forward_splits(dates, n_folds=n_folds, min_train_folds=min_train_folds)


def _fit_target_model(
    x_train: np.ndarray,
    y_train: np.ndarray,
    train_dates: Sequence[str],
    *,
    config: RankerConfig,
) -> base_ranker.LinearModel:
    return base_ranker.fit_pairwise_linear_ranker(
        x_train,
        y_train,
        train_dates,
        max_iter=config.max_iter,
        learning_rate=config.learning_rate,
        l2=config.l2,
        negatives_per_positive=config.negatives_per_positive,
    )


def fit_oof_rankers(
    panel: pd.DataFrame,
    feature_names: Sequence[str],
    *,
    config: RankerConfig,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    x_raw = build_feature_matrix(panel, feature_names)
    predictions = panel.copy()
    predictions["feature_version_492"] = FEATURE_VERSION
    predictions["feature_hash_492"] = feature_hash(feature_names)
    predictions["oof_available_492"] = False
    predictions["fold_492"] = np.nan
    predictions["model_492_optimal_score"] = np.nan
    predictions["model_492_bad_risk_score"] = np.nan

    y_by_target = {
        "optimal": predictions["target_optimal"].astype(float).to_numpy(dtype=float),
        "bad_risk": predictions["target_bad_risk"].astype(float).to_numpy(dtype=float),
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
        standardizer = base_ranker.fit_standardizer(x_raw[train_mask])
        x_train = base_ranker.apply_standardizer(x_raw[train_mask], standardizer)
        x_valid = base_ranker.apply_standardizer(x_raw[valid_mask], standardizer)
        train_dates = predictions.loc[train_mask, "scan_date"].astype(str).tolist()
        for target in TARGETS:
            y_train = y_by_target[target][train_mask]
            model = _fit_target_model(x_train, y_train, train_dates, config=config)
            scores = base_ranker.predict_score(model, x_valid)
            predictions.loc[valid_mask, f"model_492_{target}_score"] = scores
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
        predictions.loc[valid_mask, "oof_available_492"] = True
        predictions.loc[valid_mask, "fold_492"] = int(split["fold"])

    predictions["model_492_risk_avoidance_score"] = -predictions["model_492_bad_risk_score"]
    predictions["model_492_combined_score"] = (
        predictions["model_492_optimal_score"] - predictions["model_492_bad_risk_score"]
    )
    for weight in BLEND_RISK_WEIGHTS:
        suffix = str(int(weight * 100)).zfill(2)
        predictions[f"model_492_blend_risk{suffix}_score"] = (
            predictions["model_492_optimal_score"] - weight * predictions["model_492_bad_risk_score"]
        )
    predictions["baseline_492_kumo_rank_score"] = -_num(predictions, "kumo_rank_by_score")
    predictions["baseline_492_kumo_score"] = _num(predictions, "kumo_score")
    predictions["baseline_492_rule_score"] = (
        _num(predictions, "kumo_score").fillna(0.0)
        + 0.30 * predictions["gap_between_minus2_5"].astype(float)
        + 0.20 * predictions["rank_le_20"].astype(float)
        + 0.10 * predictions["relvol_pct_in_day"].fillna(0.0)
        - 0.50 * predictions["gap_gt_8"].astype(float)
        - 0.35 * predictions["gap_lt_minus5"].astype(float)
    )
    predictions["prior_467_combined_score"] = _num(predictions, "model_combined_score")
    predictions["prior_467_trade_worthy_score"] = _num(predictions, "model_trade_worthy_score")
    predictions["prior_467_runner_score"] = _num(predictions, "model_runner_score")

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
    if not rows:
        return pd.DataFrame(columns=["target", "feature", "coef_mean", "coef_abs_mean", "coef_std"])
    return pd.DataFrame(rows).sort_values(["target", "coef_abs_mean"], ascending=[True, False]).reset_index(drop=True)


def fit_final_artifact(panel: pd.DataFrame, feature_names: Sequence[str], *, config: RankerConfig) -> dict[str, Any]:
    x_raw = build_feature_matrix(panel, feature_names)
    standardizer = base_ranker.fit_standardizer(x_raw)
    x = base_ranker.apply_standardizer(x_raw, standardizer)
    dates = panel["scan_date"].astype(str).tolist()
    models: dict[str, Any] = {}
    for target, column in {"optimal": "target_optimal", "bad_risk": "target_bad_risk"}.items():
        y = panel[column].astype(float).to_numpy(dtype=float)
        model = _fit_target_model(x, y, dates, config=config)
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
        "combined_score": {"formula": "optimal_score - bad_risk_score"},
        "blend_scores": [
            {"name": f"model_492_blend_risk{str(int(weight * 100)).zfill(2)}_score", "risk_weight": weight}
            for weight in BLEND_RISK_WEIGHTS
        ],
        "training_rows": int(len(panel)),
        "training_dates": [str(panel["scan_date"].min()), str(panel["scan_date"].max())],
    }


def _dcg(values: Sequence[float]) -> float:
    return float(sum((2.0**value - 1.0) / np.log2(idx + 2.0) for idx, value in enumerate(values)))


def topk_metrics(predictions: pd.DataFrame, *, score_col: str, ks: Sequence[int] = KS) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    frame = predictions[predictions[score_col].notna()].copy()
    for k in ks:
        selected_total = 0
        optimal_total = 0
        optimal_hits = 0
        ndcgs: list[float] = []
        ret_values: list[float] = []
        mfe_values: list[float] = []
        mae_values: list[float] = []
        deployable_values: list[float] = []
        bad_values: list[float] = []
        watch_values: list[float] = []
        date_count = 0
        for _date, group in frame.groupby("scan_date", sort=True):
            optimal_count = int(group["target_optimal"].astype(bool).sum())
            if optimal_count == 0:
                continue
            ranked = group.sort_values(score_col, ascending=False).head(k)
            selected = len(ranked)
            optimal = int(ranked["target_optimal"].astype(bool).sum())
            ideal_values = sorted(group["target_relevance"].astype(float).tolist(), reverse=True)[:selected]
            actual_values = ranked["target_relevance"].astype(float).tolist()
            ideal_dcg = _dcg(ideal_values)
            ndcgs.append(_dcg(actual_values) / ideal_dcg if ideal_dcg else 0.0)
            selected_total += selected
            optimal_total += optimal_count
            optimal_hits += optimal
            date_count += 1
            ret_values.extend(_num(ranked, "best_entry_ret_20d_close_pct").dropna().tolist())
            mfe_values.extend(_num(ranked, "best_entry_mfe_20d_pct").dropna().tolist())
            mae_values.extend(_num(ranked, "best_entry_mae_20d_pct").dropna().tolist())
            deployable_values.extend(_num(ranked, "best_deployable_total_equity_ret_40d_pct").dropna().tolist())
            bad_values.extend(ranked["target_bad_risk"].astype(float).tolist())
            watch_values.extend(ranked["target_watch"].astype(float).tolist())
        rows.append(
            {
                "score": score_col,
                "k": int(k),
                "dates": int(date_count),
                "selected_rows": int(selected_total),
                "optimal_rows": int(optimal_total),
                "optimal_hits": int(optimal_hits),
                "optimal_recall_pct": round(100.0 * optimal_hits / optimal_total, 3) if optimal_total else 0.0,
                "optimal_precision_pct": round(100.0 * optimal_hits / selected_total, 3) if selected_total else 0.0,
                "bad_trade_pct_topk": round(100.0 * float(np.mean(bad_values)), 3) if bad_values else 0.0,
                "watch_pct_topk": round(100.0 * float(np.mean(watch_values)), 3) if watch_values else 0.0,
                "ndcg_mean": round(float(np.mean(ndcgs)), 4) if ndcgs else 0.0,
                "avg_best_entry_ret20_topk_pct": round(float(np.mean(ret_values)), 4) if ret_values else None,
                "avg_best_entry_mfe20_topk_pct": round(float(np.mean(mfe_values)), 4) if mfe_values else None,
                "avg_best_entry_mae20_topk_pct": round(float(np.mean(mae_values)), 4) if mae_values else None,
                "avg_deployable_ret40_topk_pct": round(float(np.mean(deployable_values)), 4)
                if deployable_values
                else None,
            }
        )
    return pd.DataFrame(rows)


def build_metric_summary(predictions: pd.DataFrame) -> pd.DataFrame:
    score_cols = [
        "baseline_492_kumo_rank_score",
        "baseline_492_kumo_score",
        "baseline_492_rule_score",
        "prior_467_combined_score",
        "prior_467_trade_worthy_score",
        "prior_467_runner_score",
        "model_492_optimal_score",
        "model_492_blend_risk25_score",
        "model_492_blend_risk50_score",
        "model_492_blend_risk75_score",
        "model_492_risk_avoidance_score",
        "model_492_combined_score",
    ]
    fair_frame = predictions[predictions["oof_available_492"]].copy()
    frames = [topk_metrics(fair_frame, score_col=score) for score in score_cols]
    return pd.concat(frames, ignore_index=True)


def monthly_stability(predictions: pd.DataFrame, *, k: int = 10) -> pd.DataFrame:
    frame = predictions[predictions["oof_available_492"]].copy()
    frame["month"] = frame["scan_date"].astype(str).str.slice(0, 7)
    rows: list[dict[str, Any]] = []
    for score in ("baseline_492_kumo_rank_score", "baseline_492_rule_score", "prior_467_combined_score", "model_492_combined_score"):
        for month, month_frame in frame[frame[score].notna()].groupby("month", sort=True):
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
                    "optimal_precision_pct": round(100.0 * float(top["target_optimal"].mean()), 3),
                    "bad_trade_pct": round(100.0 * float(top["target_bad_risk"].mean()), 3),
                    "watch_pct": round(100.0 * float(top["target_watch"].mean()), 3),
                    "avg_best_entry_ret20_pct": round(float(_num(top, "best_entry_ret_20d_close_pct").mean()), 4),
                    "avg_deployable_ret40_pct": round(float(_num(top, "best_deployable_total_equity_ret_40d_pct").mean()), 4),
                }
            )
    return pd.DataFrame(rows)


def daily_examples(predictions: pd.DataFrame, *, k: int = 10, limit: int = 120) -> pd.DataFrame:
    frame = predictions[predictions["oof_available_492"]].copy()
    rows: list[dict[str, Any]] = []
    score_specs = (
        ("optimal_model", "model_492_optimal_score", True, False),
        ("risk_blend", "model_492_combined_score", False, True),
    )
    for scan_date, group in frame.groupby("scan_date", sort=True):
        base = group[group["baseline_492_kumo_rank_score"].notna()].copy()
        if base.empty:
            continue
        base_rank = base["baseline_492_kumo_rank_score"].rank(method="first", ascending=False).astype(int)
        for score_label, score_col, include_promoted, include_demoted in score_specs:
            model = group[group[score_col].notna()].copy()
            if model.empty:
                continue
            model_rank = model[score_col].rank(method="first", ascending=False).astype(int)
            joined = group.copy()
            joined["model_score_name"] = score_col
            joined["model_score_value"] = joined[score_col]
            joined["baseline_rank"] = base_rank.reindex(joined.index)
            joined["model_rank"] = model_rank.reindex(joined.index)
            joined["rank_delta"] = joined["baseline_rank"] - joined["model_rank"]
            promoted = pd.DataFrame()
            demoted = pd.DataFrame()
            if include_promoted:
                promoted = joined[
                    joined["target_optimal"] & joined["baseline_rank"].gt(k) & joined["model_rank"].le(k)
                ].copy()
                promoted["example_type"] = f"{score_label}_promoted_optimal"
            if include_demoted:
                demoted = joined[
                    joined["target_bad_risk"] & joined["baseline_rank"].le(k) & joined["model_rank"].gt(k)
                ].copy()
                demoted["example_type"] = f"{score_label}_demoted_bad"
            for part in (promoted, demoted):
                if not part.empty:
                    rows.extend(part.to_dict("records"))
    if not rows:
        return pd.DataFrame()
    examples = pd.DataFrame(rows)
    examples["rank_delta_abs"] = examples["rank_delta"].abs()
    columns = [
        "example_type",
        "scan_date",
        "symbol",
        "trade_bucket",
        "model_score_name",
        "model_score_value",
        "kumo_rank_by_score",
        "kumo_score",
        "baseline_rank",
        "model_rank",
        "rank_delta",
        "model_492_combined_score",
        "model_492_optimal_score",
        "model_492_bad_risk_score",
        "prior_467_combined_score",
        "best_entry_ret_20d_close_pct",
        "best_entry_mfe_20d_pct",
        "best_entry_mae_20d_pct",
        "best_deployable_total_equity_ret_40d_pct",
        "reason_codes",
        "company_sector",
        "company_industry",
        "sector_category",
        "sector_etf_proxy",
    ]
    selected: list[pd.DataFrame] = []
    example_types = sorted(examples["example_type"].dropna().unique().tolist())
    per_type_limit = max(1, int(np.ceil(limit / max(1, len(example_types)))))
    for example_type in example_types:
        part = examples[examples["example_type"].eq(example_type)]
        selected.append(part.sort_values("rank_delta_abs", ascending=False).head(per_type_limit))
    return (
        pd.concat(selected, ignore_index=True)
        .sort_values(["example_type", "rank_delta_abs"], ascending=[True, False])
        .head(limit)
        .loc[:, columns]
        .reset_index(drop=True)
    )


def prediction_output(predictions: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "scan_date",
        "symbol",
        "opportunity_id",
        "trade_bucket",
        "reason_codes",
        "source_bucket",
        "feature_version_492",
        "feature_hash_492",
        "fold_492",
        "oof_available_492",
        "kumo_signal_seen",
        "kumo_top_n",
        "kumo_scanner",
        "george_signal_seen",
        "george_scanner_positive",
        "george_watchlist",
        "source_tags",
        "kumo_rank_by_score",
        "kumo_score",
        "kumo_gap_pct",
        "kumo_vol_ratio_20d",
        "target_optimal",
        "target_bad_risk",
        "target_watch",
        "best_entry_ret_20d_close_pct",
        "best_entry_mfe_20d_pct",
        "best_entry_mae_20d_pct",
        "best_deployable_total_equity_ret_40d_pct",
        "baseline_492_kumo_rank_score",
        "baseline_492_kumo_score",
        "baseline_492_rule_score",
        "prior_467_combined_score",
        "prior_467_trade_worthy_score",
        "prior_467_runner_score",
        "model_492_optimal_score",
        "model_492_bad_risk_score",
        "model_492_risk_avoidance_score",
        "model_492_blend_risk25_score",
        "model_492_blend_risk50_score",
        "model_492_blend_risk75_score",
        "model_492_combined_score",
    ]
    present = [column for column in columns if column in predictions]
    return predictions.loc[:, present].copy()


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


def _metric_delta(metrics: pd.DataFrame, *, model_score: str, baseline_score: str, k: int) -> dict[str, Any]:
    model = metrics[(metrics["score"] == model_score) & (metrics["k"] == k)]
    base = metrics[(metrics["score"] == baseline_score) & (metrics["k"] == k)]
    if model.empty or base.empty:
        return {}
    m = model.iloc[0]
    b = base.iloc[0]
    return {
        "k": k,
        "optimal_precision_delta_pct": round(float(m["optimal_precision_pct"] - b["optimal_precision_pct"]), 3),
        "bad_trade_delta_pct": round(float(m["bad_trade_pct_topk"] - b["bad_trade_pct_topk"]), 3),
        "avg_ret20_delta_pct": round(
            float((m["avg_best_entry_ret20_topk_pct"] or 0.0) - (b["avg_best_entry_ret20_topk_pct"] or 0.0)),
            4,
        ),
        "ndcg_delta": round(float(m["ndcg_mean"] - b["ndcg_mean"]), 4),
    }


def _best_metric_rows(metrics: pd.DataFrame, *, k: int) -> tuple[dict[str, Any], dict[str, Any]]:
    subset = metrics[metrics["k"] == k].copy()
    model_subset = subset[subset["score"].astype(str).str.startswith("model_492_")]
    if model_subset.empty:
        return {}, {}
    best_precision = model_subset.sort_values(
        ["optimal_precision_pct", "bad_trade_pct_topk"],
        ascending=[False, True],
    ).iloc[0]
    lowest_bad = model_subset.sort_values(
        ["bad_trade_pct_topk", "optimal_precision_pct"],
        ascending=[True, False],
    ).iloc[0]
    keys = [
        "score",
        "optimal_precision_pct",
        "bad_trade_pct_topk",
        "optimal_recall_pct",
        "avg_best_entry_ret20_topk_pct",
        "avg_deployable_ret40_topk_pct",
    ]
    return best_precision.loc[keys].to_dict(), lowest_bad.loc[keys].to_dict()


def write_report(
    *,
    output_dir: Path,
    predictions: pd.DataFrame,
    metrics: pd.DataFrame,
    monthly: pd.DataFrame,
    examples: pd.DataFrame,
    fold_summary: pd.DataFrame,
    coef_summary: pd.DataFrame,
    config: RankerConfig,
) -> None:
    top10 = metrics[metrics["k"] == 10].sort_values(
        ["optimal_precision_pct", "bad_trade_pct_topk", "optimal_recall_pct"],
        ascending=[False, True, False],
    )
    top50 = metrics[metrics["k"] == 50].sort_values(
        ["optimal_precision_pct", "bad_trade_pct_topk", "optimal_recall_pct"],
        ascending=[False, True, False],
    )
    delta10 = _metric_delta(
        metrics,
        model_score="model_492_combined_score",
        baseline_score="baseline_492_kumo_rank_score",
        k=10,
    )
    delta50 = _metric_delta(
        metrics,
        model_score="model_492_combined_score",
        baseline_score="baseline_492_kumo_rank_score",
        k=50,
    )
    optimal_vs_score10 = _metric_delta(
        metrics,
        model_score="model_492_optimal_score",
        baseline_score="baseline_492_kumo_score",
        k=10,
    )
    risk25_vs_score10 = _metric_delta(
        metrics,
        model_score="model_492_blend_risk25_score",
        baseline_score="baseline_492_kumo_score",
        k=10,
    )
    best_precision10, lowest_bad10 = _best_metric_rows(metrics, k=10)
    recommendation = "iterate"
    if delta10 and delta10["optimal_precision_delta_pct"] >= 5.0 and delta10["bad_trade_delta_pct"] <= 0.0:
        recommendation = "promote_candidate"
    if delta10 and delta10["optimal_precision_delta_pct"] <= 0.0 and delta10["bad_trade_delta_pct"] >= 0.0:
        recommendation = "discard_or_rework"

    lines = [
        "# Scan-Time Scanner Ranker #492",
        "",
        "This trains a first-pass scan-time ranker on the #482 optimal/bad trade buckets.",
        "Validation is expanding-window by scan date. The model does not use George/source, future path,",
        "entry, exit, return, MFE, MAE, or prior-model columns as features.",
        "",
        "## Inputs",
        "",
        f"- Trade universe: `{config.universe}`",
        f"- Scan-time panel metadata: `{config.panel}`",
        f"- Candidate filter: `{config.candidate_filter}`",
        "",
        "## Coverage",
        "",
        f"- Rows: `{len(predictions)}`",
        f"- Dates: `{predictions['scan_date'].nunique()}`",
        f"- OOF rows: `{int(predictions['oof_available_492'].sum())}`",
        f"- Optimal rows: `{int(predictions['target_optimal'].sum())}`",
        f"- Bad rows: `{int(predictions['target_bad_risk'].sum())}`",
        f"- Watch rows: `{int(predictions['target_watch'].sum())}`",
        f"- Feature version: `{FEATURE_VERSION}`",
        f"- Feature hash: `{predictions['feature_hash_492'].iloc[0] if len(predictions) else ''}`",
        "",
        "## Decision",
        "",
        f"- Recommendation: `{recommendation}`",
        f"- Best top-10 #492 precision point: `{best_precision10}`",
        f"- Lowest-bad top-10 #492 point: `{lowest_bad10}`",
        f"- Top-10 optimal model vs current Kumo-score delta: `{optimal_vs_score10}`",
        f"- Top-10 25% risk blend vs current Kumo-score delta: `{risk25_vs_score10}`",
        f"- Top-10 full risk blend vs current Kumo-rank delta: `{delta10}`",
        f"- Top-50 full risk blend vs current Kumo-rank delta: `{delta50}`",
        "",
        "Interpretation: scan-time features reduce bad-trade concentration more reliably than they",
        "increase top-10 optimal precision. This is useful for a risk filter, but not enough on its own",
        "to explain George-style top-pick selection.",
        "",
        "## Top-10 Ranking",
        "",
        _markdown_table(
            top10,
            [
                "score",
                "selected_rows",
                "optimal_hits",
                "optimal_recall_pct",
                "optimal_precision_pct",
                "bad_trade_pct_topk",
                "watch_pct_topk",
                "ndcg_mean",
                "avg_best_entry_ret20_topk_pct",
                "avg_deployable_ret40_topk_pct",
            ],
        ),
        "",
        "## Top-50 Ranking",
        "",
        _markdown_table(
            top50,
            [
                "score",
                "selected_rows",
                "optimal_hits",
                "optimal_recall_pct",
                "optimal_precision_pct",
                "bad_trade_pct_topk",
                "watch_pct_topk",
                "ndcg_mean",
                "avg_best_entry_ret20_topk_pct",
                "avg_deployable_ret40_topk_pct",
            ],
        ),
        "",
        "## Promotion/Demotion Examples",
        "",
        _markdown_table(
            examples,
            [
                "example_type",
                "scan_date",
                "symbol",
                "trade_bucket",
                "model_score_name",
                "kumo_rank_by_score",
                "baseline_rank",
                "model_rank",
                "rank_delta",
                "best_entry_ret_20d_close_pct",
                "best_deployable_total_equity_ret_40d_pct",
            ],
            limit=30,
        ),
        "",
        "## Monthly Stability",
        "",
        _markdown_table(
            monthly,
            [
                "month",
                "score",
                "selected_rows",
                "optimal_precision_pct",
                "bad_trade_pct",
                "watch_pct",
                "avg_best_entry_ret20_pct",
            ],
            limit=80,
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
            limit=40,
        ),
        "",
        "## Notes",
        "",
        "- `prior_467_*` scores are comparison baselines only; they are not model features.",
        "- `daily_rank_examples.csv` shows rows the #492 model moves into or out of top 10 vs Kumo rank.",
        "- This is scan-time only. Intraday entry/exit policy remains #491/#490.",
        "",
    ]
    (output_dir / "scan_time_ranker_report.md").write_text("\n".join(lines), encoding="utf-8")


def write_outputs(
    *,
    predictions: pd.DataFrame,
    fold_summary: pd.DataFrame,
    metrics: pd.DataFrame,
    monthly: pd.DataFrame,
    examples: pd.DataFrame,
    coef_summary: pd.DataFrame,
    model_artifact: dict[str, Any],
    config: RankerConfig,
    output_dir: Path,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "README.md").write_text(
        "# scan_time_scanner_ranker_492/\n\n"
        "Contains scan-time scanner ranking research artifacts for issue #492.\n"
        "Keep compact OOF predictions, top-k metrics, monthly stability diagnostics, examples, and model JSON here.\n"
        "Do not store raw market-data extracts or bulky run folders here.\n",
        encoding="utf-8",
    )
    oof_path = output_dir / "oof_predictions.csv.gz"
    _write_gzip_csv(prediction_output(predictions), oof_path)
    fold_summary.to_csv(output_dir / "fold_summary.csv", index=False)
    metrics.to_csv(output_dir / "topk_metrics.csv", index=False)
    monthly.to_csv(output_dir / "monthly_stability.csv", index=False)
    examples.to_csv(output_dir / "daily_rank_examples.csv", index=False)
    coef_summary.to_csv(output_dir / "feature_importance.csv", index=False)
    (output_dir / "model_artifact.json").write_text(json.dumps(model_artifact, indent=2) + "\n", encoding="utf-8")
    write_report(
        output_dir=output_dir,
        predictions=predictions,
        metrics=metrics,
        monthly=monthly,
        examples=examples,
        fold_summary=fold_summary,
        coef_summary=coef_summary,
        config=config,
    )
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "issue": "https://github.com/FALK-BRAUER/kumo-qc/issues/492",
        "config": asdict(config),
        "feature_version": FEATURE_VERSION,
        "feature_hash": model_artifact["feature_hash"],
        "outputs": {
            "oof_predictions.csv.gz": {"rows": int(len(predictions))},
            "fold_summary.csv": {"rows": int(len(fold_summary))},
            "topk_metrics.csv": {"rows": int(len(metrics))},
            "monthly_stability.csv": {"rows": int(len(monthly))},
            "daily_rank_examples.csv": {"rows": int(len(examples))},
            "feature_importance.csv": {"rows": int(len(coef_summary))},
            "model_artifact.json": {"schema_version": MODEL_SCHEMA_VERSION},
            "scan_time_ranker_report.md": {},
        },
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return {
        "oof_predictions": oof_path,
        "fold_summary": output_dir / "fold_summary.csv",
        "topk_metrics": output_dir / "topk_metrics.csv",
        "monthly_stability": output_dir / "monthly_stability.csv",
        "daily_rank_examples": output_dir / "daily_rank_examples.csv",
        "feature_importance": output_dir / "feature_importance.csv",
        "model_artifact": output_dir / "model_artifact.json",
        "report": output_dir / "scan_time_ranker_report.md",
        "manifest": output_dir / "manifest.json",
    }


def run(
    *,
    universe_path: Path = DEFAULT_UNIVERSE,
    panel_path: Path = DEFAULT_PANEL,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    candidate_filter: str = "kumo_ranked",
    n_folds: int = 6,
    min_train_folds: int = 1,
    max_iter: int = 180,
    learning_rate: float = 0.02,
    l2: float = 0.01,
    negatives_per_positive: int = 25,
    limit: int | None = None,
) -> dict[str, Path]:
    config = RankerConfig(
        universe=str(universe_path),
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
    panel = read_trade_universe(universe_path, panel_path, candidate_filter=candidate_filter, limit=limit)
    panel, feature_names = add_scan_time_features(panel)
    predictions, fold_summary, coef_summary, model_artifact = fit_oof_rankers(panel, feature_names, config=config)
    metrics = build_metric_summary(predictions)
    monthly = monthly_stability(predictions)
    examples = daily_examples(predictions)
    return write_outputs(
        predictions=predictions,
        fold_summary=fold_summary,
        metrics=metrics,
        monthly=monthly,
        examples=examples,
        coef_summary=coef_summary,
        model_artifact=model_artifact,
        config=config,
        output_dir=output_dir,
    )


def main() -> None:
    args = _args()
    outputs = run(
        universe_path=args.universe,
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
