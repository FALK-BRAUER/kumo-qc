"""#10 storage-uniformity — sweep index (bt-results format) + the main-side merge dedup.

ZERO real BT: hand-built LedgerRows + a tmp bt-results.csv. Asserts the column mapping (blanks for
unmeasured, never faked), the canonical header, and idempotent dedup-append.
"""
from __future__ import annotations

import csv
import io
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(_ROOT), str(_ROOT / "scripts")]

from sweeps.provenance import LedgerRow  # noqa: E402
from sweeps.sweep_index import BT_RESULTS_COLUMNS, sweep_index_rows, to_index_csv  # noqa: E402
from sweeps.types import Window  # noqa: E402

WINDOWS = {
    "w1": Window(name="w1", start="2025-01-01", end="2025-02-28"),
    "fy2025": Window(name="fy2025", start="2025-01-01", end="2025-12-31"),
}


def _ledger() -> list[LedgerRow]:
    return [
        LedgerRow(config_hash="abc123", data_fingerprint="fp", commit="deadbeef", bt_id="111",
                  marker="m", sharpe=1.2, ret_pct=12.5, dd_pct=8.0, orders=20, window="w1", verdict="OK"),
        LedgerRow(config_hash="abc123", data_fingerprint="fp", commit="deadbeef", bt_id="222",
                  marker="m", sharpe=0.5, ret_pct=3.1, dd_pct=9.4, orders=15, window="fy2025", verdict="OK"),
    ]


def test_rows_map_to_bt_results_columns_blanks_not_faked() -> None:
    rows = sweep_index_rows(_ledger(), windows=WINDOWS, branch="feat/x", env="local",
                            grid="dvrank", date_run="2026-06-02T00:00:00+00:00")
    r = rows[0]
    assert r["window"] == "w1" and r["period_start"] == "2025-01-01" and r["period_end"] == "2025-02-28"
    assert r["commit"] == "deadbeef" and r["branch"] == "feat/x" and r["environment"] == "local"
    assert r["sharpe"] == "1.200" and r["net_profit_pct"] == "12.500" and r["max_drawdown_pct"] == "8.000"
    assert r["total_orders"] == "20"
    # unmeasured-by-sweep columns are BLANK (never faked)
    assert r["net_profit_usd"] == "" and r["win_rate_pct"] == "" and r["total_fees_usd"] == ""
    assert "config=abc123" in r["notes"] and "bt=111" in r["notes"] and "dvrank" in r["notes"]


def test_index_csv_header_is_canonical() -> None:
    rows = sweep_index_rows(_ledger(), windows=WINDOWS, branch="b", env="local", grid="g",
                            date_run="t")
    csv_text = to_index_csv(rows)
    header = csv_text.splitlines()[0]
    assert header == ",".join(BT_RESULTS_COLUMNS)  # exact match → mergeable into bt-results.csv
    assert len(csv_text.strip().splitlines()) == 3  # header + 2 rows


def test_merge_is_idempotent_dedup(tmp_path: Path) -> None:
    from merge_sweep_index import merge  # noqa: E402

    # a bt-results.csv with the canonical header + one pre-existing row (same key as a sweep row).
    bt = tmp_path / "bt-results.csv"
    with bt.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(BT_RESULTS_COLUMNS))
        w.writeheader()
        w.writerow({c: "" for c in BT_RESULTS_COLUMNS} | {
            "commit": "deadbeef", "window": "w1", "notes": "sweep cell [dvrank] config=abc123 bt=111"})

    idx = tmp_path / "sweep_index.csv"
    idx.write_text(to_index_csv(sweep_index_rows(_ledger(), windows=WINDOWS, branch="b",
                                                 env="local", grid="dvrank", date_run="t")))

    # first merge: w1 row is a dup (skip), fy2025 row is new (append) → +1
    added = merge([idx], bt_results=bt)
    assert added == 1
    # second merge: everything now present → +0 (idempotent)
    assert merge([idx], bt_results=bt) == 0
    # bt-results has header + 1 original + 1 appended = 3 lines
    assert len(bt.read_text().strip().splitlines()) == 3
