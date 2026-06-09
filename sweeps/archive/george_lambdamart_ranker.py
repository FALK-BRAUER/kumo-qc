"""Optional LightGBM LambdaMART ranker for George/BCT scanner-alignment research.

This module is research-only. It imports LightGBM lazily so the main repo and CI do not require
the dependency unless this benchmark is executed.
"""
from __future__ import annotations

import argparse
import importlib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from sweeps.archive import george_learned_ranker as learned
from sweeps.archive import george_sector_context_audit as sector_context
from sweeps.archive import george_topk_audit as topk


@dataclass(frozen=True, slots=True)
class LambdaMARTConfig:
    """Configuration for the optional LightGBM grouped ranker benchmark."""

    top_n: int = topk.DEFAULT_TOP_N
    min_score: int = topk.DEFAULT_MIN_SCORE
    n_folds: int = 5
    n_estimators: int = 140
    learning_rate: float = 0.045
    num_leaves: int = 15
    min_child_samples: int = 24
    random_state: int = 17
    use_sector_context: bool = True
    use_denominator_ranks: bool = True
    use_sector_breadth: bool = True
    ks: tuple[int, ...] = topk.DEFAULT_KS


@dataclass(frozen=True, slots=True)
class LambdaMARTResult:
    """In-memory result tables from the optional LambdaMART benchmark."""

    base_summary: pd.DataFrame
    gate_summary: pd.DataFrame
    rank_summary: pd.DataFrame
    fold_summary: pd.DataFrame
    importance_summary: pd.DataFrame


def _import_lightgbm() -> Any:
    try:
        return importlib.import_module("lightgbm")
    except (ImportError, OSError) as exc:
        raise RuntimeError(
            "LightGBM is required for this optional research benchmark. "
            "Install it in the research venv with `python -m pip install lightgbm`; "
            "on macOS the wheel may also require `brew install libomp`."
        ) from exc


def sort_by_date_groups(
    x: np.ndarray,
    y: np.ndarray,
    dates: Sequence[str],
) -> tuple[np.ndarray, np.ndarray, list[int]]:
    """Sort rows by date and return LightGBM group sizes."""
    date_values = np.asarray([str(date) for date in dates], dtype=object)
    order = np.argsort(date_values, kind="stable")
    sorted_dates = date_values[order]
    groups = [int((sorted_dates == date).sum()) for date in pd.unique(sorted_dates)]
    return x[order], y[order], groups


def _fit_lambdamart(
    x_train: np.ndarray,
    y_train: np.ndarray,
    train_dates: Sequence[str],
    *,
    feature_names: list[str],
    config: LambdaMARTConfig,
) -> Any:
    lgb = _import_lightgbm()
    x_sorted, y_sorted, groups = sort_by_date_groups(x_train, y_train, train_dates)
    train_frame = pd.DataFrame(x_sorted, columns=feature_names)
    model = lgb.LGBMRanker(
        objective="lambdarank",
        metric="ndcg",
        n_estimators=config.n_estimators,
        learning_rate=config.learning_rate,
        num_leaves=config.num_leaves,
        min_child_samples=config.min_child_samples,
        random_state=config.random_state,
        n_jobs=1,
        verbose=-1,
    )
    model.fit(train_frame, y_sorted, group=groups, eval_at=list(config.ks))
    return model


def _importance_rows(models: list[Any], feature_names: list[str]) -> pd.DataFrame:
    if not models:
        return pd.DataFrame(columns=["feature", "importance_mean", "importance_std"])
    importances = np.vstack([np.asarray(model.feature_importances_, dtype=float) for model in models])
    rows = [
        {
            "feature": feature,
            "importance_mean": round(float(importances[:, idx].mean()), 6),
            "importance_std": round(float(importances[:, idx].std()), 6),
        }
        for idx, feature in enumerate(feature_names)
    ]
    return pd.DataFrame(rows).sort_values("importance_mean", ascending=False).reset_index(drop=True)


