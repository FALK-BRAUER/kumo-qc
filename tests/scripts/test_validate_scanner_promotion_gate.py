from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

sys.path[:0] = [str(Path(__file__).resolve().parents[2] / "scripts")]

import validate_scanner_promotion_gate as V


def _row(**overrides: str) -> dict[str, str]:
    row = {field: "" for field in V.SCHEMA}
    row.update(
        {
            "feature": "gap_pct",
            "qc_status": "qc_ranker_feature",
            "deployability_class": "qc_cloud_deployable",
            "safe_for_qc_handoff": "True",
            "used_in_feature_sets": "qc_cloud_deployable",
            "handoff_note": "safe to hand to kumo-qc after normal QC data-availability checks",
        }
    )
    row.update(overrides)
    return row


def _minimal_rows() -> list[dict[str, str]]:
    return [
        _row(feature="gap_pct"),
        _row(feature="d_ma200_overhead_pct", qc_status="clean_available_not_used"),
        _row(
            feature="gap_pct_rank_in_panel",
            qc_status="blocked_local_massive_only",
            deployability_class="local_massive_only",
            safe_for_qc_handoff="False",
            used_in_feature_sets="local_real_data",
            handoff_note="port only after matching the live QC universe and rank denominator",
        ),
        _row(
            feature="sector_bct7_pct",
            qc_status="qc_ranker_feature",
            deployability_class="qc_cloud_deployable",
            safe_for_qc_handoff="True",
            used_in_feature_sets="qc_cloud_deployable",
            handoff_note="computed from live pre-score candidate denominator and SECURITY_PROFILE_SOURCE",
        ),
        _row(
            feature="george_included",
            qc_status="non_deployable_george_evidence",
            deployability_class="george_bct_derived",
            safe_for_qc_handoff="False",
            used_in_feature_sets="",
            handoff_note="denied: George/OCR/video evidence is label provenance not a live scanner input",
        ),
    ]


def _write_inventory(path: Path, rows: list[dict[str, str]], *, schema: list[str] | None = None) -> None:
    fieldnames = schema or V.SCHEMA
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def _write_checklist(path: Path) -> None:
    path.write_text(
        "# Promotion Gate #432\n\n"
        "## Promotion Criteria\n\n"
        "## Feature Availability\n\n"
        "Use `feature_parity_columns.csv`.\n\n"
        "### QC Cloud-Ready\n\n"
        "### Denied\n",
        encoding="utf-8",
    )


def test_real_scanner_promotion_gate_validates() -> None:
    rows, checklist = V.validate()

    assert len(rows) >= 200
    assert "feature_parity_columns.csv" in checklist
    assert any(row["safe_for_qc_handoff"] == "True" for row in rows)
    assert any(row["qc_status"] == "non_deployable_george_evidence" for row in rows)


def test_minimal_gate_validates(tmp_path: Path) -> None:
    inventory = tmp_path / "inventory.csv"
    checklist = tmp_path / "promotion_gate.md"
    _write_inventory(inventory, _minimal_rows())
    _write_checklist(checklist)

    rows, _text = V.validate(inventory_path=inventory, checklist_path=checklist)

    assert len(rows) == 5


def test_schema_mismatch_fails(tmp_path: Path) -> None:
    inventory = tmp_path / "inventory.csv"
    _write_inventory(inventory, _minimal_rows(), schema=V.SCHEMA[:-1])

    with pytest.raises(V.PromotionGateValidationError, match="schema mismatch"):
        V.validate_inventory(inventory)


def test_george_evidence_must_be_explicitly_denied(tmp_path: Path) -> None:
    inventory = tmp_path / "inventory.csv"
    rows = _minimal_rows()
    rows[-1] = _row(
        feature="george_included",
        qc_status="non_deployable_george_evidence",
        deployability_class="",
        safe_for_qc_handoff="",
    )
    _write_inventory(inventory, rows)

    with pytest.raises(V.PromotionGateValidationError, match="George-derived evidence must be explicit False"):
        V.validate_inventory(inventory)


def test_safe_true_cannot_be_local_only(tmp_path: Path) -> None:
    inventory = tmp_path / "inventory.csv"
    rows = _minimal_rows()
    rows[2] = _row(
        feature="gap_pct_rank_in_panel",
        qc_status="blocked_local_massive_only",
        deployability_class="local_massive_only",
        safe_for_qc_handoff="True",
    )
    _write_inventory(inventory, rows)

    with pytest.raises(V.PromotionGateValidationError, match="safe=True requires qc_cloud_deployable"):
        V.validate_inventory(inventory)


def test_checklist_must_link_inventory(tmp_path: Path) -> None:
    checklist = tmp_path / "promotion_gate.md"
    checklist.write_text("# Promotion Gate #432\n", encoding="utf-8")

    with pytest.raises(V.PromotionGateValidationError, match="checklist missing"):
        V.validate_checklist(checklist)
