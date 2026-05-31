"""Provenance + ledger tests (#214 component 7) — pinning + round-trip."""
from __future__ import annotations

from pathlib import Path

import pytest

from sweeps.provenance import (
    LEDGER_COLUMNS,
    LedgerRow,
    Provenance,
    from_csv,
    git_commit,
    ledger_rows,
    read_ledger,
    to_csv,
    write_ledger,
)
from sweeps.types import ConfigRun, PhaseChoice, ResultMetrics, SweepConfig, Window, WindowResult
from sweeps.windows import SIX_WINDOWS


def _run() -> ConfigRun:
    cfg = SweepConfig(choices=(PhaseChoice("signal", "Mock", (("a", 1),), 1),))
    wrs = tuple(
        WindowResult(
            window=w,
            metrics=ResultMetrics(sharpe=1.0 + i, ret_pct=10.0 + i, dd_pct=5.0 + i, orders=i),
        )
        for i, w in enumerate(SIX_WINDOWS)
    )
    return ConfigRun(config=cfg, window_results=wrs)


def _prov(run: ConfigRun) -> Provenance:
    return Provenance(
        commit="deadbeef",
        config_hash=run.config.config_hash,
        data_fingerprint="fp123",
        marker="mock-v1",
    )


def test_provenance_validate_requires_full_triple() -> None:
    Provenance(commit="c", config_hash="h", data_fingerprint="f", marker="m").validate()
    with pytest.raises(ValueError, match="incomplete provenance"):
        Provenance(commit="", config_hash="h", data_fingerprint="f", marker="m").validate()
    with pytest.raises(ValueError, match="incomplete provenance"):
        Provenance(commit="c", config_hash="h", data_fingerprint="", marker="m").validate()


def test_ledger_rows_one_per_window_fully_pinned() -> None:
    run = _run()
    rows = ledger_rows(run, _prov(run), bt_id="sweep001")
    assert len(rows) == 6
    for r in rows:
        assert r.config_hash == run.config.config_hash
        assert r.data_fingerprint == "fp123"
        assert r.commit == "deadbeef"
        assert r.marker == "mock-v1"
        assert r.bt_id.startswith("sweep001:")
        assert r.verdict == "sweep"


def test_ledger_rows_reject_config_hash_mismatch() -> None:
    run = _run()
    bad = Provenance(commit="c", config_hash="WRONG", data_fingerprint="f", marker="m")
    with pytest.raises(ValueError, match="stamped against the wrong config"):
        ledger_rows(run, bad, bt_id="s")


def test_csv_schema_matches_canonical_columns() -> None:
    # results/README mandates this exact schema.
    expected = (
        "config_hash",
        "data_fingerprint",
        "commit",
        "bt_id",
        "marker",
        "sharpe",
        "ret_pct",
        "dd_pct",
        "orders",
        "window",
        "verdict",
    )
    assert LEDGER_COLUMNS == expected
    run = _run()
    csv_text = to_csv(ledger_rows(run, _prov(run), bt_id="s"))
    assert csv_text.splitlines()[0] == ",".join(expected)


def test_ledger_round_trip_identical() -> None:
    run = _run()
    rows = ledger_rows(run, _prov(run), bt_id="s")
    parsed = from_csv(to_csv(rows))
    assert parsed == rows


def test_write_read_file_round_trip(tmp_path: Path) -> None:
    run = _run()
    rows = ledger_rows(run, _prov(run), bt_id="s")
    path = tmp_path / "ledger.csv"
    write_ledger(path, rows)
    assert read_ledger(path) == rows


def test_write_append_grows_without_duplicate_header(tmp_path: Path) -> None:
    run = _run()
    rows = ledger_rows(run, _prov(run), bt_id="s")
    path = tmp_path / "ledger.csv"
    write_ledger(path, rows, append=True)  # creates with header
    write_ledger(path, rows, append=True)  # appends, no second header
    text = path.read_text(encoding="utf-8")
    assert text.count("config_hash,data_fingerprint") == 1  # header once
    assert len(read_ledger(path)) == 12  # 6 + 6


def test_git_commit_returns_sha() -> None:
    # Real git call against the worktree — returns a 40-char hex sha (no backtest involved).
    sha = git_commit(Path(__file__).resolve().parents[2])
    assert len(sha) == 40
    int(sha, 16)  # valid hex
