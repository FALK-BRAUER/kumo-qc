#!/usr/bin/env python3
"""Audit BCT/George scanner feature parity between kumo-lab and kumo-qc."""
from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
for path in (REPO_ROOT, REPO_ROOT / "src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from sweeps.archive import george_learned_ranker as learned_ranker  # noqa: E402


COMPARE_DIR = Path("/Users/falk/projects/kumo-lab/data/bluecloudtrading/scanner_compare")
DEFAULT_DENOMINATOR = COMPARE_DIR / "george_ranking_denominator_profiled.csv"
DEFAULT_INVENTORY = COMPARE_DIR / "george_top10_feature_deployability_inventory.csv"
DEFAULT_IMPORTANCES = COMPARE_DIR / "george_top10_feature_rich_importances.csv"
DEFAULT_VARIANTS = COMPARE_DIR / "george_top10_feature_rich_variant_summary.csv"
DEFAULT_OUTPUT_MD = Path("research/scanner-alignment/feature_parity_audit.md")
DEFAULT_OUTPUT_CSV = Path("research/scanner-alignment/feature_parity_columns.csv")

NON_DEPLOYABLE_CLASSES = {"offline_research_only", "george_bct_derived"}
BLOCKED_CLASSES = {"local_massive_only", "tc2000_mapping_required"}
DENY_HANDOFF_NOTE = {
    "non_deployable_george_evidence": "denied: George/OCR/video evidence is label provenance, not a live scanner input",
    "non_deployable_model_score": "denied: offline model score would leak out-of-fold or in-sample research state",
    "non_deployable_research_only": "denied: research-only feature needs a clean runtime source before handoff",
}
DENY_DEPLOYABILITY_CLASS = {
    "non_deployable_george_evidence": "george_bct_derived",
    "non_deployable_model_score": "offline_research_only",
    "non_deployable_research_only": "offline_research_only",
}
LEAKAGE_TOKENS = (
    "george",
    "ocr",
    "source",
    "post_id",
    "_path",
    "decision_label",
    "scanner_rank",
    "is_george",
    "forced",
    "pct_change_text",
    "attention",
    "video",
    "transcript",
)
OFFLINE_MODEL_TOKENS = (
    "oof_",
    "in_sample_model",
    "base_model_score",
    "scanner_time_",
)


def _read_header(path: Path) -> list[str]:
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        return next(reader)


def _read_inventory(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as fh:
        return {row["feature"]: row for row in csv.DictReader(fh)}


def _read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def qc_matrix_features() -> set[str]:
    """Features that can enter the current QC learned-ranker feature matrix."""
    return set(
        learned_ranker.NUMERIC_FEATURES
        + learned_ranker.BOOLEAN_FEATURES
        + learned_ranker.SECTOR_NUMERIC_FEATURES
        + learned_ranker.SECTOR_BOOLEAN_FEATURES
        + learned_ranker.FIRST_HOUR_NUMERIC_FEATURES
        + learned_ranker.FIRST_HOUR_BOOLEAN_FEATURES
    )


def classify_feature(feature: str, *, inventory_class: str = "", qc_features: set[str] | None = None) -> str:
    """Classify a lab feature from the perspective of QC scanner handoff."""
    qc_features = qc_features or set()
    lowered = feature.lower()
    if any(token in lowered for token in OFFLINE_MODEL_TOKENS):
        return "non_deployable_model_score"
    if any(token in lowered for token in LEAKAGE_TOKENS):
        return "non_deployable_george_evidence"
    if feature in qc_features:
        return "qc_ranker_feature"
    if inventory_class in NON_DEPLOYABLE_CLASSES:
        return "non_deployable_research_only"
    if inventory_class == "tc2000_mapping_required":
        return "blocked_tc2000_mapping"
    if inventory_class == "local_massive_only":
        return "blocked_local_massive_only"
    if inventory_class == "qc_cloud_deployable":
        return "clean_available_not_used"
    return "unclassified_or_unused"


def handoff_fields(
    *,
    qc_status: str,
    deployability_class: str,
    safe_for_qc_handoff: str,
    handoff_note: str,
) -> tuple[str, str, str]:
    """Normalize explicit deny metadata for generated feature-parity inventories."""
    if qc_status in DENY_HANDOFF_NOTE:
        return (
            deployability_class or DENY_DEPLOYABILITY_CLASS[qc_status],
            safe_for_qc_handoff or "False",
            handoff_note or DENY_HANDOFF_NOTE[qc_status],
        )
    return deployability_class, safe_for_qc_handoff, handoff_note


def build_column_inventory(
    denominator_columns: Iterable[str],
    *,
    inventory: dict[str, dict[str, str]],
) -> list[dict[str, str]]:
    """Return one audit row per denominator column."""
    qc_features = qc_matrix_features()
    rows: list[dict[str, str]] = []
    for feature in denominator_columns:
        inv = inventory.get(feature, {})
        deployability_class = inv.get("deployability_class", "")
        qc_status = classify_feature(feature, inventory_class=deployability_class, qc_features=qc_features)
        deployability_class, safe_for_qc_handoff, handoff_note = handoff_fields(
            qc_status=qc_status,
            deployability_class=deployability_class,
            safe_for_qc_handoff=inv.get("safe_for_qc_handoff", ""),
            handoff_note=inv.get("handoff_note", ""),
        )
        rows.append(
            {
                "feature": feature,
                "qc_status": qc_status,
                "deployability_class": deployability_class,
                "safe_for_qc_handoff": safe_for_qc_handoff,
                "used_in_feature_sets": inv.get("used_in_feature_sets", ""),
                "handoff_note": handoff_note,
            }
        )
    return rows


def _variant_line(rows: list[dict[str, str]], variant: str) -> str:
    for row in rows:
        if row.get("variant") == variant:
            return f"{row.get('recall10_pct', '')}% recall@10, {row.get('precision10_pct', '')}% precision@10"
    return "not available"


def _markdown_table(rows: list[dict[str, str]], columns: list[str], *, limit: int | None = None) -> str:
    subset = rows[:limit] if limit is not None else rows
    if not subset:
        return "_none_"
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for row in subset:
        lines.append("| " + " | ".join(str(row.get(col, "")).replace("|", "/") for col in columns) + " |")
    return "\n".join(lines)


def write_outputs(
    *,
    denominator_path: Path,
    inventory_path: Path,
    importances_path: Path,
    variants_path: Path,
    output_md: Path,
    output_csv: Path,
) -> tuple[list[dict[str, str]], str]:
    """Build feature parity inventory and write CSV plus Markdown report."""
    denominator_columns = _read_header(denominator_path)
    inventory = _read_inventory(inventory_path)
    column_rows = build_column_inventory(denominator_columns, inventory=inventory)
    status_counts = Counter(row["qc_status"] for row in column_rows)

    importances = _read_rows(importances_path)
    importance_rows: list[dict[str, str]] = []
    for row in importances:
        feature = row.get("feature", "")
        inv = inventory.get(feature, {})
        importance_rows.append(
            {
                "feature": feature,
                "importance": row.get("importance", ""),
                "qc_status": classify_feature(
                    feature,
                    inventory_class=inv.get("deployability_class", ""),
                    qc_features=qc_matrix_features(),
                ),
                "deployability_class": inv.get("deployability_class", ""),
            }
        )
    top25 = importance_rows[:25]
    top25_counts = Counter(row["qc_status"] for row in top25)
    variants = _read_rows(variants_path)

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", newline="", encoding="utf-8") as fh:
        fieldnames = [
            "feature",
            "qc_status",
            "deployability_class",
            "safe_for_qc_handoff",
            "used_in_feature_sets",
            "handoff_note",
        ]
        writer = csv.DictWriter(fh, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(column_rows)

    clean_unused = [
        row for row in column_rows if row["qc_status"] == "clean_available_not_used"
    ][:20]
    blocked = [
        row for row in column_rows if row["qc_status"] in {"blocked_tc2000_mapping", "blocked_local_massive_only"}
    ][:20]
    non_deployable_top = [
        row for row in top25 if row["qc_status"].startswith("non_deployable") or row["qc_status"].startswith("blocked")
    ]

    report = [
        "# Scanner Feature-Parity Audit",
        "",
        "Purpose: separate real QC-deployable scanner features from lab-only or George-derived lift before tuning another ranker.",
        "",
        "## Inputs",
        "",
        f"- denominator: `{denominator_path}`",
        f"- deployability inventory: `{inventory_path}`",
        f"- lab feature-rich importances: `{importances_path}`",
        f"- lab feature-rich variants: `{variants_path}`",
        "",
        "## Summary",
        "",
        f"- denominator columns: {len(denominator_columns)}",
        f"- current QC learned-ranker matrix features: {len(qc_matrix_features())}",
        f"- lab feature-rich date-grouped CV: {_variant_line(variants, 'feature_rich_gbm_date_grouped_cv')}",
        f"- lab stage-1 baseline: {_variant_line(variants, 'stage1_kijun_baseline')}",
        f"- top-25 lab importance statuses: {dict(sorted(top25_counts.items()))}",
        "",
        "## Denominator Column Status Counts",
        "",
        _markdown_table(
            [{"qc_status": key, "count": str(value)} for key, value in sorted(status_counts.items())],
            ["qc_status", "count"],
        ),
        "",
        "## Top Lab Importances That Are Not Clean QC Runtime Features",
        "",
        _markdown_table(non_deployable_top, ["feature", "importance", "qc_status", "deployability_class"]),
        "",
        "## Clean Deployable Columns Not Yet In The QC Ranker Matrix",
        "",
        _markdown_table(clean_unused, ["feature", "deployability_class", "handoff_note"]),
        "",
        "## Blocked Local Or TC2000-Dependent Columns",
        "",
        _markdown_table(blocked, ["feature", "qc_status", "deployability_class", "handoff_note"]),
        "",
        "## Read",
        "",
        "- The QC ranker already consumes the main clean daily/weekly structure family.",
        "- More clean QC columns alone are unlikely to explain the lab lift; the lab feature-rich top importances include offline OOF model scores and local/panel-relative ranks.",
        "- The next deployable gap is not another blind model class. It is TC2000-compatible sector/industry breadth plus a clean way to reproduce live denominator-relative ranks.",
    ]
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text("\n".join(report) + "\n", encoding="utf-8")
    return column_rows, str(output_md)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--denominator-csv", type=Path, default=DEFAULT_DENOMINATOR)
    parser.add_argument("--inventory-csv", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--importances-csv", type=Path, default=DEFAULT_IMPORTANCES)
    parser.add_argument("--variants-csv", type=Path, default=DEFAULT_VARIANTS)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_OUTPUT_MD)
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_OUTPUT_CSV)
    args = parser.parse_args(argv)

    rows, report = write_outputs(
        denominator_path=args.denominator_csv,
        inventory_path=args.inventory_csv,
        importances_path=args.importances_csv,
        variants_path=args.variants_csv,
        output_md=args.output_md,
        output_csv=args.output_csv,
    )
    counts = Counter(row["qc_status"] for row in rows)
    print(f"OK: {len(rows)} denominator columns audited")
    print(dict(sorted(counts.items())))
    print(f"report={report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
