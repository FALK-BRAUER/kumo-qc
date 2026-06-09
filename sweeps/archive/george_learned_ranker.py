"""Offline QC-safe learned ranker for George/BCT scanner-alignment research.

This module trains/evaluates a simple dependency-free logistic ranker with date-grouped
out-of-fold validation. It is research-only: runtime strategy code must not import it, and live
code must not read George labels, OCR rows, transcripts, or generated lab scores.
"""
from __future__ import annotations

import argparse
import csv
import warnings
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from sweeps.archive import first_hour_confirmation as first_hour
from sweeps.archive import george_sector_context_audit as sector_context
from sweeps.archive import george_topk_audit as topk

DEFAULT_PROMOTION_INVENTORY = Path("research/scanner-alignment/feature_parity_columns.csv")


@dataclass(frozen=True, slots=True)
class DenominatorRankSpec:
    """A raw daily-panel column to turn into rank and percentile features."""

    source_col: str
    output_prefix: str


EXTRA_USECOLS: tuple[str, ...] = (
    "day_dollar_vol",
    "adv20_incl_today",
    "d_tenkan_gt_kijun",
    "d_cloud_green",
    "d_price_above_ma200",
    "d_chikou_ok",
    "d_chikou_open_space",
    "d_tk_spread_pct",
    "d_distance_to_prior_high20_pct",
    "d_distance_to_prior_high50_pct",
    "d_distance_to_prior_high252_pct",
    "d_recent_resistance_rejection_count20",
    "d_volume_above_ma50",
    "d_volume_spike_150",
    "d_price_up_volume_down",
    "d_price_up_volume_below50",
    "d_return_5d_pct",
    "d_return_10d_pct",
    "d_return_20d_pct",
    "d_rel_volume50",
    "d_body_pct_range",
    "d_upper_wick_pct_range",
    "d_lower_wick_pct_range",
    "d_doji_or_spinning_top",
    "d_overextended_tenkan_3",
    "d_overextended_tenkan_5",
    "d_overextended_tenkan_10",
    "d_rapid_run_10d_15",
    "d_rapid_run_20d_30",
    "d_extension_reversal_warning",
    "daily_breakout_quality_score",
    "d_adx",
    "d_plus_di",
    "d_minus_di",
    "d_adx_rising_3",
    "bct_c1_weekly_price_above_cloud",
    "bct_c2_weekly_tenkan_gt_kijun",
    "bct_c3_weekly_chikou_ok",
    "bct_c4_weekly_cloud_green",
    "bct_c5_daily_price_above_cloud",
    "bct_c6_daily_price_above_tenkan",
    "bct_c7_adx_confirmed",
    "bct_c8_daily_price_above_ma200",
    "w_cloud_green",
    "w_tenkan_gt_kijun",
    "w_chikou_ok",
    "w_cloud_distance_pct",
    "w_tenkan_extension_pct",
)

DENOMINATOR_RANK_SPECS: tuple[DenominatorRankSpec, ...] = (
    DenominatorRankSpec("gap_pct", "gap_pct"),
    DenominatorRankSpec("day_return_pct", "day_return_pct"),
    DenominatorRankSpec("rel_volume20", "rel_volume20"),
    DenominatorRankSpec("d_rel_volume50", "rel_volume50"),
    DenominatorRankSpec("bct_score", "bct_score"),
    DenominatorRankSpec("daily_structure_score", "daily_structure_score"),
    DenominatorRankSpec("d_cloud_distance_pct", "daily_cloud_distance_pct"),
    DenominatorRankSpec("daily_breakout_quality_score", "daily_breakout_quality_score"),
    DenominatorRankSpec("day_dollar_vol", "day_dollar_vol"),
    DenominatorRankSpec("adv20_incl_today", "adv20"),
)

DENOMINATOR_RANK_FEATURES: tuple[str, ...] = tuple(
    feature
    for spec in DENOMINATOR_RANK_SPECS
    for feature in (
        f"{spec.output_prefix}_rank_in_panel",
        f"{spec.output_prefix}_pctile_in_panel",
    )
)

