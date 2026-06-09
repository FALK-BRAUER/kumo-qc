#!/usr/bin/env python3
"""Validate the BCT/George scanner-alignment experiment ledger."""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path
from typing import Iterable


DEFAULT_LEDGER = Path("research/scanner-alignment/experiment_log.csv")

SCHEMA = [
    "experiment_id",
    "issue",
    "experiment_type",
    "hypothesis",
    "denominator",
    "label_set",
    "feature_set",
    "model_type",
    "eval_protocol",
    "candidate_rows",
    "covered_dates",
    "median_rows_per_day",
    "labels_total",
    "labels_in_panel",
    "labels_selected",
    "recall_at_5",
    "recall_at_10",
    "recall_at_20",
    "recall_at_50",
    "recall_at_100",
    "recall_at_200",
    "precision_pct",
    "lift",
    "command",
    "commit",
    "source",
    "status",
    "verdict",
    "notes",
]

ALLOWED_TYPES = {
    "coverage",
    "filter",
    "ranker",
    "confirmation",
    "diagnostic",
}
ALLOWED_STATUSES = {"planned", "complete", "blocked"}
ALLOWED_VERDICTS = {
    "best_current",
    "confirmation_layer",
    "coverage_blocker",
    "diagnostic",
    "not_promoted",
    "rejected_for_runtime",
    "rejected_for_selector",
    "useful_not_promoted",
}
INT_FIELDS = {
    "candidate_rows",
    "covered_dates",
    "labels_total",
    "labels_in_panel",
    "labels_selected",
    "recall_at_5",
    "recall_at_10",
    "recall_at_20",
    "recall_at_50",
    "recall_at_100",
    "recall_at_200",
}
FLOAT_FIELDS = {"median_rows_per_day", "precision_pct", "lift"}
REQUIRED_TEXT_FIELDS = {
    "experiment_id",
    "issue",
    "experiment_type",
    "hypothesis",
    "denominator",
    "label_set",
    "feature_set",
    "model_type",
    "eval_protocol",
    "status",
    "verdict",
}
COMMIT_RE = re.compile(r"^[0-9a-f]{7,40}$")


class LedgerValidationError(ValueError):
    """Raised when the scanner experiment ledger violates the schema or row contract."""


def _parse_int(value: str, *, field: str, row_id: str) -> None:
    if value == "":
        return
    try:
        parsed = int(value)
    except ValueError as exc:
        raise LedgerValidationError(f"{row_id}: {field} must be an integer or blank") from exc
    if parsed < 0:
        raise LedgerValidationError(f"{row_id}: {field} must be non-negative")


def _parse_float(value: str, *, field: str, row_id: str) -> None:
    if value == "":
        return
    try:
        parsed = float(value)
    except ValueError as exc:
        raise LedgerValidationError(f"{row_id}: {field} must be numeric or blank") from exc
    if parsed < 0.0:
        raise LedgerValidationError(f"{row_id}: {field} must be non-negative")


def _require_fields(row: dict[str, str], fields: Iterable[str], *, row_id: str) -> None:
    missing = [field for field in fields if not row.get(field, "").strip()]
    if missing:
        raise LedgerValidationError(f"{row_id}: missing required fields {missing}")


def validate(path: Path = DEFAULT_LEDGER) -> list[dict[str, str]]:
    """Return validated ledger rows or raise `LedgerValidationError`."""
    if not path.exists():
        raise LedgerValidationError(f"ledger not found: {path}")

    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames != SCHEMA:
            raise LedgerValidationError(
                f"schema mismatch: expected {SCHEMA}, got {reader.fieldnames}"
            )
        rows = list(reader)

    if not rows:
        raise LedgerValidationError("ledger has no experiment rows")

    seen: set[str] = set()
    for i, row in enumerate(rows, start=2):
        row_id = row.get("experiment_id", "").strip() or f"line {i}"
        if None in row:
            raise LedgerValidationError(f"{row_id}: row has more cells than schema")
        if row_id in seen:
            raise LedgerValidationError(f"{row_id}: duplicate experiment_id")
        seen.add(row_id)

        _require_fields(row, REQUIRED_TEXT_FIELDS, row_id=row_id)

        if row["experiment_type"] not in ALLOWED_TYPES:
            raise LedgerValidationError(f"{row_id}: unsupported experiment_type {row['experiment_type']}")
        if row["status"] not in ALLOWED_STATUSES:
            raise LedgerValidationError(f"{row_id}: unsupported status {row['status']}")
        if row["verdict"] not in ALLOWED_VERDICTS:
            raise LedgerValidationError(f"{row_id}: unsupported verdict {row['verdict']}")

        if row["status"] == "complete":
            _require_fields(row, ("commit", "source"), row_id=row_id)
            if not row["command"] and row["experiment_type"] in {"ranker", "confirmation", "diagnostic"}:
                raise LedgerValidationError(f"{row_id}: completed {row['experiment_type']} row needs command")
            if not COMMIT_RE.match(row["commit"]):
                raise LedgerValidationError(f"{row_id}: commit must be a short or full hex sha")

        for field in INT_FIELDS:
            _parse_int(row[field], field=field, row_id=row_id)
        for field in FLOAT_FIELDS:
            _parse_float(row[field], field=field, row_id=row_id)

        labels_total = row["labels_total"]
        if labels_total:
            total = int(labels_total)
            for field in {"labels_in_panel", "labels_selected"} | INT_FIELDS:
                value = row.get(field, "")
                if value and field != "candidate_rows" and int(value) > total and field.startswith(("labels", "recall")):
                    raise LedgerValidationError(f"{row_id}: {field} exceeds labels_total")

    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", type=Path, default=DEFAULT_LEDGER)
    args = parser.parse_args(argv)

    try:
        rows = validate(args.path)
    except LedgerValidationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"OK: {len(rows)} scanner experiment rows validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
