"""Feature-source ablation harness for George/BCT scanner ranker research.

This module is research-only. It compares LambdaMART cells that progressively add blocked or
non-runtime feature sources to the raw QC-cloud-safe chart feature subset.
"""
from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from sweeps.archive import george_lambdamart_ranker as lambdamart
from sweeps.archive import george_learned_ranker as learned
from sweeps.archive import george_topk_audit as topk


@dataclass(frozen=True, slots=True)
class FeatureSourceCell:
    """One controlled LambdaMART feature-source cell."""

    cell_id: str
    label: str
    deployability_class: str
    use_sector_context: bool
    use_denominator_ranks: bool
    use_sector_breadth: bool
    allowed_sources: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FeatureSourceAblationConfig:
    """Settings for the scanner feature-source ablation run."""

    top_n: int = topk.DEFAULT_TOP_N
    min_score: int = topk.DEFAULT_MIN_SCORE
    n_folds: int = 5
    n_estimators: int = 140
    learning_rate: float = 0.045
    num_leaves: int = 15
    min_child_samples: int = 24
    random_state: int = 17
    promotion_inventory_path: Path = learned.DEFAULT_PROMOTION_INVENTORY
    ks: tuple[int, ...] = topk.DEFAULT_KS


@dataclass(frozen=True, slots=True)
class FeatureSourceAblationResult:
    """Combined result tables from all feature-source ablation cells."""

    cell_summary: pd.DataFrame
    rank_summary: pd.DataFrame
    importance_summary: pd.DataFrame
    failure_examples: pd.DataFrame


RAW_QC_SAFE_SOURCE = "raw_qc_safe"
DENOMINATOR_RANK_SOURCE = "denominator_ranks"
SECTOR_CONTEXT_SOURCE = "sector_context"
SECTOR_BREADTH_SOURCE = "sector_breadth"
ALL_RESEARCH_SOURCE = "all_research"


def default_cells() -> tuple[FeatureSourceCell, ...]:
    """Return the controlled feature-source cells from the ablation goal."""
    return (
        FeatureSourceCell(
            cell_id="raw_qc_safe",
            label="Raw QC-safe chart features only",
            deployability_class="qc_cloud_deployable",
            use_sector_context=False,
            use_denominator_ranks=False,
            use_sector_breadth=False,
            allowed_sources=(RAW_QC_SAFE_SOURCE,),
        ),
        FeatureSourceCell(
            cell_id="raw_plus_denominator_ranks",
            label="Raw QC-safe plus denominator-relative ranks",
            deployability_class="local_massive_only",
            use_sector_context=False,
            use_denominator_ranks=True,
            use_sector_breadth=False,
            allowed_sources=(RAW_QC_SAFE_SOURCE, DENOMINATOR_RANK_SOURCE),
        ),
        FeatureSourceCell(
            cell_id="raw_plus_sector_context",
            label="Raw QC-safe plus sector/industry context",
            deployability_class="tc2000_mapping_required",
            use_sector_context=True,
            use_denominator_ranks=False,
            use_sector_breadth=False,
            allowed_sources=(RAW_QC_SAFE_SOURCE, SECTOR_CONTEXT_SOURCE),
        ),
        FeatureSourceCell(
            cell_id="raw_plus_sector_breadth",
            label="Raw QC-safe plus sector/industry breadth",
            deployability_class="tc2000_mapping_required",
            use_sector_context=False,
            use_denominator_ranks=False,
            use_sector_breadth=True,
            allowed_sources=(RAW_QC_SAFE_SOURCE, SECTOR_BREADTH_SOURCE),
        ),
        FeatureSourceCell(
            cell_id="raw_plus_denominator_ranks_sector_context",
            label="Raw QC-safe plus denominator ranks plus sector context",
            deployability_class="local_plus_tc2000_blocked",
            use_sector_context=True,
            use_denominator_ranks=True,
            use_sector_breadth=False,
            allowed_sources=(RAW_QC_SAFE_SOURCE, DENOMINATOR_RANK_SOURCE, SECTOR_CONTEXT_SOURCE),
        ),
        FeatureSourceCell(
            cell_id="raw_plus_denominator_ranks_sector_breadth",
            label="Raw QC-safe plus denominator ranks plus sector breadth",
            deployability_class="local_plus_tc2000_blocked",
            use_sector_context=False,
            use_denominator_ranks=True,
            use_sector_breadth=True,
            allowed_sources=(RAW_QC_SAFE_SOURCE, DENOMINATOR_RANK_SOURCE, SECTOR_BREADTH_SOURCE),
        ),
        FeatureSourceCell(
            cell_id="full_research_reference",
            label="Full current research feature set",
            deployability_class="research_only_reference",
            use_sector_context=True,
            use_denominator_ranks=True,
            use_sector_breadth=True,
            allowed_sources=(ALL_RESEARCH_SOURCE,),
        ),
    )