SECTOR_BREADTH_NUMERIC_FEATURES: tuple[str, ...] = (
    "sector_denominator_count",
    "sector_bct6_count",
    "sector_bct7_count",
    "sector_positive_return_count",
    "sector_median_day_return_pct",
    "sector_median_rel_volume20",
    "sector_bct6_pct",
    "sector_bct7_pct",
    "sector_positive_return_pct",
    "industry_denominator_count",
    "industry_bct6_count",
    "industry_bct7_count",
    "industry_positive_return_count",
    "industry_median_day_return_pct",
    "industry_median_rel_volume20",
    "industry_bct6_pct",
    "industry_bct7_pct",
    "industry_positive_return_pct",
)

LEARNED_USECOLS: tuple[str, ...] = tuple(
    dict.fromkeys(
        (
            *topk.DENOMINATOR_USECOLS,
            *EXTRA_USECOLS,
            *sector_context.PROFILE_USECOLS,
            *SECTOR_BREADTH_NUMERIC_FEATURES,
        )
    )
)

NUMERIC_FEATURES: tuple[str, ...] = (
    "adv20_rank_price10",
    "day_dv_rank_price10",
    "bct_score",
    "gap_pct",
    "day_return_pct",
    "intraday_return_pct",
    "range_pct",
    "daily_structure_score",
    "d_tenkan_extension_pct",
    "d_kijun_extension_pct",
    "d_cloud_distance_pct",
    "d_tk_spread_pct",
    "d_distance_to_prior_high20_pct",
    "d_distance_to_prior_high50_pct",
    "d_distance_to_prior_high252_pct",
    "d_recent_resistance_rejection_count20",
    "rel_volume20",
    "d_return_5d_pct",
    "d_return_10d_pct",
    "d_return_20d_pct",
    "d_body_pct_range",
    "d_upper_wick_pct_range",
    "d_lower_wick_pct_range",
    "daily_breakout_quality_score",
    "d_adx",
    "d_plus_di",
    "d_minus_di",
    "w_cloud_distance_pct",
    "w_tenkan_extension_pct",
)
BOOLEAN_FEATURES: tuple[str, ...] = (
    "d_price_above_cloud",
    "d_price_above_tenkan",
    "d_price_above_kijun",
    "d_tenkan_gt_kijun",
    "d_cloud_green",
    "d_price_above_ma200",
    "d_chikou_ok",
    "d_chikou_open_space",
    "d_near_prior20_high_within3",
    "d_near_prior50_high_within5",
    "d_near_prior252_high_within5",
    "d_breakout20_volume_confirmed",
    "d_breakout50_volume_confirmed",
    "d_breakout252_volume_confirmed",
    "d_no_chase_risk",
    "d_bearish_reversal_candle",
    "d_shooting_star_like",
    "d_volume_above_ma50",
    "d_volume_spike_150",
    "d_price_up_volume_down",
    "d_price_up_volume_below50",
    "d_doji_or_spinning_top",
    "d_overextended_tenkan_3",
    "d_overextended_tenkan_5",
    "d_overextended_tenkan_10",
    "d_rapid_run_10d_15",
    "d_rapid_run_20d_30",
    "d_extension_reversal_warning",
    "d_adx_rising_3",
    "bct_c1_weekly_price_above_cloud",
    "bct_c2_weekly_tenkan_gt_kijun",
    "bct_c3_weekly_chikou_ok",
    "bct_c4_weekly_cloud_green",
    "bct_c5_daily_price_above_cloud",
    "bct_c6_daily_price_above_tenkan",
    "bct_c7_adx_confirmed",
    "bct_c8_daily_price_above_ma200",
    "w_price_above_cloud",
    "w_cloud_green",
    "w_tenkan_gt_kijun",
    "w_chikou_ok",
)
SECTOR_NUMERIC_FEATURES: tuple[str, ...] = (
    "stock_chart_score",
    "base_stock_score",
    "base_stock_rank",
    "sector_proxy_score",
    "sector_rank",
    "sector_weekly_good_pct",
    "sector_daily_good_pct",
    "sector_bct7_count_proxy",
    "sector_rows_proxy",
    "industry_proxy_score",
    "industry_hierarchy_score",
    "industry_rank_global",
    "industry_rank_hierarchy",
    "industry_rank_in_sector",
    "industry_weekly_good_pct",
    "industry_daily_good_pct",
    "industry_bct7_count_proxy",
    "industry_rows_proxy",
    "stock_rank_in_industry_base",
    "stock_rank_in_sector_base",
    "sector_context_score",
    "hierarchy_stage_score",
)
SECTOR_BOOLEAN_FEATURES: tuple[str, ...] = (
    "has_sector_profile",
    "has_industry_profile",
    "weekly_good",
    "weekly_strong",
    "weekly_recovering",
    "daily_good",
    "daily_strong",
    "daily_support_hold",
    "daily_breakout",
    "volume_confirmed",
    "positive_day",
    "bad_reversal",
    "no_chase_pass",
    "sector_pass_top7",
    "industry_pass_hierarchy",
    "stock_pass_in_industry",
    "trigger_pass_proxy",
    "hierarchy_all_stage_pass",
    "strong_industry_exception",
)
FIRST_HOUR_NUMERIC_FEATURES: tuple[str, ...] = (
    "fh_bars",
    "fh_return_pct",
    "fh_range_pct",
    "fh_drawdown_pct",
    "fh_volume_adv_ratio",
)
FIRST_HOUR_BOOLEAN_FEATURES: tuple[str, ...] = (
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


@dataclass(frozen=True, slots=True)
class LearnedRankerConfig:
    """Configuration for the offline learned ranker."""

    top_n: int = topk.DEFAULT_TOP_N
    min_score: int = topk.DEFAULT_MIN_SCORE
    n_folds: int = 5
    model_type: str = "logistic"
    max_iter: int = 500
    learning_rate: float = 0.05
    l2: float = 0.01
    pairwise_negatives_per_positive: int = 80
    use_sector_context: bool = False
    use_first_hour: bool = False
    use_denominator_ranks: bool = False
    use_sector_breadth: bool = False
    use_qc_cloud_safe_features: bool = False
    promotion_inventory_path: Path = DEFAULT_PROMOTION_INVENTORY
    first_hour_minute_dir: Path | None = None
    ks: tuple[int, ...] = topk.DEFAULT_KS


@dataclass(frozen=True, slots=True)
class Standardizer:
    mean: np.ndarray
    scale: np.ndarray


@dataclass(frozen=True, slots=True)
class LogisticModel:
    coef: np.ndarray
    intercept: float


@dataclass(frozen=True, slots=True)
class LearnedRankerResult:
    base_summary: pd.DataFrame
    gate_summary: pd.DataFrame
    rank_summary: pd.DataFrame
    fold_summary: pd.DataFrame
    coefficient_summary: pd.DataFrame
    failure_examples: pd.DataFrame


def load_denominator(path: Path) -> pd.DataFrame:
    """Load denominator columns used by the learned ranker."""
    header = list(pd.read_csv(path, nrows=0).columns)
    missing = [col for col in topk.DENOMINATOR_USECOLS if col not in header]
    if missing:
        raise ValueError(f"denominator missing required columns: {missing}")
    usecols = [col for col in LEARNED_USECOLS if col in header]
    return pd.read_csv(path, usecols=usecols, low_memory=False)


def add_denominator_rank_features(panel: pd.DataFrame) -> pd.DataFrame:
    """Add per-date live-panel ranks and percentiles from raw denominator columns."""
    out = panel.copy()
    if "date" not in out:
        for feature in DENOMINATOR_RANK_FEATURES:
            out[feature] = np.nan
        return out

    group = out["date"].astype(str)
    for spec in DENOMINATOR_RANK_SPECS:
        rank_col = f"{spec.output_prefix}_rank_in_panel"
        pctile_col = f"{spec.output_prefix}_pctile_in_panel"
        values = topk._num_col(out, spec.source_col)
        out[rank_col] = values.groupby(group).rank(method="average", ascending=False)
        out[pctile_col] = values.groupby(group).rank(pct=True, ascending=True)
    return out


def load_qc_cloud_safe_feature_names(path: Path = DEFAULT_PROMOTION_INVENTORY) -> set[str]:
    """Load feature names explicitly allowed by the scanner runtime-promotion gate."""
    if not path.exists():
        raise FileNotFoundError(f"promotion inventory not found: {path}")
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        required = {"feature", "deployability_class", "safe_for_qc_handoff"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"promotion inventory missing required columns: {sorted(missing)}")
        names = {
            row["feature"].strip()
            for row in reader
            if row.get("safe_for_qc_handoff", "").strip() == "True"
            and row.get("deployability_class", "").strip() == "qc_cloud_deployable"
            and row.get("feature", "").strip()
        }
    if not names:
        raise ValueError(f"promotion inventory has no QC-cloud-safe features: {path}")
    return names


def filter_feature_matrix(
    x: np.ndarray,
    feature_names: list[str],
    *,
    allowed_features: set[str] | None,
) -> tuple[np.ndarray, list[str]]:
    """Restrict a feature matrix to an explicit feature-name allowlist."""
    if allowed_features is None:
        return x, feature_names
    keep = [idx for idx, feature in enumerate(feature_names) if feature in allowed_features]
    if not keep:
        raise ValueError("QC-cloud-safe feature filter removed every feature")
    return x[:, keep], [feature_names[idx] for idx in keep]


def make_date_folds(dates: Sequence[str], *, n_folds: int) -> list[set[str]]:
    """Create chronological date-group validation folds."""
    unique_dates = sorted(set(dates))
    if not unique_dates:
        return []
    fold_count = max(1, min(n_folds, len(unique_dates)))
    arrays = np.array_split(np.array(unique_dates, dtype=object), fold_count)
    return [set(str(date) for date in arr.tolist()) for arr in arrays if len(arr) > 0]


def build_feature_matrix(
    panel: pd.DataFrame,
    *,
    include_sector_context: bool = False,
    include_first_hour: bool = False,
    include_denominator_ranks: bool = False,
    include_sector_breadth: bool = False,
    allowed_features: set[str] | None = None,
) -> tuple[np.ndarray, list[str]]:
    """Build a numeric feature matrix from QC-safe denominator columns."""
    columns: list[np.ndarray] = []
    names: list[str] = []
    numeric_features = (
        NUMERIC_FEATURES
        + (SECTOR_NUMERIC_FEATURES if include_sector_context else ())
        + (FIRST_HOUR_NUMERIC_FEATURES if include_first_hour else ())
        + (DENOMINATOR_RANK_FEATURES if include_denominator_ranks else ())
        + (SECTOR_BREADTH_NUMERIC_FEATURES if include_sector_breadth else ())
    )
    boolean_features = (
        BOOLEAN_FEATURES
        + (SECTOR_BOOLEAN_FEATURES if include_sector_context else ())
        + (FIRST_HOUR_BOOLEAN_FEATURES if include_first_hour else ())
    )
    for col in numeric_features:
        values = topk._num_col(panel, col).to_numpy(dtype=float)
        if (
            col.endswith("_rank_price10")
            or col.endswith("_rank_in_panel")
            or col.endswith("_count")
            or col.endswith("_denominator_count")
        ):
            values = np.log1p(values)
        columns.append(values)
        names.append(col)
    for col in boolean_features:
        columns.append(topk._bool_col(panel, col).astype(float).to_numpy(dtype=float))
        names.append(col)
    if not columns:
        return np.empty((len(panel), 0), dtype=float), []
    x = np.column_stack(columns).astype(float)
    return filter_feature_matrix(x, names, allowed_features=allowed_features)


def fit_standardizer(x_train: np.ndarray) -> Standardizer:
    """Fit train-only imputation and standardization statistics."""
    if x_train.shape[1] == 0:
        return Standardizer(np.empty(0), np.empty(0))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        mean = np.nanmean(x_train, axis=0)
    mean = np.where(np.isfinite(mean), mean, 0.0)
    filled = np.where(np.isfinite(x_train), x_train, mean)
    scale = filled.std(axis=0)
    scale = np.where(np.isfinite(scale) & (scale > 1e-9), scale, 1.0)
    return Standardizer(mean=mean, scale=scale)


def apply_standardizer(x: np.ndarray, standardizer: Standardizer) -> np.ndarray:
    """Apply train-only imputation and standardization statistics."""
    if x.shape[1] == 0:
        return x
    filled = np.where(np.isfinite(x), x, standardizer.mean)
    return np.asarray((filled - standardizer.mean) / standardizer.scale, dtype=float)


def _sigmoid(values: np.ndarray) -> np.ndarray:
    clipped = np.clip(values, -40.0, 40.0)
    return np.asarray(1.0 / (1.0 + np.exp(-clipped)), dtype=float)


def _balanced_weights(y: np.ndarray) -> np.ndarray:
    pos = float(y.sum())
    neg = float(len(y) - y.sum())
    weights = np.ones(len(y), dtype=float)
    if pos > 0.0 and neg > 0.0:
        weights[y >= 0.5] = neg / pos
    return np.asarray(weights / weights.mean(), dtype=float)


def fit_logistic_ridge(
    x: np.ndarray,
    y: np.ndarray,
    *,
    max_iter: int,
    learning_rate: float,
    l2: float,
) -> LogisticModel:
    """Fit a small weighted L2-logistic model using NumPy gradient descent."""
    if len(y) == 0 or x.shape[1] == 0 or y.min() == y.max():
        prior = float(y.mean()) if len(y) else 0.0
        prior = min(max(prior, 1e-6), 1.0 - 1e-6)
        return LogisticModel(coef=np.zeros(x.shape[1], dtype=float), intercept=float(np.log(prior / (1.0 - prior))))

    coef = np.zeros(x.shape[1], dtype=float)
    prior = min(max(float(y.mean()), 1e-6), 1.0 - 1e-6)
    intercept = float(np.log(prior / (1.0 - prior)))
    weights = _balanced_weights(y)
    denom = float(weights.sum())
    for _ in range(max_iter):
        logits = x @ coef + intercept
        pred = _sigmoid(logits)
        error = (pred - y) * weights
        grad_coef = (x.T @ error) / denom + l2 * coef
        grad_intercept = float(error.sum() / denom)
        coef -= learning_rate * grad_coef
        intercept -= learning_rate * grad_intercept
    return LogisticModel(coef=coef, intercept=intercept)


def _sample_pairwise_diffs(
    x: np.ndarray,
    y: np.ndarray,
    dates: np.ndarray,
    *,
    negatives_per_positive: int,
) -> np.ndarray:
    """Build deterministic same-date positive-minus-negative pairwise feature diffs."""
    diffs: list[np.ndarray] = []
    neg_limit = max(1, int(negatives_per_positive))
    for date in sorted(set(str(value) for value in dates.tolist())):
        date_mask = dates == date
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
    return np.vstack(diffs).astype(float)


def fit_pairwise_linear_ranker(
    x: np.ndarray,
    y: np.ndarray,
    dates: Sequence[str],
    *,
    max_iter: int,
    learning_rate: float,
    l2: float,
    negatives_per_positive: int,
) -> LogisticModel:
    """Fit a dependency-free pairwise linear ranker over same-date candidate pairs."""
    if len(y) == 0 or x.shape[1] == 0 or y.min() == y.max():
        return LogisticModel(coef=np.zeros(x.shape[1], dtype=float), intercept=0.0)
    diffs = _sample_pairwise_diffs(
        x,
        y,
        np.asarray([str(date) for date in dates], dtype=object),
        negatives_per_positive=negatives_per_positive,
    )
    if len(diffs) == 0:
        return LogisticModel(coef=np.zeros(x.shape[1], dtype=float), intercept=0.0)

    coef = np.zeros(x.shape[1], dtype=float)
    denom = float(len(diffs))
    for _ in range(max_iter):
        margin = diffs @ coef
        pred = _sigmoid(margin)
        grad_coef = -(diffs.T @ (1.0 - pred)) / denom + l2 * coef
        coef -= learning_rate * grad_coef
    return LogisticModel(coef=coef, intercept=0.0)


def fit_rank_model(
    x: np.ndarray,
    y: np.ndarray,
    dates: Sequence[str],
    *,
    config: LearnedRankerConfig,
) -> LogisticModel:
    """Fit the configured offline rank model."""
    if config.model_type == "logistic":
        return fit_logistic_ridge(
            x,
            y,
            max_iter=config.max_iter,
            learning_rate=config.learning_rate,
            l2=config.l2,
        )
    if config.model_type == "pairwise":
        return fit_pairwise_linear_ranker(
            x,
            y,
            dates,
            max_iter=config.max_iter,
            learning_rate=config.learning_rate,
            l2=config.l2,
            negatives_per_positive=config.pairwise_negatives_per_positive,
        )
    raise ValueError(f"unsupported model_type: {config.model_type}")


def predict_logit(model: LogisticModel, x: np.ndarray) -> np.ndarray:
    """Return ranking logits for a fitted model."""
    return np.asarray(x @ model.coef + model.intercept, dtype=float)


def _coefficient_rows(models: list[LogisticModel], feature_names: list[str]) -> pd.DataFrame:
    if not models:
        return pd.DataFrame(columns=["feature", "coef_mean", "coef_abs_mean", "coef_std"])
    coefs = np.vstack([m.coef for m in models])
    rows = [
        {
            "feature": feature,
            "coef_mean": round(float(coefs[:, idx].mean()), 6),
            "coef_abs_mean": round(float(np.abs(coefs[:, idx]).mean()), 6),
            "coef_std": round(float(coefs[:, idx].std()), 6),
        }
        for idx, feature in enumerate(feature_names)
    ]
    return pd.DataFrame(rows).sort_values("coef_abs_mean", ascending=False).reset_index(drop=True)


def run_learned_ranker(
    denominator: pd.DataFrame,
    labels: Sequence[tuple[str, str]],
    *,
    covered_dates: set[str],
    config: LearnedRankerConfig = LearnedRankerConfig(),
) -> LearnedRankerResult:
    """Run date-grouped OOF learned-ranker validation."""
    topk_config = topk.AuditConfig(top_n=config.top_n, min_score=config.min_score, ks=config.ks)
    panel = topk.build_score6_panel(denominator, labels, covered_dates=covered_dates, config=topk_config)
    if config.use_sector_context:
        panel = sector_context.add_stock_context_features(panel)
        panel, _sectors, _industries = sector_context.add_sector_industry_context(panel)
    if config.use_denominator_ranks:
        panel = add_denominator_rank_features(panel)
    if config.use_first_hour:
        if config.first_hour_minute_dir is None:
            raise ValueError("first_hour_minute_dir is required when use_first_hour=True")
        panel = first_hour.build_confirmation_panel(panel, minute_dir=config.first_hour_minute_dir)
    gates = topk.default_gates(panel)
    allowed_features = (
        load_qc_cloud_safe_feature_names(config.promotion_inventory_path)
        if config.use_qc_cloud_safe_features
        else None
    )
    x_raw, feature_names = build_feature_matrix(
        panel,
        include_sector_context=config.use_sector_context,
        include_first_hour=config.use_first_hour,
        include_denominator_ranks=config.use_denominator_ranks,
        include_sector_breadth=config.use_sector_breadth,
        allowed_features=allowed_features,
    )
    y = topk._bool_col(panel, "is_george").astype(float).to_numpy(dtype=float)
    folds = make_date_folds(panel["date"].astype(str).tolist(), n_folds=config.n_folds)

    oof_scores = pd.Series(float("-inf"), index=panel.index, dtype=float)
    fold_rows: list[dict[str, Any]] = []
    models: list[LogisticModel] = []
    for idx, valid_dates in enumerate(folds, start=1):
        valid_mask = panel["date"].isin(valid_dates).to_numpy(dtype=bool)
        train_mask = ~valid_mask
        x_train_raw = x_raw[train_mask]
        x_valid_raw = x_raw[valid_mask]
        y_train = y[train_mask]
        standardizer = fit_standardizer(x_train_raw)
        x_train = apply_standardizer(x_train_raw, standardizer)
        x_valid = apply_standardizer(x_valid_raw, standardizer)
        train_dates = panel.loc[panel.index[train_mask], "date"].astype(str).tolist()
        model = fit_rank_model(
            x_train,
            y_train,
            train_dates,
            config=config,
        )
        models.append(model)
        valid_scores = predict_logit(model, x_valid)
        oof_scores.loc[panel.index[valid_mask]] = valid_scores
        fold_rows.append(
            {
                "fold": idx,
                "valid_first_date": min(valid_dates),
                "valid_last_date": max(valid_dates),
                "train_rows": int(train_mask.sum()),
                "valid_rows": int(valid_mask.sum()),
                "train_hits": int(y_train.sum()),
                "valid_hits": int(y[valid_mask].sum()),
            }
        )

    variants = topk.default_rank_variants(panel, gates)
    all_rows = pd.Series(True, index=panel.index, dtype=bool)
    prefix_parts = ["learned_oof"]
    if config.model_type != "logistic":
        prefix_parts.append(config.model_type)
    if config.use_qc_cloud_safe_features:
        prefix_parts.append("qc_cloud_safe")
    if config.use_sector_context:
        prefix_parts.append("sector_context")
    if config.use_first_hour:
        prefix_parts.append("first_hour")
    if config.use_denominator_ranks:
        prefix_parts.append("denominator_ranks")
    if config.use_sector_breadth:
        prefix_parts.append("sector_breadth")
    prefix = "_".join(prefix_parts)
    variants = {
        f"{prefix}_all": (all_rows, oof_scores),
        f"{prefix}_clean_top2000": (gates["clean_top2000"], oof_scores),
        f"{prefix}_score7_or_clean6": (gates["score7_or_clean6"], oof_scores),
        **variants,
    }
    return LearnedRankerResult(
        base_summary=topk.summarize_base_panel(panel, label_count=len(labels)),
        gate_summary=topk.summarize_gates(panel, gates, label_count=len(labels)),
        rank_summary=topk.evaluate_rank_variants(panel, variants, label_count=len(labels), ks=config.ks),
        fold_summary=pd.DataFrame(fold_rows),
        coefficient_summary=_coefficient_rows(models, feature_names),
        failure_examples=topk.rank_failure_examples(panel, variants, k=10),
    )


def write_result(result: LearnedRankerResult, output_dir: Path) -> None:
    """Write learned-ranker result tables as CSVs."""
    output_dir.mkdir(parents=True, exist_ok=True)
    result.base_summary.to_csv(output_dir / "base_summary.csv", index=False)
    result.gate_summary.to_csv(output_dir / "gate_summary.csv", index=False)
    result.rank_summary.to_csv(output_dir / "rank_summary.csv", index=False)
    result.fold_summary.to_csv(output_dir / "fold_summary.csv", index=False)
    result.coefficient_summary.to_csv(output_dir / "coefficient_summary.csv", index=False)
    result.failure_examples.to_csv(output_dir / "failure_examples.csv", index=False)


def _print_result(result: LearnedRankerResult) -> None:
    print("\nBASE")
    print(result.base_summary.to_string(index=False))
    print("\nRANK VARIANTS")
    print(result.rank_summary.head(20).to_string(index=False))
    print("\nFOLDS")
    print(result.fold_summary.to_string(index=False))
    print("\nTOP COEFFICIENTS")
    print(result.coefficient_summary.head(20).to_string(index=False))
    print("\nFAILURE EXAMPLES")
    print(result.failure_examples.head(20).to_string(index=False))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels-csv", required=True, type=Path)
    parser.add_argument("--denominator-csv", required=True, type=Path)
    parser.add_argument("--coarse-dir", required=True, type=Path)
    parser.add_argument("--year", default=2026, type=int)
    parser.add_argument("--top-n", default=topk.DEFAULT_TOP_N, type=int)
    parser.add_argument("--min-score", default=topk.DEFAULT_MIN_SCORE, type=int)
    parser.add_argument("--n-folds", default=5, type=int)
    parser.add_argument("--model-type", choices=("logistic", "pairwise"), default="logistic")
    parser.add_argument("--max-iter", default=500, type=int)
    parser.add_argument("--learning-rate", default=0.05, type=float)
    parser.add_argument("--l2", default=0.01, type=float)
    parser.add_argument("--pairwise-negatives-per-positive", default=80, type=int)
    parser.add_argument("--use-sector-context", action="store_true")
    parser.add_argument("--use-first-hour", action="store_true")
    parser.add_argument("--use-denominator-ranks", action="store_true")
    parser.add_argument("--use-sector-breadth", action="store_true")
    parser.add_argument("--use-qc-cloud-safe-features", action="store_true")
    parser.add_argument("--promotion-inventory", default=DEFAULT_PROMOTION_INVENTORY, type=Path)
    parser.add_argument("--minute-dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)

    covered_dates = topk.covered_dates_from_coarse(args.year, args.coarse_dir)
    labels = topk.load_covered_labels(args.labels_csv, covered_dates=covered_dates)
    if not labels:
        raise ValueError("no George labels remain after covered-date filtering")
    result = run_learned_ranker(
        load_denominator(args.denominator_csv),
        labels,
        covered_dates=covered_dates,
        config=LearnedRankerConfig(
            top_n=args.top_n,
            min_score=args.min_score,
            n_folds=args.n_folds,
            model_type=args.model_type,
            max_iter=args.max_iter,
            learning_rate=args.learning_rate,
            l2=args.l2,
            pairwise_negatives_per_positive=args.pairwise_negatives_per_positive,
            use_sector_context=args.use_sector_context,
            use_first_hour=args.use_first_hour,
            use_denominator_ranks=args.use_denominator_ranks,
            use_sector_breadth=args.use_sector_breadth,
            use_qc_cloud_safe_features=args.use_qc_cloud_safe_features,
            promotion_inventory_path=args.promotion_inventory,
            first_hour_minute_dir=args.minute_dir,
        ),
    )
    _print_result(result)
    if args.output_dir is not None:
        write_result(result, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
