"""Optional LightGBM LambdaMART ranker for George/BCT scanner-alignment research.

This module is research-only. It imports LightGBM lazily so the main repo and CI do not require
the dependency unless this benchmark is executed.
"""
from __future__ import annotations

import argparse
import json
import importlib
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from runtime.scanner_ranker import (
    ARTIFACT_SCHEMA_VERSION,
    DENOMINATOR_CONTRACT_VERSION,
    DEPLOYABLE_SCANNER_FEATURES,
    FEATURE_CONTRACT_VERSION,
    feature_contract_hash,
    load_scanner_model_artifact,
)
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
    positive_weight: float = 1.0
    negative_weight: float = 1.0
    two_stage_top_n: int | None = None
    use_sector_context: bool = True
    use_denominator_ranks: bool = True
    use_sector_breadth: bool = True
    use_qc_cloud_safe_features: bool = False
    promotion_inventory_path: Path = learned.DEFAULT_PROMOTION_INVENTORY
    feature_allowlist: frozenset[str] | None = None
    ks: tuple[int, ...] = topk.DEFAULT_KS


@dataclass(frozen=True, slots=True)
class LambdaMARTResult:
    """In-memory result tables from the optional LambdaMART benchmark."""

    base_summary: pd.DataFrame
    gate_summary: pd.DataFrame
    rank_summary: pd.DataFrame
    fold_summary: pd.DataFrame
    importance_summary: pd.DataFrame
    failure_examples: pd.DataFrame


@dataclass(frozen=True, slots=True)
class LambdaMARTTrainingData:
    """Feature matrix and panel used by both OOF validation and train-all artifact export."""

    panel: pd.DataFrame
    x: np.ndarray
    y: np.ndarray
    feature_names: list[str]


@dataclass(frozen=True, slots=True)
class ExportedLambdaMARTArtifact:
    """Metadata for a written runtime artifact."""

    path: Path
    artifact_hash: str
    feature_list_hash: str
    feature_count: int
    row_count: int
    positive_count: int


def _import_lightgbm() -> Any:
    try:
        return importlib.import_module("lightgbm")
    except (ImportError, OSError) as exc:
        raise RuntimeError(
            "LightGBM is required for this optional research benchmark. "
            "Install it in the research venv with `python -m pip install lightgbm`; "
            "on macOS the wheel may also require `brew install libomp`."
        ) from exc


def date_group_order(dates: Sequence[str]) -> tuple[np.ndarray, list[int]]:
    """Return a stable date sort order plus LightGBM group sizes."""
    date_values = np.asarray([str(date) for date in dates], dtype=object)
    order = np.argsort(date_values, kind="stable")
    sorted_dates = date_values[order]
    groups = [int((sorted_dates == date).sum()) for date in pd.unique(sorted_dates)]
    return order, groups


def sort_by_date_groups(
    x: np.ndarray,
    y: np.ndarray,
    dates: Sequence[str],
) -> tuple[np.ndarray, np.ndarray, list[int]]:
    """Sort rows by date and return LightGBM group sizes."""
    order, groups = date_group_order(dates)
    return x[order], y[order], groups


def sample_weights(y: np.ndarray, *, config: LambdaMARTConfig) -> np.ndarray | None:
    """Return PU-style sample weights or None when weighting is disabled."""
    if config.positive_weight == 1.0 and config.negative_weight == 1.0:
        return None
    weights = np.where(y >= 0.5, config.positive_weight, config.negative_weight)
    return np.asarray(weights, dtype=float)


def runtime_export_config(config: LambdaMARTConfig) -> LambdaMARTConfig:
    """Return the train-all config that matches `runtime.scanner_ranker`'s deployable contract."""
    return replace(
        config,
        use_sector_context=False,
        use_denominator_ranks=True,
        use_sector_breadth=True,
        use_qc_cloud_safe_features=False,
        feature_allowlist=frozenset(DEPLOYABLE_SCANNER_FEATURES),
    )


