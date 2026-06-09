from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from aggregate_416_george_context_reports import aggregate_reports  # noqa: E402


def _write_summary(path: Path, rows: list[dict[str, str]]) -> None:
    path.mkdir(parents=True, exist_ok=True)
    columns = [
        "variant_id",
        "family",
        "wave",
        "hypothesis",
        "sweep_config_hash",
        "window",
        "ok",
        "sharpe",
        "ret_pct",
        "dd_pct",
        "orders",
        "run_dir",
        "result_path",
        "error",
    ]
    with (path / "summary.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def test_aggregate_reports_ranks_and_dedupes_retry_success(tmp_path: Path) -> None:
    wave = tmp_path / "wave"
    retry = tmp_path / "retry"
    output = tmp_path / "aggregate"
    _write_summary(
        wave,
        [
            {
                "variant_id": "slow",
                "family": "mfe_target",
                "wave": "1",
                "hypothesis": "failed under pressure",
                "sweep_config_hash": "aaa",
                "window": "fy2025_full",
                "ok": "False",
                "sharpe": "0",
                "ret_pct": "0",
                "dd_pct": "0",
                "orders": "0",
                "run_dir": "run/slow",
                "result_path": "",
                "error": "timeout",
            },
            {
                "variant_id": "winner",
                "family": "mfe_target",
                "wave": "1",
                "hypothesis": "good",
                "sweep_config_hash": "bbb",
                "window": "fy2025_full",
                "ok": "True",
                "sharpe": "1.2",
                "ret_pct": "12.5",
                "dd_pct": "8.0",
                "orders": "10",
                "run_dir": "run/winner",
                "result_path": "winner.json",
                "error": "",
            },
        ],
    )
    _write_summary(
        retry,
        [
            {
                "variant_id": "slow",
                "family": "mfe_target",
                "wave": "1",
                "hypothesis": "retry success",
                "sweep_config_hash": "aaa",
                "window": "fy2025_full",
                "ok": "True",
                "sharpe": "0.7",
                "ret_pct": "7.0",
                "dd_pct": "9.0",
                "orders": "9",
                "run_dir": "run/slow-retry",
                "result_path": "slow.json",
                "error": "",
            }
        ],
    )

    rows = aggregate_reports([wave, retry], output)

    assert [row["variant_id"] for row in rows] == ["winner", "slow"]
    assert rows[1]["ok"] == "True"
    assert rows[1]["source_report"] == "retry"
    assert (output / "summary.csv").exists()
    assert (output / "family_summary.csv").exists()
