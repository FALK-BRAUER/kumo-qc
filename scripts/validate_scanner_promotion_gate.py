#!/usr/bin/env python3
"""Validate the BCT/George scanner runtime-promotion gate."""
from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path


DEFAULT_INVENTORY = Path("research/scanner-alignment/feature_parity_columns.csv")
DEFAULT_CHECKLIST = Path("research/scanner-alignment/promotion_gate.md")

SCHEMA = [
    "feature",
    "qc_status",
    "deployability_class",
    "safe_for_qc_handoff",
    "used_in_feature_sets",
    "handoff_note",
]

ALLOWED_QC_STATUSES = {
    "blocked_local_massive_only",
    "blocked_tc2000_mapping",
    "clean_available_not_used",
    "non_deployable_george_evidence",
    "non_deployable_model_score",
    "non_deployable_research_only",
    "qc_ranker_feature",
    "unclassified_or_unused",
}
ALLOWED_DEPLOYABILITY_CLASSES = {
    "",
    "george_bct_derived",
    "local_massive_only",
    "offline_research_only",
    "qc_cloud_deployable",
    "tc2000_mapping_required",
}
SAFE_VALUES = {"", "False", "True"}
QC_CLOUD_READY_STATUSES = {"clean_available_not_used", "qc_ranker_feature"}
DENY_STATUSES = {
    "blocked_local_massive_only",
    "blocked_tc2000_mapping",
    "non_deployable_george_evidence",
    "non_deployable_model_score",
    "non_deployable_research_only",
}
GEORGE_EVIDENCE_TOKENS = (
    "george",
    "ocr",
    "post_id",
    "candidate_source",
    "decision_label",
    "forced",
    "pct_change_text",
    "scanner_rank",
    "source_",
)
LOCAL_DENOMINATOR_RANK_TOKENS = ("rank_in_panel", "rank_price10")


class PromotionGateValidationError(ValueError):
    """Raised when scanner promotion-gate artifacts are ambiguous or unsafe."""


def _read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise PromotionGateValidationError(f"inventory not found: {path}")
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames != SCHEMA:
            raise PromotionGateValidationError(
                f"schema mismatch: expected {SCHEMA}, got {reader.fieldnames}"
            )
        rows = list(reader)
    if not rows:
        raise PromotionGateValidationError("inventory has no feature rows")
    return rows


def _is_george_evidence_feature(feature: str) -> bool:
    lowered = feature.lower()
    return any(token in lowered for token in GEORGE_EVIDENCE_TOKENS)


def _is_local_denominator_rank(feature: str) -> bool:
    lowered = feature.lower()
    return any(token in lowered for token in LOCAL_DENOMINATOR_RANK_TOKENS)