def top_n_mask_by_date(panel: pd.DataFrame, scores: pd.Series, *, top_n: int) -> pd.Series:
    """Return a mask selecting the top-N scored rows per date."""
    if top_n <= 0:
        return pd.Series(False, index=panel.index, dtype=bool)
    ranked = panel[["date", "symbol"]].copy()
    ranked["_score"] = scores.reindex(panel.index).fillna(float("-inf"))
    ranked = ranked.sort_values(["date", "_score", "symbol"], ascending=[True, False, True])
    keep_index = ranked.groupby("date", sort=False).head(top_n).index
    out = pd.Series(False, index=panel.index, dtype=bool)
    out.loc[keep_index] = True
    return out


def _fit_lambdamart(
    x_train: np.ndarray,
    y_train: np.ndarray,
    train_dates: Sequence[str],
    *,
    feature_names: list[str],
    weights: np.ndarray | None = None,
    config: LambdaMARTConfig,
) -> Any:
    lgb = _import_lightgbm()
    order, groups = date_group_order(train_dates)
    x_sorted = x_train[order]
    y_sorted = y_train[order]
    sorted_weights = weights[order] if weights is not None else None
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
    model.fit(train_frame, y_sorted, group=groups, sample_weight=sorted_weights, eval_at=list(config.ks))
    return model


