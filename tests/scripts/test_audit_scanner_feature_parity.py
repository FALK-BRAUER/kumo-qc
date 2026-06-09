from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[2] / "scripts")]

import audit_scanner_feature_parity as A


def _write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def test_classify_feature_prioritizes_non_deployable_patterns() -> None:
    assert A.classify_feature("oof_model_score") == "non_deployable_model_score"
    assert A.classify_feature("george_prior_any_120d") == "non_deployable_george_evidence"
    assert A.classify_feature("bct_score", qc_features={"bct_score"}) == "qc_ranker_feature"
    assert (
        A.classify_feature("sector_bct7_count", inventory_class="tc2000_mapping_required")
        == "blocked_tc2000_mapping"
    )
    assert (
        A.classify_feature("adv20_rank_in_panel", inventory_class="local_massive_only")
        == "blocked_local_massive_only"
    )
    assert (
        A.classify_feature("d_ma200_overhead_pct", inventory_class="qc_cloud_deployable")
        == "clean_available_not_used"
    )


def test_build_column_inventory_uses_inventory_and_qc_feature_sets() -> None:
    rows = A.build_column_inventory(
        ["bct_score", "d_ma200_overhead_pct", "oof_model_score"],
        inventory={
            "bct_score": {"deployability_class": "qc_cloud_deployable"},
            "d_ma200_overhead_pct": {"deployability_class": "qc_cloud_deployable"},
            "oof_model_score": {"deployability_class": "offline_research_only"},
        },
    )

    by_feature = {row["feature"]: row["qc_status"] for row in rows}
    assert by_feature["bct_score"] == "qc_ranker_feature"
    assert by_feature["d_ma200_overhead_pct"] == "clean_available_not_used"
    assert by_feature["oof_model_score"] == "non_deployable_model_score"


def test_write_outputs_creates_report_and_column_csv(tmp_path: Path) -> None:
    denominator = tmp_path / "den.csv"
    inventory = tmp_path / "inventory.csv"
    importances = tmp_path / "importances.csv"
    variants = tmp_path / "variants.csv"
    output_md = tmp_path / "report.md"
    output_csv = tmp_path / "columns.csv"

    _write_csv(
        denominator,
        [{"bct_score": "7", "d_ma200_overhead_pct": "1.2", "oof_model_score": "0.8"}],
        ["bct_score", "d_ma200_overhead_pct", "oof_model_score"],
    )
    _write_csv(
        inventory,
        [
            {
                "feature": "bct_score",
                "deployability_class": "qc_cloud_deployable",
                "safe_for_qc_handoff": "True",
                "used_in_feature_sets": "qc_cloud_deployable",
                "handoff_note": "safe",
            },
            {
                "feature": "d_ma200_overhead_pct",
                "deployability_class": "qc_cloud_deployable",
                "safe_for_qc_handoff": "True",
                "used_in_feature_sets": "qc_cloud_deployable",
                "handoff_note": "safe",
            },
            {
                "feature": "oof_model_score",
                "deployability_class": "offline_research_only",
                "safe_for_qc_handoff": "False",
                "used_in_feature_sets": "offline_oof_research",
                "handoff_note": "research only",
            },
        ],
        ["feature", "deployability_class", "safe_for_qc_handoff", "used_in_feature_sets", "handoff_note"],
    )
    _write_csv(
        importances,
        [{"feature": "oof_model_score", "importance": "0.5"}],
        ["feature", "importance"],
    )
    _write_csv(
        variants,
        [
            {"variant": "feature_rich_gbm_date_grouped_cv", "recall10_pct": "44.7", "precision10_pct": "28.36"},
            {"variant": "stage1_kijun_baseline", "recall10_pct": "31.81", "precision10_pct": "20.18"},
        ],
        ["variant", "recall10_pct", "precision10_pct"],
    )

    rows, report = A.write_outputs(
        denominator_path=denominator,
        inventory_path=inventory,
        importances_path=importances,
        variants_path=variants,
        output_md=output_md,
        output_csv=output_csv,
    )

    assert report == str(output_md)
    assert output_md.exists()
    assert output_csv.exists()
    assert {row["qc_status"] for row in rows} >= {"qc_ranker_feature", "clean_available_not_used"}
    assert "oof_model_score" in output_md.read_text(encoding="utf-8")
