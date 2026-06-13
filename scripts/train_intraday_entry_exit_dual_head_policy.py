"""Train dual-head intraday entry/exit policies for #490 winner preservation."""
from __future__ import annotations

import argparse
import gzip
import io
import json
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import train_intraday_entry_exit_policy as base_policy  # noqa: E402

DEFAULT_PANEL = base_policy.DEFAULT_PANEL
DEFAULT_OUTPUT_DIR = ROOT / "sweeps" / "reports" / "intraday_entry_exit_policy_490_dual_head"
DUAL_HEAD_VERSION = "intraday_entry_exit_policy_490_dual_head_v1"
MODEL_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class HeadSpec:
    name: str
    row_type: str
    negative_class: str
    positive_class: str
    description: str
    target: Callable[[pd.DataFrame], pd.Series]


@dataclass(frozen=True)
class DualHeadConfig:
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
    parser.add_argument("--max-iter", type=int, default=120)
    parser.add_argument("--learning-rate", type=float, default=0.05)
    parser.add_argument("--l2", type=float, default=0.01)
    parser.add_argument("--limit", type=int, default=None, help="Optional row limit after loading.")
    return parser.parse_args()


def _bool_series(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip().str.lower().isin({"1", "true", "yes", "y"})


def _rate(numerator: int | float, denominator: int | float) -> float:
    return round(100.0 * float(numerator) / float(denominator), 3) if denominator else 0.0


def entry_bad_risk_target(frame: pd.DataFrame) -> pd.Series:
    return frame["trade_bucket"].astype(str).str.lower().eq("bad")


def entry_winner_preservation_target(frame: pd.DataFrame) -> pd.Series:
    bucket = frame["trade_bucket"].astype(str).str.lower()
    runner = frame["oracle_best_entry_outcome_20d"].astype(str).str.contains("runner", case=False, na=False)
    return bucket.eq("optimal") | runner


def entry_ready_target(frame: pd.DataFrame) -> pd.Series:
    return frame["entry_action_label"].astype(str).eq("enter_now")


def management_exit_risk_target(frame: pd.DataFrame) -> pd.Series:
    return frame["management_action_label"].astype(str).isin({"exit_loser", "protect_profit", "scratch_or_reduce"})


def management_runner_preservation_target(frame: pd.DataFrame) -> pd.Series:
    return frame["management_action_label"].astype(str).isin({"do_not_cut_runner", "hold_winner"})


HEAD_SPECS = (
    HeadSpec(
        name="entry_bad_risk_head",
        row_type="entry_decision",
        negative_class="not_bad_entry_risk",
        positive_class="bad_entry_risk",
        description="Predicts whether the candidate is a bad-entry route label, independent of entry timing.",
        target=entry_bad_risk_target,
    ),
    HeadSpec(
        name="entry_winner_preservation_head",
        row_type="entry_decision",
        negative_class="not_winner_preserve",
        positive_class="winner_preserve",
        description="Predicts whether the candidate should be preserved as an optimal or runner opportunity.",
        target=entry_winner_preservation_target,
    ),
    HeadSpec(
        name="entry_ready_head",
        row_type="entry_decision",
        negative_class="not_entry_ready",
        positive_class="entry_ready",
        description="Predicts whether the current checkpoint is at or after the oracle best-entry trigger.",
        target=entry_ready_target,
    ),
    HeadSpec(
        name="management_exit_risk_head",
        row_type="position_management",
        negative_class="not_exit_risk",
        positive_class="exit_risk",
        description="Predicts whether the position-management state calls for an exit, scratch, or protect action.",
        target=management_exit_risk_target,
    ),
    HeadSpec(
        name="management_runner_preservation_head",
        row_type="position_management",
        negative_class="not_runner_preserve",
        positive_class="runner_preserve",
        description="Predicts whether the position state should preserve a runner or active winner.",
        target=management_runner_preservation_target,
    ),
)


def head_subset(panel: pd.DataFrame, spec: HeadSpec) -> pd.DataFrame:
    frame = panel[panel["row_type"].eq(spec.row_type)].copy()
    if spec.row_type == "entry_decision":
        frame = frame[frame["entry_action_label"].isin(base_policy.ENTRY_ACTIONS)].copy()
    elif spec.row_type == "position_management":
        frame = frame[frame["management_action_label"].isin(base_policy.MANAGEMENT_ACTIONS)].copy()
    else:
        raise ValueError(f"unknown head row_type: {spec.row_type}")
    positive = spec.target(frame)
    frame["label_action"] = np.where(positive, spec.positive_class, spec.negative_class)
    return frame


def fit_oof_head(
    panel: pd.DataFrame,
    feature_names: Sequence[str],
    *,
    spec: HeadSpec,
    config: DualHeadConfig,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    classes = (spec.negative_class, spec.positive_class)
    frame = head_subset(panel, spec)
    class_to_idx = {label: idx for idx, label in enumerate(classes)}
    x_raw = base_policy.build_feature_matrix(frame, feature_names)
    y = frame["label_action"].map(class_to_idx).to_numpy(dtype=int)
    predictions = frame.copy()
    predictions["head_name"] = spec.name
    predictions["feature_version_490_dual"] = DUAL_HEAD_VERSION
    predictions["feature_hash_490_dual"] = base_policy.feature_hash(feature_names)
    predictions["oof_available_490_dual"] = False
    predictions["fold_490_dual"] = np.nan
    predictions["predicted_action"] = ""
    predictions["predicted_confidence"] = np.nan
    for action in classes:
        predictions[f"prob_{action}"] = np.nan

    splits = base_policy.make_walk_forward_splits(
        predictions["scan_date"].tolist(),
        n_folds=config.n_folds,
        min_train_folds=config.min_train_folds,
    )
    print(
        f"{spec.name}: rows={len(predictions)}, classes={','.join(classes)}, folds={len(splits)}, features={len(feature_names)}",
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
            f"{spec.name}: fitting fold {int(split['fold'])} "
            f"train={int(train_mask.sum())} valid={int(valid_mask.sum())} "
            f"valid_dates={split['valid_start']}..{split['valid_end']}",
            file=sys.stderr,
            flush=True,
        )
        standardizer = base_policy.fit_standardizer(x_raw[train_mask])
        x_train = base_policy.apply_standardizer(x_raw[train_mask], standardizer)
        x_valid = base_policy.apply_standardizer(x_raw[valid_mask], standardizer)
        model = base_policy.fit_softmax_linear(
            x_train,
            y[train_mask],
            classes,
            max_iter=config.max_iter,
            learning_rate=config.learning_rate,
            l2=config.l2,
        )
        probs = base_policy.predict_proba(model, x_valid)
        pred_idx = probs.argmax(axis=1)
        valid_indices = predictions.index[valid_mask]
        predictions.loc[valid_indices, "oof_available_490_dual"] = True
        predictions.loc[valid_indices, "fold_490_dual"] = int(split["fold"])
        predictions.loc[valid_indices, "predicted_action"] = [classes[idx] for idx in pred_idx]
        predictions.loc[valid_indices, "predicted_confidence"] = probs.max(axis=1)
        for idx, action in enumerate(classes):
            predictions.loc[valid_indices, f"prob_{action}"] = probs[:, idx]
        y_train = y[train_mask]
        fold_rows.append(
            {
                "head_name": spec.name,
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
                        "policy_name": spec.name,
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
        "policy_name": spec.name,
        "model_type": "binary_softmax_linear_oof_folds",
        "feature_version": DUAL_HEAD_VERSION,
        "feature_hash": base_policy.feature_hash(feature_names),
        "feature_names": list(feature_names),
        "classes": list(classes),
        "positive_class": spec.positive_class,
        "negative_class": spec.negative_class,
        "description": spec.description,
        "fold_models": models,
    }
    return predictions, pd.DataFrame(fold_rows), pd.DataFrame(coef_rows), artifact


def action_metrics(predictions: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    frame = predictions[predictions["oof_available_490_dual"]].copy()
    for head_name, group in frame.groupby("head_name", sort=True):
        actions = sorted(set(group["label_action"].dropna()) | set(group["predicted_action"].dropna()))
        for action in actions:
            label_is_action = group["label_action"].eq(action)
            pred_is_action = group["predicted_action"].eq(action)
            tp = int((label_is_action & pred_is_action).sum())
            fp = int((~label_is_action & pred_is_action).sum())
            fn = int((label_is_action & ~pred_is_action).sum())
            precision = tp / (tp + fp) if tp + fp else 0.0
            recall = tp / (tp + fn) if tp + fn else 0.0
            f1 = 2.0 * precision * recall / (precision + recall) if precision + recall else 0.0
            rows.append(
                {
                    "head_name": head_name,
                    "action": action,
                    "support": int(label_is_action.sum()),
                    "predicted": int(pred_is_action.sum()),
                    "precision_pct": _rate(tp, tp + fp),
                    "recall_pct": _rate(tp, tp + fn),
                    "f1": round(float(f1), 4),
                }
            )
    return pd.DataFrame(rows)


def summary_metrics(predictions: pd.DataFrame, actions: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    frame = predictions[predictions["oof_available_490_dual"]].copy()
    for head_name, group in frame.groupby("head_name", sort=True):
        head_actions = actions[actions["head_name"].eq(head_name)]
        positive_action = next(spec.positive_class for spec in HEAD_SPECS if spec.name == head_name)
        positive_metrics = head_actions[head_actions["action"].eq(positive_action)]
        rows.append(
            {
                "head_name": head_name,
                "rows": int(len(group)),
                "positive_class": positive_action,
                "positive_rate_pct": _rate(group["label_action"].eq(positive_action).sum(), len(group)),
                "accuracy_pct": round(100.0 * float(group["label_action"].eq(group["predicted_action"]).mean()), 3) if len(group) else 0.0,
                "macro_f1": round(float(head_actions["f1"].mean()), 4) if not head_actions.empty else 0.0,
                "positive_precision_pct": float(positive_metrics["precision_pct"].iloc[0]) if len(positive_metrics) else 0.0,
                "positive_recall_pct": float(positive_metrics["recall_pct"].iloc[0]) if len(positive_metrics) else 0.0,
            }
        )
    return pd.DataFrame(rows)


def grouped_summary(predictions: pd.DataFrame, *, group_col: str) -> pd.DataFrame:
    frame = predictions[predictions["oof_available_490_dual"]].copy()
    rows: list[dict[str, Any]] = []
    for (head_name, group_value), group in frame.groupby(["head_name", group_col], dropna=False, sort=True):
        rows.append(
            {
                "head_name": head_name,
                "group_col": group_col,
                "group_value": group_value,
                "rows": int(len(group)),
                "accuracy_pct": round(100.0 * float(group["label_action"].eq(group["predicted_action"]).mean()), 3),
            }
        )
    return pd.DataFrame(rows)


def prediction_output(predictions: pd.DataFrame) -> pd.DataFrame:
    base_cols = [
        "head_name",
        "feature_version_490_dual",
        "feature_hash_490_dual",
        "oof_available_490_dual",
        "fold_490_dual",
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
    config: DualHeadConfig,
) -> None:
    lines = [
        "# Intraday Entry/Exit Dual-Head Policy #490",
        "",
        "This trains separate bad-risk and winner-preservation heads instead of forcing entry labels into one softmax class race.",
        "The artifact is consumed by the #490 replay script as `dual_head_policy`.",
        "",
        "## Inputs",
        "",
        f"- Panel: `{config.panel}`",
        "",
        "## Summary Metrics",
        "",
        _markdown_table(
            summary,
            [
                "head_name",
                "rows",
                "positive_class",
                "positive_rate_pct",
                "accuracy_pct",
                "macro_f1",
                "positive_precision_pct",
                "positive_recall_pct",
            ],
        ),
        "",
        "## Action Metrics",
        "",
        _markdown_table(action, ["head_name", "action", "support", "predicted", "precision_pct", "recall_pct", "f1"], limit=80),
        "",
        "## Source/Month/Fold Diagnostics",
        "",
        _markdown_table(grouped, ["head_name", "group_col", "group_value", "rows", "accuracy_pct"], limit=80),
        "",
        "## Fold Summary",
        "",
        _markdown_table(folds, ["head_name", "fold", "train_start", "train_end", "valid_start", "valid_end", "train_rows", "valid_rows"], limit=50),
        "",
        "## Feature Diagnostics",
        "",
        _markdown_table(importance, ["policy_name", "action", "feature", "coef_mean", "coef_abs_mean"], limit=80),
        "",
        "## Read",
        "",
        "- Decision comes from replay economics, not classifier accuracy alone.",
        "- Entry heads separate bad-entry risk, winner preservation, and entry timing.",
        "- Management heads separate exit pressure from runner preservation.",
        "- Feature names reuse the existing #490 leakage guard.",
        "",
    ]
    (output_dir / "intraday_entry_exit_dual_head_policy_report.md").write_text("\n".join(lines), encoding="utf-8")


def write_outputs(
    *,
    predictions: pd.DataFrame,
    folds: pd.DataFrame,
    summary: pd.DataFrame,
    action: pd.DataFrame,
    grouped: pd.DataFrame,
    importance: pd.DataFrame,
    artifact: dict[str, Any],
    config: DualHeadConfig,
    output_dir: Path,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "README.md").write_text(
        "# intraday_entry_exit_policy_490_dual_head/\n\n"
        "Contains #490 dual-head intraday entry/exit policy artifacts.\n"
        "Keep OOF predictions, model JSON, metrics, reports, and manifest here.\n"
        "Do not store raw parquet data or replay trade ledgers here.\n",
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
        "dual_head_version": DUAL_HEAD_VERSION,
        "config": asdict(config),
        "heads": {
            spec.name: {
                "row_type": spec.row_type,
                "negative_class": spec.negative_class,
                "positive_class": spec.positive_class,
                "description": spec.description,
            }
            for spec in HEAD_SPECS
        },
        "outputs": {
            "oof_predictions.csv.gz": {"rows": int(len(predictions))},
            "fold_summary.csv": {"rows": int(len(folds))},
            "summary_metrics.csv": {"rows": int(len(summary))},
            "action_metrics.csv": {"rows": int(len(action))},
            "grouped_metrics.csv": {"rows": int(len(grouped))},
            "feature_importance.csv": {"rows": int(len(importance))},
            "model_artifact.json": {"schema_version": MODEL_SCHEMA_VERSION},
            "intraday_entry_exit_dual_head_policy_report.md": {},
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
        "report": output_dir / "intraday_entry_exit_dual_head_policy_report.md",
        "manifest": output_dir / "manifest.json",
    }


def run(
    *,
    panel_path: Path = DEFAULT_PANEL,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    n_folds: int = 6,
    min_train_folds: int = 1,
    max_iter: int = 120,
    learning_rate: float = 0.05,
    l2: float = 0.01,
    limit: int | None = None,
) -> dict[str, Path]:
    config = DualHeadConfig(
        panel=str(panel_path),
        output_dir=str(output_dir),
        n_folds=n_folds,
        min_train_folds=min_train_folds,
        max_iter=max_iter,
        learning_rate=learning_rate,
        l2=l2,
        limit=limit,
    )
    panel = base_policy.read_panel(panel_path, limit=limit)
    print(f"loaded panel rows={len(panel)} from {panel_path}", file=sys.stderr, flush=True)
    panel, feature_names = base_policy.add_policy_features(panel)
    print(f"built feature matrix columns={len(feature_names)} hash={base_policy.feature_hash(feature_names)}", file=sys.stderr, flush=True)
    prediction_frames: list[pd.DataFrame] = []
    fold_frames: list[pd.DataFrame] = []
    coef_frames: list[pd.DataFrame] = []
    artifacts: dict[str, Any] = {
        "schema_version": MODEL_SCHEMA_VERSION,
        "model_type": "dual_head_softmax_linear_oof_folds",
        "dual_head_version": DUAL_HEAD_VERSION,
        "feature_hash": base_policy.feature_hash(feature_names),
        "feature_names": feature_names,
        "policies": {},
    }
    for spec in HEAD_SPECS:
        print(f"starting {spec.name}", file=sys.stderr, flush=True)
        preds, folds, coefs, artifact = fit_oof_head(panel, feature_names, spec=spec, config=config)
        print(f"finished {spec.name}", file=sys.stderr, flush=True)
        prediction_frames.append(preds)
        fold_frames.append(folds)
        coef_frames.append(coefs)
        artifacts["policies"][spec.name] = artifact
    predictions = pd.concat(prediction_frames, ignore_index=True)
    folds = pd.concat(fold_frames, ignore_index=True)
    coefs = pd.concat(coef_frames, ignore_index=True)
    action = action_metrics(predictions)
    summary = summary_metrics(predictions, action)
    grouped = pd.concat(
        [
            grouped_summary(frame.assign(month=frame["scan_date"].astype(str).str.slice(0, 7)), group_col=group_col)
            for frame in prediction_frames
            for group_col in ("scanner_source_bucket", "month", "fold_490_dual")
        ],
        ignore_index=True,
    )
    importance = base_policy.feature_importance(coefs)
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