def build_lambdamart_training_data(
    denominator: pd.DataFrame,
    labels: Sequence[tuple[str, str]],
    *,
    covered_dates: set[str],
    config: LambdaMARTConfig = LambdaMARTConfig(),
) -> LambdaMARTTrainingData:
    """Build the grouped LambdaMART training panel and deployability-filtered feature matrix."""
    topk_config = topk.AuditConfig(top_n=config.top_n, min_score=config.min_score, ks=config.ks)
    denominator_for_panel = (
        learned.add_live_denominator_sector_breadth(
            denominator,
            covered_dates=covered_dates,
            top_n=config.top_n,
        )
        if config.use_sector_breadth
        else denominator
    )
    panel = topk.build_score6_panel(denominator_for_panel, labels, covered_dates=covered_dates, config=topk_config)
    if config.use_sector_context:
        panel = sector_context.add_stock_context_features(panel)
        panel, _sectors, _industries = sector_context.add_sector_industry_context(panel)
    if config.use_denominator_ranks:
        panel = learned.add_denominator_rank_features(panel)

    allowed_features = None
    if config.feature_allowlist is not None:
        allowed_features = set(config.feature_allowlist)
    elif config.use_qc_cloud_safe_features:
        allowed_features = learned.load_qc_cloud_safe_feature_names(config.promotion_inventory_path)
    x_raw, feature_names = learned.build_feature_matrix(
        panel,
        include_sector_context=config.use_sector_context,
        include_denominator_ranks=config.use_denominator_ranks,
        include_sector_breadth=config.use_sector_breadth,
        allowed_features=allowed_features,
    )
    y = topk._bool_col(panel, "is_george").astype(float).to_numpy(dtype=float)
    return LambdaMARTTrainingData(panel=panel, x=x_raw, y=y, feature_names=feature_names)


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
    training = build_lambdamart_training_data(
        denominator,
        labels,
        covered_dates=covered_dates,
        config=config,
    )
    panel = training.panel
    gates = topk.default_gates(panel)
    x_raw = training.x
    y = training.y
    feature_names = training.feature_names
    folds = learned.make_date_folds(panel["date"].astype(str).tolist(), n_folds=config.n_folds)

    oof_scores = pd.Series(float("-inf"), index=panel.index, dtype=float)
    fold_rows: list[dict[str, Any]] = []
    models: list[Any] = []
    for idx, valid_dates in enumerate(folds, start=1):
        valid_mask = panel["date"].isin(valid_dates).to_numpy(dtype=bool)
        train_mask = ~valid_mask
        train_indices = np.flatnonzero(train_mask)
        valid_indices = np.flatnonzero(valid_mask)
        train_dates = panel.loc[panel.index[train_mask], "date"].astype(str).tolist()
        train_weights = sample_weights(y[train_mask], config=config)
        if config.two_stage_top_n is None:
            model = _fit_lambdamart(
                x_raw[train_mask],
                y[train_mask],
                train_dates,
                feature_names=feature_names,
                weights=train_weights,
                config=config,
            )
            models.append(model)
            valid_frame = pd.DataFrame(x_raw[valid_mask], columns=feature_names)
            oof_scores.loc[panel.index[valid_mask]] = model.predict(valid_frame)
        else:
            stage1 = _fit_lambdamart(
                x_raw[train_mask],
                y[train_mask],
                train_dates,
                feature_names=feature_names,
                weights=train_weights,
                config=config,
            )
            train_panel = panel.loc[panel.index[train_mask]]
            train_frame = pd.DataFrame(x_raw[train_mask], columns=feature_names)
            stage1_train_scores = pd.Series(stage1.predict(train_frame), index=train_panel.index, dtype=float)
            train_top_mask = top_n_mask_by_date(
                train_panel,
                stage1_train_scores,
                top_n=config.two_stage_top_n,
            )
            selected_train_indices = train_indices[train_top_mask.to_numpy(dtype=bool)]
            selected_dates = panel.loc[panel.index[selected_train_indices], "date"].astype(str).tolist()
            selected_weights = sample_weights(y[selected_train_indices], config=config)
            stage2 = _fit_lambdamart(
                x_raw[selected_train_indices],
                y[selected_train_indices],
                selected_dates,
                feature_names=feature_names,
                weights=selected_weights,
                config=config,
            )
            models.append(stage2)
            valid_panel = panel.loc[panel.index[valid_mask]]
            valid_frame = pd.DataFrame(x_raw[valid_mask], columns=feature_names)
            stage1_valid_scores = pd.Series(stage1.predict(valid_frame), index=valid_panel.index, dtype=float)
            valid_top_mask = top_n_mask_by_date(
                valid_panel,
                stage1_valid_scores,
                top_n=config.two_stage_top_n,
            )
            fold_scores = pd.Series(float("-inf"), index=valid_panel.index, dtype=float)
            selected_valid_indices = valid_indices[valid_top_mask.to_numpy(dtype=bool)]
            selected_valid_frame = pd.DataFrame(x_raw[selected_valid_indices], columns=feature_names)
            fold_scores.loc[panel.index[selected_valid_indices]] = stage2.predict(selected_valid_frame)
            oof_scores.loc[valid_panel.index] = fold_scores
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
    if config.use_qc_cloud_safe_features:
        prefix_parts.append("qc_cloud_safe")
    if config.positive_weight != 1.0 or config.negative_weight != 1.0:
        prefix_parts.append(
            f"pu_pos{int(round(config.positive_weight * 100)):03d}_neg{int(round(config.negative_weight * 100)):03d}"
        )
    if config.two_stage_top_n is not None:
        prefix_parts.append(f"two_stage{config.two_stage_top_n}")
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
        failure_examples=topk.rank_failure_examples(panel, variants, k=10),
    )


def _repo_git_commit() -> str:
    root = Path(__file__).resolve().parents[2]
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()
    except Exception:
        return ""


def _model_trees(model: Any) -> list[dict[str, Any]]:
    booster = getattr(model, "booster_", None)
    if booster is None:
        raise ValueError("fitted LightGBM model has no booster_")
    dump = booster.dump_model()
    tree_info = dump.get("tree_info")
    if not isinstance(tree_info, list) or not tree_info:
        raise ValueError("LightGBM dump_model returned no tree_info")
    trees: list[dict[str, Any]] = []
    for tree in tree_info:
        if not isinstance(tree, dict) or "tree_structure" not in tree:
            raise ValueError("LightGBM tree_info entry missing tree_structure")
        trees.append(
            {
                key: tree[key]
                for key in ("tree_index", "num_leaves", "shrinkage", "tree_structure")
                if key in tree
            }
        )
    return trees