def source_feature_names(
    source: str,
    *,
    promotion_inventory_path: Path,
) -> set[str] | None:
    """Return the feature names unlocked by one ablation source."""
    if source == ALL_RESEARCH_SOURCE:
        return None
    if source == RAW_QC_SAFE_SOURCE:
        return learned.load_qc_cloud_safe_feature_names(promotion_inventory_path)
    if source == DENOMINATOR_RANK_SOURCE:
        return set(learned.DENOMINATOR_RANK_FEATURES)
    if source == SECTOR_CONTEXT_SOURCE:
        return set(learned.SECTOR_NUMERIC_FEATURES + learned.SECTOR_BOOLEAN_FEATURES)
    if source == SECTOR_BREADTH_SOURCE:
        return set(learned.SECTOR_BREADTH_NUMERIC_FEATURES)
    raise ValueError(f"unsupported feature source: {source}")


def cell_feature_allowlist(
    cell: FeatureSourceCell,
    *,
    promotion_inventory_path: Path,
) -> frozenset[str] | None:
    """Return an explicit feature allowlist for `cell`, or None for the full reference."""
    names: set[str] = set()
    for source in cell.allowed_sources:
        source_names = source_feature_names(source, promotion_inventory_path=promotion_inventory_path)
        if source_names is None:
            return None
        names.update(source_names)
    if not names:
        raise ValueError(f"cell has no allowed features: {cell.cell_id}")
    return frozenset(names)


def clean_variant_name(variant: str) -> str:
    """Convert a LambdaMART variant name into a stable gate name."""
    for suffix in ("_clean_top2000", "_score7_or_clean6", "_all"):
        if variant.endswith(suffix):
            return suffix.removeprefix("_")
    return variant


def _with_cell_columns(frame: pd.DataFrame, cell: FeatureSourceCell, *, feature_count: int) -> pd.DataFrame:
    out = frame.copy()
    out.insert(0, "feature_count", feature_count)
    out.insert(0, "allowed_sources", "+".join(cell.allowed_sources))
    out.insert(0, "deployability_class", cell.deployability_class)
    out.insert(0, "cell_label", cell.label)
    out.insert(0, "cell_id", cell.cell_id)
    return out


def cell_summary_rows(result: lambdamart.LambdaMARTResult, cell: FeatureSourceCell, *, feature_count: int) -> list[dict[str, Any]]:
    """Return the learned LambdaMART all/clean/score7 rows for one ablation cell."""
    rows: list[dict[str, Any]] = []
    for row in result.rank_summary.to_dict("records"):
        gate = clean_variant_name(str(row["variant"]))
        if gate not in {"all", "clean_top2000", "score7_or_clean6"}:
            continue
        rows.append(
            {
                "cell_id": cell.cell_id,
                "cell_label": cell.label,
                "deployability_class": cell.deployability_class,
                "allowed_sources": "+".join(cell.allowed_sources),
                "feature_count": feature_count,
                "gate": gate,
                **row,
            }
        )
    return rows