def run_lambdamart_ranker(
    denominator: pd.DataFrame,
    labels: Sequence[tuple[str, str]],
    *,
    covered_dates: set[str],
    config: LambdaMARTConfig = LambdaMARTConfig(),
) -> LambdaMARTResult:
    """Run date-grouped OOF LambdaMART validation."""
    topk_config = topk.AuditConfig(top_n=config.top_n, min_score=config.min_score, ks=config.ks)
    panel = topk.build_score6_panel(denominator, labels, covered_dates=covered_dates, config=topk_config)
    if config.use_sector_context:
        panel = sector_context.add_stock_context_features(panel)
        panel, _sectors, _industries = sector_context.add_sector_industry_context(panel)
    if config.use_denominator_ranks:
        panel = learned.add_denominator_rank_features(panel)

    gates = topk.default_gates(panel)
    x_raw, feature_names = learned.build_feature_matrix(
        panel,
        include_sector_context=config.use_sector_context,
        include_denominator_ranks=config.use_denominator_ranks,
        include_sector_breadth=config.use_sector_breadth,
    )
    y = topk._bool_col(panel, "is_george").astype(float).to_numpy(dtype=float)
    folds = learned.make_date_folds(panel["date"].astype(str).tolist(), n_folds=config.n_folds)

    oof_scores = pd.Series(float("-inf"), index=panel.index, dtype=float)
    fold_rows: list[dict[str, Any]] = []
    models: list[Any] = []
    for idx, valid_dates in enumerate(folds, start=1):
        valid_mask = panel["date"].isin(valid_dates).to_numpy(dtype=bool)
        train_mask = ~valid_mask
        train_dates = panel.loc[panel.index[train_mask], "date"].astype(str).tolist()
        model = _fit_lambdamart(
            x_raw[train_mask],
            y[train_mask],
            train_dates,
            feature_names=feature_names,
            config=config,
        )
        models.append(model)
        valid_frame = pd.DataFrame(x_raw[valid_mask], columns=feature_names)
        oof_scores.loc[panel.index[valid_mask]] = model.predict(valid_frame)
        fold_rows.append(
            {
                "fold": idx,
                "valid_first_date": min(valid_dates),
                "valid_last_date": max(valid_dates),
                "train_rows": int(train_mask.sum()),
                "valid_rows": int(valid_mask.sum()),
                "train_hits": int(y[train_mask].sum()),
                "valid_hits": int(y[valid_mask].sum()),
            }
        )

    all_rows = pd.Series(True, index=panel.index, dtype=bool)
    prefix_parts = ["lambdamart"]
    if config.use_sector_context:
        prefix_parts.append("sector_context")
    if config.use_denominator_ranks:
        prefix_parts.append("denominator_ranks")
    if config.use_sector_breadth:
        prefix_parts.append("sector_breadth")
    prefix = "_".join(prefix_parts)
    variants = {
        f"{prefix}_all": (all_rows, oof_scores),
        f"{prefix}_clean_top2000": (gates["clean_top2000"], oof_scores),
        f"{prefix}_score7_or_clean6": (gates["score7_or_clean6"], oof_scores),
        **topk.default_rank_variants(panel, gates),
    }
    return LambdaMARTResult(
        base_summary=topk.summarize_base_panel(panel, label_count=len(labels)),
        gate_summary=topk.summarize_gates(panel, gates, label_count=len(labels)),
        rank_summary=topk.evaluate_rank_variants(panel, variants, label_count=len(labels), ks=config.ks),
        fold_summary=pd.DataFrame(fold_rows),
        importance_summary=_importance_rows(models, feature_names),
    )


def write_result(result: LambdaMARTResult, output_dir: Path) -> None:
    """Write LambdaMART benchmark result tables as CSVs."""
    output_dir.mkdir(parents=True, exist_ok=True)
    result.base_summary.to_csv(output_dir / "base_summary.csv", index=False)
    result.gate_summary.to_csv(output_dir / "gate_summary.csv", index=False)
    result.rank_summary.to_csv(output_dir / "rank_summary.csv", index=False)
    result.fold_summary.to_csv(output_dir / "fold_summary.csv", index=False)
    result.importance_summary.to_csv(output_dir / "importance_summary.csv", index=False)


def _print_result(result: LambdaMARTResult) -> None:
    print("\nBASE")
    print(result.base_summary.to_string(index=False))
    print("\nRANK VARIANTS")
    print(result.rank_summary.head(20).to_string(index=False))
    print("\nFOLDS")
    print(result.fold_summary.to_string(index=False))
    print("\nTOP IMPORTANCES")
    print(result.importance_summary.head(20).to_string(index=False))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels-csv", required=True, type=Path)
    parser.add_argument("--denominator-csv", required=True, type=Path)
    parser.add_argument("--coarse-dir", required=True, type=Path)
    parser.add_argument("--year", default=2026, type=int)
    parser.add_argument("--top-n", default=topk.DEFAULT_TOP_N, type=int)
    parser.add_argument("--min-score", default=topk.DEFAULT_MIN_SCORE, type=int)
    parser.add_argument("--n-folds", default=5, type=int)
    parser.add_argument("--n-estimators", default=140, type=int)
    parser.add_argument("--learning-rate", default=0.045, type=float)
    parser.add_argument("--num-leaves", default=15, type=int)
    parser.add_argument("--min-child-samples", default=24, type=int)
    parser.add_argument("--no-sector-context", action="store_true")
    parser.add_argument("--no-denominator-ranks", action="store_true")
    parser.add_argument("--no-sector-breadth", action="store_true")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)

    covered_dates = topk.covered_dates_from_coarse(args.year, args.coarse_dir)
    labels = topk.load_covered_labels(args.labels_csv, covered_dates=covered_dates)
    if not labels:
        raise ValueError("no George labels remain after covered-date filtering")
    result = run_lambdamart_ranker(
        learned.load_denominator(args.denominator_csv),
        labels,
        covered_dates=covered_dates,
        config=LambdaMARTConfig(
            top_n=args.top_n,
            min_score=args.min_score,
            n_folds=args.n_folds,
            n_estimators=args.n_estimators,
            learning_rate=args.learning_rate,
            num_leaves=args.num_leaves,
            min_child_samples=args.min_child_samples,
            use_sector_context=not args.no_sector_context,
            use_denominator_ranks=not args.no_denominator_ranks,
            use_sector_breadth=not args.no_sector_breadth,
        ),
    )
    _print_result(result)
    if args.output_dir is not None:
        write_result(result, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