def train_lambdamart_model(
    denominator: pd.DataFrame,
    labels: Sequence[tuple[str, str]],
    *,
    covered_dates: set[str],
    config: LambdaMARTConfig = LambdaMARTConfig(),
) -> tuple[Any, LambdaMARTTrainingData]:
    """Train one final model on all covered dates for runtime artifact export."""
    training = build_lambdamart_training_data(
        denominator,
        labels,
        covered_dates=covered_dates,
        config=config,
    )
    if len(training.y) == 0:
        raise ValueError("cannot train LambdaMART artifact on an empty panel")
    if float(training.y.sum()) <= 0.0:
        raise ValueError("cannot train LambdaMART artifact without positive George labels")
    weights = sample_weights(training.y, config=config)
    model = _fit_lambdamart(
        training.x,
        training.y,
        training.panel["date"].astype(str).tolist(),
        feature_names=training.feature_names,
        weights=weights,
        config=config,
    )
    return model, training


def export_lambdamart_artifact(
    denominator: pd.DataFrame,
    labels: Sequence[tuple[str, str]],
    *,
    covered_dates: set[str],
    output_path: Path,
    config: LambdaMARTConfig = LambdaMARTConfig(),
    metadata: dict[str, Any] | None = None,
) -> ExportedLambdaMARTArtifact:
    """Train on all labels and write a QC-safe JSON artifact for `runtime.scanner_ranker`."""
    model, training = train_lambdamart_model(
        denominator,
        labels,
        covered_dates=covered_dates,
        config=config,
    )
    feature_names = tuple(training.feature_names)
    feature_list_hash = feature_contract_hash(feature_names)
    dates = sorted(str(date) for date in training.panel["date"].astype(str).unique().tolist())
    payload = {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "model_type": "lightgbm_lambdamart_json",
        "feature_names": list(feature_names),
        "feature_list_hash": feature_list_hash,
        "base_score": 0.0,
        "trees": _model_trees(model),
        "metadata": {
            "feature_contract_version": FEATURE_CONTRACT_VERSION,
            "denominator_contract_version": DENOMINATOR_CONTRACT_VERSION,
            "git_commit": _repo_git_commit(),
            "training_rows": int(len(training.panel)),
            "positive_labels": int(training.y.sum()),
            "covered_label_count": int(len(labels)),
            "date_count": int(len(dates)),
            "first_date": dates[0] if dates else "",
            "last_date": dates[-1] if dates else "",
            "top_n": int(config.top_n),
            "min_score": int(config.min_score),
            "n_estimators": int(config.n_estimators),
            "learning_rate": float(config.learning_rate),
            "num_leaves": int(config.num_leaves),
            "min_child_samples": int(config.min_child_samples),
            "positive_weight": float(config.positive_weight),
            "negative_weight": float(config.negative_weight),
            "use_sector_context": bool(config.use_sector_context),
            "use_denominator_ranks": bool(config.use_denominator_ranks),
            "use_sector_breadth": bool(config.use_sector_breadth),
            "runtime_contract_export": set(feature_names).issubset(set(DEPLOYABLE_SCANNER_FEATURES)),
            **(metadata or {}),
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False)
    output_path.write_text(text + "\n", encoding="utf-8")
    loaded = load_scanner_model_artifact(str(output_path))
    return ExportedLambdaMARTArtifact(
        path=output_path,
        artifact_hash=loaded.artifact_hash,
        feature_list_hash=feature_list_hash,
        feature_count=len(feature_names),
        row_count=int(len(training.panel)),
        positive_count=int(training.y.sum()),
    )


def write_result(result: LambdaMARTResult, output_dir: Path) -> None:
    """Write LambdaMART benchmark result tables as CSVs."""
    output_dir.mkdir(parents=True, exist_ok=True)
    result.base_summary.to_csv(output_dir / "base_summary.csv", index=False)
    result.gate_summary.to_csv(output_dir / "gate_summary.csv", index=False)
    result.rank_summary.to_csv(output_dir / "rank_summary.csv", index=False)
    result.fold_summary.to_csv(output_dir / "fold_summary.csv", index=False)
    result.importance_summary.to_csv(output_dir / "importance_summary.csv", index=False)
    result.failure_examples.to_csv(output_dir / "failure_examples.csv", index=False)


def _print_result(result: LambdaMARTResult) -> None:
    print("\nBASE")
    print(result.base_summary.to_string(index=False))
    print("\nRANK VARIANTS")
    print(result.rank_summary.head(20).to_string(index=False))
    print("\nFOLDS")
    print(result.fold_summary.to_string(index=False))
    print("\nTOP IMPORTANCES")
    print(result.importance_summary.head(20).to_string(index=False))
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
    parser.add_argument("--n-estimators", default=140, type=int)
    parser.add_argument("--learning-rate", default=0.045, type=float)
    parser.add_argument("--num-leaves", default=15, type=int)
    parser.add_argument("--min-child-samples", default=24, type=int)
    parser.add_argument("--positive-weight", default=1.0, type=float)
    parser.add_argument("--negative-weight", default=1.0, type=float)
    parser.add_argument("--two-stage-top-n", type=int)
    parser.add_argument("--no-sector-context", action="store_true")
    parser.add_argument("--no-denominator-ranks", action="store_true")
    parser.add_argument("--no-sector-breadth", action="store_true")
    parser.add_argument("--use-qc-cloud-safe-features", action="store_true")
    parser.add_argument("--promotion-inventory", default=learned.DEFAULT_PROMOTION_INVENTORY, type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument(
        "--skip-oof",
        action="store_true",
        help="Skip date-grouped OOF reporting and only run the requested train-all export.",
    )
    parser.add_argument(
        "--export-artifact",
        type=Path,
        help=(
            "Train one final runtime-contract model on all covered labels and write the validated "
            "JSON artifact. This forces the runtime deployable feature contract."
        ),
    )
    args = parser.parse_args(argv)
    if args.skip_oof and args.export_artifact is None:
        raise ValueError("--skip-oof requires --export-artifact")

    covered_dates = topk.covered_dates_from_coarse(args.year, args.coarse_dir)
    labels = topk.load_covered_labels(args.labels_csv, covered_dates=covered_dates)
    if not labels:
        raise ValueError("no George labels remain after covered-date filtering")
    denominator = learned.load_denominator(args.denominator_csv)
    config = LambdaMARTConfig(
        top_n=args.top_n,
        min_score=args.min_score,
        n_folds=args.n_folds,
        n_estimators=args.n_estimators,
        learning_rate=args.learning_rate,
        num_leaves=args.num_leaves,
        min_child_samples=args.min_child_samples,
        positive_weight=args.positive_weight,
        negative_weight=args.negative_weight,
        two_stage_top_n=args.two_stage_top_n,
        use_sector_context=not args.no_sector_context,
        use_denominator_ranks=not args.no_denominator_ranks,
        use_sector_breadth=not args.no_sector_breadth,
        use_qc_cloud_safe_features=args.use_qc_cloud_safe_features,
        promotion_inventory_path=args.promotion_inventory,
    )
    if not args.skip_oof:
        result = run_lambdamart_ranker(
            denominator,
            labels,
            covered_dates=covered_dates,
            config=config,
        )
        _print_result(result)
        if args.output_dir is not None:
            write_result(result, args.output_dir)
    if args.export_artifact is not None:
        artifact = export_lambdamart_artifact(
            denominator,
            labels,
            covered_dates=covered_dates,
            output_path=args.export_artifact,
            config=runtime_export_config(config),
            metadata={
                "labels_csv": str(args.labels_csv),
                "denominator_csv": str(args.denominator_csv),
                "coarse_dir": str(args.coarse_dir),
                "export_note": "runtime contract export for opt-in scanner ranker",
            },
        )
        print(
            "\nEXPORTED ARTIFACT "
            f"path={artifact.path} hash={artifact.artifact_hash[:12]} "
            f"features={artifact.feature_count} rows={artifact.row_count} positives={artifact.positive_count}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