def validate_inventory(path: Path = DEFAULT_INVENTORY) -> list[dict[str, str]]:
    """Return validated feature-promotion inventory rows."""
    rows = _read_rows(path)
    seen: set[str] = set()
    counts: Counter[str] = Counter()

    for i, row in enumerate(rows, start=2):
        if None in row:
            raise PromotionGateValidationError(f"line {i}: row has more cells than schema")

        feature = row["feature"].strip()
        status = row["qc_status"].strip()
        deployability_class = row["deployability_class"].strip()
        safe = row["safe_for_qc_handoff"].strip()
        note = row["handoff_note"].strip()

        row_id = feature or f"line {i}"
        if not feature:
            raise PromotionGateValidationError(f"{row_id}: missing feature")
        if feature in seen:
            raise PromotionGateValidationError(f"{row_id}: duplicate feature")
        seen.add(feature)

        if status not in ALLOWED_QC_STATUSES:
            raise PromotionGateValidationError(f"{row_id}: unsupported qc_status {status}")
        if deployability_class not in ALLOWED_DEPLOYABILITY_CLASSES:
            raise PromotionGateValidationError(
                f"{row_id}: unsupported deployability_class {deployability_class}"
            )
        if safe not in SAFE_VALUES:
            raise PromotionGateValidationError(f"{row_id}: safe_for_qc_handoff must be True, False, or blank")

        counts[status] += 1
        if safe == "True":
            if deployability_class != "qc_cloud_deployable":
                raise PromotionGateValidationError(f"{row_id}: safe=True requires qc_cloud_deployable")
            if status not in QC_CLOUD_READY_STATUSES:
                raise PromotionGateValidationError(f"{row_id}: safe=True is incompatible with {status}")
            if not note:
                raise PromotionGateValidationError(f"{row_id}: safe=True needs a handoff_note")

        if status == "clean_available_not_used":
            if deployability_class != "qc_cloud_deployable" or safe != "True":
                raise PromotionGateValidationError(f"{row_id}: clean available columns must be QC-cloud safe")

        if status == "blocked_local_massive_only":
            if deployability_class != "local_massive_only" or safe != "False":
                raise PromotionGateValidationError(f"{row_id}: local Massive blockers must be explicit False")
            if not note:
                raise PromotionGateValidationError(f"{row_id}: local Massive blockers need a handoff_note")

        if status == "blocked_tc2000_mapping":
            if deployability_class != "tc2000_mapping_required" or safe != "False":
                raise PromotionGateValidationError(f"{row_id}: TC2000 blockers must be explicit False")
            if not note:
                raise PromotionGateValidationError(f"{row_id}: TC2000 blockers need a handoff_note")

        if status == "non_deployable_george_evidence":
            if deployability_class != "george_bct_derived" or safe != "False":
                raise PromotionGateValidationError(f"{row_id}: George-derived evidence must be explicit False")
            if not note:
                raise PromotionGateValidationError(f"{row_id}: George-derived evidence needs a handoff_note")

        if status in {"non_deployable_model_score", "non_deployable_research_only"}:
            if deployability_class != "offline_research_only" or safe != "False":
                raise PromotionGateValidationError(f"{row_id}: offline research columns must be explicit False")
            if not note:
                raise PromotionGateValidationError(f"{row_id}: offline research columns need a handoff_note")

        if _is_george_evidence_feature(feature) and status != "non_deployable_george_evidence":
            raise PromotionGateValidationError(f"{row_id}: George/OCR/source feature must be denied")
        if _is_local_denominator_rank(feature) and safe != "False":
            raise PromotionGateValidationError(f"{row_id}: denominator-rank feature must not be QC-cloud safe")

    required_statuses = {
        "blocked_local_massive_only",
        "blocked_tc2000_mapping",
        "clean_available_not_used",
        "non_deployable_george_evidence",
        "qc_ranker_feature",
    }
    missing_statuses = sorted(status for status in required_statuses if counts[status] == 0)
    if missing_statuses:
        raise PromotionGateValidationError(f"inventory missing required categories {missing_statuses}")

    if not any(row["safe_for_qc_handoff"].strip() == "True" for row in rows):
        raise PromotionGateValidationError("inventory has no QC-cloud-ready columns")

    return rows


def validate_checklist(path: Path = DEFAULT_CHECKLIST) -> str:
    """Return the checklist text if it contains the required promotion-gate anchors."""
    if not path.exists():
        raise PromotionGateValidationError(f"checklist not found: {path}")
    text = path.read_text(encoding="utf-8")
    required_fragments = [
        "#432",
        "Promotion Criteria",
        "Feature Availability",
        "feature_parity_columns.csv",
        "QC Cloud-Ready",
        "Denied",
    ]
    missing = [fragment for fragment in required_fragments if fragment not in text]
    if missing:
        raise PromotionGateValidationError(f"checklist missing required fragments {missing}")
    return text


def validate(
    *,
    inventory_path: Path = DEFAULT_INVENTORY,
    checklist_path: Path = DEFAULT_CHECKLIST,
) -> tuple[list[dict[str, str]], str]:
    """Validate all scanner promotion-gate artifacts."""
    rows = validate_inventory(inventory_path)
    checklist = validate_checklist(checklist_path)
    return rows, checklist


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", default=DEFAULT_INVENTORY, type=Path)
    parser.add_argument("--checklist", default=DEFAULT_CHECKLIST, type=Path)
    args = parser.parse_args(argv)

    try:
        rows, _checklist = validate(inventory_path=args.inventory, checklist_path=args.checklist)
    except PromotionGateValidationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    safe_count = sum(1 for row in rows if row["safe_for_qc_handoff"].strip() == "True")
    denied_count = sum(1 for row in rows if row["qc_status"].strip() in DENY_STATUSES)
    print(f"OK: {len(rows)} scanner promotion rows validated ({safe_count} safe, {denied_count} denied)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