def run_feature_source_ablation(
    denominator: pd.DataFrame,
    labels: Sequence[tuple[str, str]],
    *,
    covered_dates: set[str],
    config: FeatureSourceAblationConfig = FeatureSourceAblationConfig(),
    cells: Sequence[FeatureSourceCell] = default_cells(),
) -> FeatureSourceAblationResult:
    """Run all configured feature-source ablation cells."""
    summary_rows: list[dict[str, Any]] = []
    rank_frames: list[pd.DataFrame] = []
    importance_frames: list[pd.DataFrame] = []
    failure_frames: list[pd.DataFrame] = []
    for cell in cells:
        allowlist = cell_feature_allowlist(cell, promotion_inventory_path=config.promotion_inventory_path)
        result = lambdamart.run_lambdamart_ranker(
            denominator,
            labels,
            covered_dates=covered_dates,
            config=lambdamart.LambdaMARTConfig(
                top_n=config.top_n,
                min_score=config.min_score,
                n_folds=config.n_folds,
                n_estimators=config.n_estimators,
                learning_rate=config.learning_rate,
                num_leaves=config.num_leaves,
                min_child_samples=config.min_child_samples,
                random_state=config.random_state,
                use_sector_context=cell.use_sector_context,
                use_denominator_ranks=cell.use_denominator_ranks,
                use_sector_breadth=cell.use_sector_breadth,
                feature_allowlist=allowlist,
                ks=config.ks,
            ),
        )
        feature_count = int(len(result.importance_summary))
        summary_rows.extend(cell_summary_rows(result, cell, feature_count=feature_count))
        rank_frames.append(_with_cell_columns(result.rank_summary, cell, feature_count=feature_count))
        importance_frames.append(_with_cell_columns(result.importance_summary, cell, feature_count=feature_count))
        failure_frames.append(_with_cell_columns(result.failure_examples, cell, feature_count=feature_count))

    return FeatureSourceAblationResult(
        cell_summary=pd.DataFrame(summary_rows),
        rank_summary=pd.concat(rank_frames, ignore_index=True) if rank_frames else pd.DataFrame(),
        importance_summary=pd.concat(importance_frames, ignore_index=True) if importance_frames else pd.DataFrame(),
        failure_examples=pd.concat(failure_frames, ignore_index=True) if failure_frames else pd.DataFrame(),
    )


def write_result(result: FeatureSourceAblationResult, output_dir: Path) -> None:
    """Write combined feature-source ablation result tables as CSVs."""
    output_dir.mkdir(parents=True, exist_ok=True)
    result.cell_summary.to_csv(output_dir / "cell_summary.csv", index=False)
    result.rank_summary.to_csv(output_dir / "rank_summary.csv", index=False)
    result.importance_summary.to_csv(output_dir / "importance_summary.csv", index=False)
    result.failure_examples.to_csv(output_dir / "failure_examples.csv", index=False)


def _print_result(result: FeatureSourceAblationResult) -> None:
    summary = result.cell_summary
    if not summary.empty:
        summary = summary.sort_values(["gate", "recall10_pct", "recall5_pct"], ascending=[True, False, False])
    print("\nCELL SUMMARY")
    print(
        summary[
            [
                "cell_id",
                "gate",
                "feature_count",
                "seen_hits",
                "hits5",
                "hits10",
                "hits20",
                "hits50",
                "hits100",
                "precision10_pct",
                "map_seen_pct",
                "ndcg10_seen_pct",
                "median_george_rank",
            ]
        ].to_string(index=False)
        if not summary.empty
        else "(empty)"
    )


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
    parser.add_argument("--promotion-inventory", default=learned.DEFAULT_PROMOTION_INVENTORY, type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)

    covered_dates = topk.covered_dates_from_coarse(args.year, args.coarse_dir)
    labels = topk.load_covered_labels(args.labels_csv, covered_dates=covered_dates)
    if not labels:
        raise ValueError("no George labels remain after covered-date filtering")
    result = run_feature_source_ablation(
        learned.load_denominator(args.denominator_csv),
        labels,
        covered_dates=covered_dates,
        config=FeatureSourceAblationConfig(
            top_n=args.top_n,
            min_score=args.min_score,
            n_folds=args.n_folds,
            n_estimators=args.n_estimators,
            learning_rate=args.learning_rate,
            num_leaves=args.num_leaves,
            min_child_samples=args.min_child_samples,
            promotion_inventory_path=args.promotion_inventory,
        ),
    )
    _print_result(result)
    if args.output_dir is not None:
        write_result(result, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
