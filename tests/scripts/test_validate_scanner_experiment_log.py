from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

sys.path[:0] = [str(Path(__file__).resolve().parents[2] / "scripts")]

import validate_scanner_experiment_log as V


def _valid_row(**overrides: str) -> dict[str, str]:
    row = {field: "" for field in V.SCHEMA}
    row.update(
        {
            "experiment_id": "exp1",
            "issue": "#423",
            "experiment_type": "ranker",
            "hypothesis": "A ranker should improve topK recall.",
            "denominator": "test denominator",
            "label_set": "test labels",
            "feature_set": "test features",
            "model_type": "pairwise linear",
            "eval_protocol": "date-grouped OOF topK recall",
            "labels_total": "10",
            "labels_in_panel": "9",
            "recall_at_10": "4",
            "command": "python -m sweeps.archive.george_learned_ranker",
            "commit": "c5a34cc",
            "source": "unit test",
            "status": "complete",
            "verdict": "best_current",
        }
    )
    row.update(overrides)
    return row


def _write_ledger(path: Path, rows: list[dict[str, str]], *, schema: list[str] | None = None) -> None:
    fieldnames = schema or V.SCHEMA
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def test_real_scanner_experiment_log_validates() -> None:
    rows = V.validate(Path("research/scanner-alignment/experiment_log.csv"))
    assert len(rows) >= 10
    assert any(row["verdict"] == "best_current" for row in rows)


def test_schema_mismatch_fails(tmp_path: Path) -> None:
    path = tmp_path / "bad.csv"
    _write_ledger(path, [_valid_row()], schema=V.SCHEMA[:-1])

    with pytest.raises(V.LedgerValidationError, match="schema mismatch"):
        V.validate(path)


def test_extra_row_cells_fail(tmp_path: Path) -> None:
    path = tmp_path / "extra-cell.csv"
    path.write_text(",".join(V.SCHEMA) + "\n" + ",".join(_valid_row().values()) + ",extra\n")

    with pytest.raises(V.LedgerValidationError, match="more cells than schema"):
        V.validate(path)


def test_duplicate_experiment_id_fails(tmp_path: Path) -> None:
    path = tmp_path / "dupe.csv"
    _write_ledger(path, [_valid_row(), _valid_row()])

    with pytest.raises(V.LedgerValidationError, match="duplicate experiment_id"):
        V.validate(path)


def test_completed_ranker_requires_command(tmp_path: Path) -> None:
    path = tmp_path / "missing-command.csv"
    _write_ledger(path, [_valid_row(command="")])

    with pytest.raises(V.LedgerValidationError, match="needs command"):
        V.validate(path)


def test_numeric_fields_must_parse(tmp_path: Path) -> None:
    path = tmp_path / "bad-number.csv"
    _write_ledger(path, [_valid_row(recall_at_10="four")])

    with pytest.raises(V.LedgerValidationError, match="recall_at_10 must be an integer"):
        V.validate(path)


def test_recall_cannot_exceed_labels_total(tmp_path: Path) -> None:
    path = tmp_path / "bad-recall.csv"
    _write_ledger(path, [_valid_row(labels_total="10", recall_at_10="11")])

    with pytest.raises(V.LedgerValidationError, match="recall_at_10 exceeds labels_total"):
        V.validate(path)
