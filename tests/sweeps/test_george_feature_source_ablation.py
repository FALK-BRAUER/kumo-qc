"""Tests for the scanner feature-source ablation harness."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from sweeps.archive import george_feature_source_ablation as A
from sweeps.archive import george_lambdamart_ranker as L
from sweeps.archive import george_learned_ranker as learned


def _write_promotion_inventory(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "feature,qc_status,deployability_class,safe_for_qc_handoff,used_in_feature_sets,handoff_note",
                "gap_pct,qc_ranker_feature,qc_cloud_deployable,True,,",
                "daily_structure_score,qc_ranker_feature,qc_cloud_deployable,True,,",
                "gap_pct_rank_in_panel,blocked_local_massive_only,local_massive_only,False,,",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_cell_allowlists_combine_sources_without_promoting_blocked_features(tmp_path: Path) -> None:
    inventory = tmp_path / "features.csv"
    _write_promotion_inventory(inventory)
    cells = {cell.cell_id: cell for cell in A.default_cells()}

    raw = A.cell_feature_allowlist(cells["raw_qc_safe"], promotion_inventory_path=inventory)
    with_ranks = A.cell_feature_allowlist(cells["raw_plus_denominator_ranks"], promotion_inventory_path=inventory)
    full = A.cell_feature_allowlist(cells["full_research_reference"], promotion_inventory_path=inventory)

    assert raw == frozenset({"gap_pct", "daily_structure_score"})
    assert with_ranks is not None
    assert "gap_pct" in with_ranks
    assert "gap_pct_rank_in_panel" in with_ranks
    assert set(learned.DENOMINATOR_RANK_FEATURES).issubset(with_ranks)
    assert full is None


def test_clean_variant_name_extracts_gate() -> None:
    assert A.clean_variant_name("lambdamart_clean_top2000") == "clean_top2000"
    assert A.clean_variant_name("lambdamart_score7_or_clean6") == "score7_or_clean6"
    assert A.clean_variant_name("lambdamart_all") == "all"


def test_run_feature_source_ablation_combines_cell_tables(monkeypatch: Any, tmp_path: Path) -> None:
    inventory = tmp_path / "features.csv"
    _write_promotion_inventory(inventory)
    captured: list[L.LambdaMARTConfig] = []

    def fake_run_lambdamart_ranker(
        denominator: pd.DataFrame,
        labels: list[tuple[str, str]],
        *,
        covered_dates: set[str],
        config: L.LambdaMARTConfig,
    ) -> L.LambdaMARTResult:
        captured.append(config)
        variant_prefix = "lambdamart"
        if config.use_denominator_ranks:
            variant_prefix += "_denominator_ranks"
        rank_summary = pd.DataFrame(
            [
                {
                    "variant": f"{variant_prefix}_all",
                    "rows": 10,
                    "median_daily": 5.0,
                    "seen_hits": 2,
                    "seen_recall_pct": 100.0,
                    "median_george_rank": 1.0,
                    "map_seen_pct": 100.0,
                    "hits5": 2,
                    "recall5_pct": 100.0,
                    "precision5_pct": 20.0,
                    "ndcg5_seen_pct": 100.0,
                    "hits10": 2,
                    "recall10_pct": 100.0,
                    "precision10_pct": 10.0,
                    "ndcg10_seen_pct": 100.0,
                    "hits20": 2,
                    "recall20_pct": 100.0,
                    "precision20_pct": 5.0,
                    "ndcg20_seen_pct": 100.0,
                    "hits50": 2,
                    "recall50_pct": 100.0,
                    "precision50_pct": 2.0,
                    "ndcg50_seen_pct": 100.0,
                    "hits100": 2,
                    "recall100_pct": 100.0,
                    "precision100_pct": 1.0,
                    "ndcg100_seen_pct": 100.0,
                }
            ]
        )
        return L.LambdaMARTResult(
            base_summary=pd.DataFrame(),
            gate_summary=pd.DataFrame(),
            rank_summary=rank_summary,
            fold_summary=pd.DataFrame(),
            importance_summary=pd.DataFrame(
                [{"feature": "gap_pct", "importance_mean": 1.0, "importance_std": 0.0}]
            ),
            failure_examples=pd.DataFrame(
                [
                    {
                        "variant": f"{variant_prefix}_all",
                        "date": "2026-02-12",
                        "k": 10,
                        "seen_george_count": 1,
                        "best_george_rank": 11,
                        "george_symbols": "AAA@11",
                        "top_symbols": "BBB",
                    }
                ]
            ),
        )

    monkeypatch.setattr(
        "sweeps.archive.george_feature_source_ablation.lambdamart.run_lambdamart_ranker",
        fake_run_lambdamart_ranker,
    )
    cells = (
        A.FeatureSourceCell(
            cell_id="raw_qc_safe",
            label="Raw",
            deployability_class="qc_cloud_deployable",
            use_sector_context=False,
            use_denominator_ranks=False,
            use_sector_breadth=False,
            allowed_sources=(A.RAW_QC_SAFE_SOURCE,),
        ),
        A.FeatureSourceCell(
            cell_id="raw_plus_denominator_ranks",
            label="Raw plus ranks",
            deployability_class="local_massive_only",
            use_sector_context=False,
            use_denominator_ranks=True,
            use_sector_breadth=False,
            allowed_sources=(A.RAW_QC_SAFE_SOURCE, A.DENOMINATOR_RANK_SOURCE),
        ),
    )

    result = A.run_feature_source_ablation(
        pd.DataFrame(),
        [("2026-02-12", "AAA")],
        covered_dates={"2026-02-12"},
        config=A.FeatureSourceAblationConfig(promotion_inventory_path=inventory),
        cells=cells,
    )

    assert len(captured) == 2
    assert captured[0].feature_allowlist == frozenset({"gap_pct", "daily_structure_score"})
    assert captured[1].feature_allowlist is not None
    assert "gap_pct_rank_in_panel" in captured[1].feature_allowlist
    assert set(result.cell_summary["cell_id"]) == {"raw_qc_safe", "raw_plus_denominator_ranks"}
    assert set(result.rank_summary["cell_id"]) == {"raw_qc_safe", "raw_plus_denominator_ranks"}
    assert set(result.importance_summary["cell_id"]) == {"raw_qc_safe", "raw_plus_denominator_ranks"}
    assert set(result.failure_examples["cell_id"]) == {"raw_qc_safe", "raw_plus_denominator_ranks"}
