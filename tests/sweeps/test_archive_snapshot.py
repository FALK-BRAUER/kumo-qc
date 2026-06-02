"""Tests for the results-archive snapshotter (sweeps/archive/snapshot.py, #276b).

ZERO real QC / LEAN: the `/orders/read` fetch and the write-destination are INJECTED. Every test
builds a fixture order list (entry+exit fills, with a urlencoded entry tag) and a tmp_path dest,
asserts the durable artifact, and exercises the fail-loud + 3-state + atomic + idempotent contract.
"""
from __future__ import annotations

import gzip
import json
import os
from pathlib import Path
from urllib.parse import urlencode

import pytest

from datetime import datetime, timezone

from sweeps.archive import (
    ArchiveError,
    CENSORED_EXIT_REASON,
    EmptyTradesError,
    M2M_LOCAL_PARQUET,
    M2M_QC_NATIVE,
    M2M_UNAVAILABLE,
    OrdersFetchError,
    RunStatus,
    SchemaValidationError,
    TRADE_SCHEMA_VERSION,
    persist_run,
)
from sweeps.archive.snapshot import _validate_trade_row

# --------------------------------------------------------------------------- #
# Fixtures — the cloud /orders/read shape (mirrors research/parity cloud_orders dumps).
# --------------------------------------------------------------------------- #
ENTRY_TAG = urlencode(
    {
        "decision_score": 8,
        "decision_cond": "11110111",
        "decision_gap": "0.0340",
        "decision_vol": "1.612",
        "decision_tdist": "0.0081",
        "decision_rank": 12,
    }
)


def _buy(symbol: str, qty: float, px: float, time: str, fill: str, tag: str = "", oid: int = 1) -> dict:
    return {
        "id": oid,
        "symbol": {"value": symbol, "id": f"{symbol} R", "permtick": symbol},
        "price": px,
        "quantity": qty,
        "time": time,
        "lastFillTime": fill,
        "status": 3,
        "type": 4,
        "direction": 0,
        "tag": tag,
        "events": [{"status": "filled", "fillPrice": px, "fillQuantity": qty, "direction": "buy"}],
    }


def _sell(symbol: str, qty: float, px: float, time: str, fill: str, tag: str = "", oid: int = 2) -> dict:
    return {
        "id": oid,
        "symbol": {"value": symbol, "id": f"{symbol} R", "permtick": symbol},
        "price": px,
        "quantity": qty,  # negative
        "time": time,
        "lastFillTime": fill,
        "status": 3,
        "type": 2,  # stop_market
        "direction": 1,
        "tag": tag,
        "events": [{"status": "filled", "fillPrice": px, "fillQuantity": qty, "direction": "sell"}],
    }


def _orders_one_clean_long() -> list[dict]:
    """One closed long: BUY 100 @ 100 (with the entry tag) → SELL 100 @ 110 (exit tag)."""
    return [
        _buy("AAPL", 100, 100.0, "2025-01-02T05:00:00Z", "2025-01-02T21:00:00Z", tag=ENTRY_TAG, oid=1),
        _sell("AAPL", -100, 110.0, "2025-01-05T05:00:00Z", "2025-01-05T21:00:00Z", tag="stop hit", oid=2),
    ]


def _stats(total_orders: int | str = 2, sharpe: float = 1.3) -> dict:
    return {
        "Total Orders": total_orders,
        "Sharpe Ratio": str(sharpe),
        "Net Profit": "10.0%",
        "Drawdown": "5.0%",
    }


CONFIG = {
    "name": "v2_champion_intraday",
    "version": "276b.1",
    "config_hash": "abc123def456",
    "phases": {
        "signal": {"impl": "BctScoreFull", "params": {"min_score": 7}},
        "entry": {"impl": "IntradayConfirm", "params": {"window_h": 2}},
        "exit": {"impl": "StopMarket", "params": {"atr_mult": 2.0}},
    },
}

BASE_KW = dict(
    config=CONFIG,
    config_hash="abc123def456",
    commit="deadbeef" * 5,
    data_fingerprint="fp-polygon-326",
    objective_version="323.v1",
    timestamp="2026-06-02T12:00:00+00:00",
    env="cloud",
)


def _fetch(orders: list[dict]):
    return lambda bt_id: orders


def _read_trades(run_dir: Path) -> list[dict]:
    raw = gzip.decompress((run_dir / "trades.jsonl.gz").read_bytes()).decode("utf-8")
    return [json.loads(ln) for ln in raw.splitlines() if ln]


# --------------------------------------------------------------------------- #
# Happy path — execution_* + decision_* (typed, cond expanded to 8 bools).
# --------------------------------------------------------------------------- #
def test_clean_run_writes_result_and_trades(tmp_path):
    run_dir = persist_run(
        backtest_id="bt-001",
        status=RunStatus.COMPLETED_CLEAN,
        statistics=_stats(),
        orders_fetch=_fetch(_orders_one_clean_long()),
        dest_root=tmp_path,
        fetch_backoff=0,
        **BASE_KW,
    )
    assert run_dir == tmp_path / "abc123def456" / "bt-001"
    assert (run_dir / "result.json").is_file()
    assert (run_dir / "trades.jsonl.gz").is_file()

    result = json.loads((run_dir / "result.json").read_text())
    assert result["status"] == "COMPLETED_CLEAN"
    assert result["backtest_id"] == "bt-001"
    assert result["config"] == CONFIG  # full config serialized
    assert result["statistics"] == _stats()  # ALL QC statistics verbatim
    assert result["commit"] == "deadbeef" * 5
    assert result["data_fingerprint"] == "fp-polygon-326"
    assert result["objective_version"] == "323.v1"
    assert result["timestamp"] == "2026-06-02T12:00:00+00:00"  # passed in, not computed
    assert result["env"] == "cloud"
    assert result["n_closed_trades"] == 1
    assert result["total_orders"] == 2

    rows = _read_trades(run_dir)
    assert len(rows) == 1
    r = rows[0]
    # execution_* from the fills
    assert r["symbol"] == "AAPL"
    assert r["entry_px"] == 100.0
    assert r["exit_px"] == 110.0
    assert r["qty"] == 100.0
    assert r["side"] == "long"
    assert r["pnl"] == pytest.approx(1000.0)  # (110-100)*100
    assert r["ret"] == pytest.approx(0.10)    # 1000 / (100*100)
    assert r["duration_sec"] == pytest.approx(3 * 86400)  # Jan 2 21:00 -> Jan 5 21:00
    assert r["exit_reason"] == "stop hit"
    assert r["entry_dt"].startswith("2025-01-02")
    assert r["exit_dt"].startswith("2025-01-05")
    # decision_* typed from the entry tag
    assert r["decision_score"] == 8 and isinstance(r["decision_score"], int)
    assert r["decision_cond"] == "11110111"
    assert r["decision_gap"] == pytest.approx(0.0340)
    assert r["decision_vol"] == pytest.approx(1.612)
    assert r["decision_tdist"] == pytest.approx(0.0081)
    assert r["decision_rank"] == 12 and isinstance(r["decision_rank"], int)
    # cond expanded to 8 bools, stable order
    assert [r[f"cond_{i}"] for i in range(8)] == [True, True, True, True, False, True, True, True]
    # MFE/MAE null (follow-on)
    assert r["mfe"] is None and r["mae"] is None
    # schema + context quality
    assert r["schema_version"] == TRADE_SCHEMA_VERSION
    assert r["context_status"] == "OK"  # core present


# --------------------------------------------------------------------------- #
# Tiered context quality (HQ refinement).
# --------------------------------------------------------------------------- #
def test_missing_optional_tag_field_is_null_not_faked(tmp_path):
    """Optional fields absent (no gap/vol/tdist/rank) but core present → null + context_status OK."""
    partial_tag = urlencode({"decision_score": 6, "decision_cond": "11000111"})
    orders = [
        _buy("MSFT", 50, 200.0, "2025-02-01T05:00:00Z", "2025-02-01T21:00:00Z", tag=partial_tag, oid=1),
        _sell("MSFT", -50, 190.0, "2025-02-03T05:00:00Z", "2025-02-03T21:00:00Z", oid=2),
    ]
    run_dir = persist_run(
        backtest_id="bt-opt", status=RunStatus.COMPLETED_CLEAN, statistics=_stats(),
        orders_fetch=_fetch(orders), dest_root=tmp_path, fetch_backoff=0, **BASE_KW,
    )
    r = _read_trades(run_dir)[0]
    assert r["decision_score"] == 6
    assert r["decision_cond"] == "11000111"
    assert r["decision_gap"] is None  # NOT faked
    assert r["decision_vol"] is None
    assert r["decision_tdist"] is None
    assert r["decision_rank"] is None
    assert r["context_status"] == "OK"  # core present → still OK
    assert r["side"] == "long"
    assert r["pnl"] == pytest.approx(-500.0)  # long 50 @ 200, exit @ 190 → (190-200)*50


def test_missing_core_tag_flags_core_missing(tmp_path):
    """No entry tag → execution recorded, decision_* null, context_status CORE_MISSING (not faked)."""
    orders = [
        _buy("TSLA", 10, 300.0, "2025-03-01T05:00:00Z", "2025-03-01T21:00:00Z", tag="", oid=1),
        _sell("TSLA", -10, 320.0, "2025-03-02T05:00:00Z", "2025-03-02T21:00:00Z", oid=2),
    ]
    run_dir = persist_run(
        backtest_id="bt-core", status=RunStatus.COMPLETED_CLEAN, statistics=_stats(),
        orders_fetch=_fetch(orders), dest_root=tmp_path, fetch_backoff=0, **BASE_KW,
    )
    r = _read_trades(run_dir)[0]
    assert r["context_status"] == "CORE_MISSING"
    assert r["decision_score"] is None
    assert r["decision_cond"] is None
    assert all(r[f"cond_{i}"] is None for i in range(8))  # not silently all-False
    # execution is still real and recorded
    assert r["symbol"] == "TSLA" and r["pnl"] == pytest.approx(200.0)


def test_partial_core_missing_score_flags_core_missing(tmp_path):
    """cond present but score absent → still CORE_MISSING (both required for OK)."""
    tag = urlencode({"decision_cond": "11111111", "decision_gap": "0.02"})
    orders = [
        _buy("NVDA", 5, 500.0, "2025-04-01T05:00:00Z", "2025-04-01T21:00:00Z", tag=tag, oid=1),
        _sell("NVDA", -5, 510.0, "2025-04-02T05:00:00Z", "2025-04-02T21:00:00Z", oid=2),
    ]
    run_dir = persist_run(
        backtest_id="bt-pc", status=RunStatus.COMPLETED_CLEAN, statistics=_stats(),
        orders_fetch=_fetch(orders), dest_root=tmp_path, fetch_backoff=0, **BASE_KW,
    )
    r = _read_trades(run_dir)[0]
    assert r["context_status"] == "CORE_MISSING"
    assert r["decision_score"] is None
    assert r["decision_cond"] == "11111111"  # cond still captured
    assert r["decision_gap"] == pytest.approx(0.02)


def test_malformed_cond_is_dropped_not_banked(tmp_path):
    """A cond of wrong length / non-binary is treated as absent (CORE_MISSING), never banked."""
    tag = urlencode({"decision_score": 7, "decision_cond": "1110"})  # only 4 bits
    orders = [
        _buy("AMD", 5, 100.0, "2025-05-01T05:00:00Z", "2025-05-01T21:00:00Z", tag=tag, oid=1),
        _sell("AMD", -5, 105.0, "2025-05-02T05:00:00Z", "2025-05-02T21:00:00Z", oid=2),
    ]
    run_dir = persist_run(
        backtest_id="bt-mal", status=RunStatus.COMPLETED_CLEAN, statistics=_stats(),
        orders_fetch=_fetch(orders), dest_root=tmp_path, fetch_backoff=0, **BASE_KW,
    )
    r = _read_trades(run_dir)[0]
    assert r["decision_cond"] is None  # malformed → dropped
    assert r["context_status"] == "CORE_MISSING"


# --------------------------------------------------------------------------- #
# 3-state status.
# --------------------------------------------------------------------------- #
def test_degraded_run_archived_with_status(tmp_path):
    run_dir = persist_run(
        backtest_id="bt-deg", status=RunStatus.COMPLETED_DEGRADED, statistics=_stats(),
        orders_fetch=_fetch(_orders_one_clean_long()), dest_root=tmp_path, fetch_backoff=0, **BASE_KW,
    )
    result = json.loads((run_dir / "result.json").read_text())
    assert result["status"] == "COMPLETED_DEGRADED"
    assert result["n_closed_trades"] == 1  # detail still captured


def test_crashed_run_captures_stats_even_with_empty_trades(tmp_path):
    """CRASHED with empty trades and orders>0 → does NOT fail loud; stats/params still captured."""
    run_dir = persist_run(
        backtest_id="bt-crash", status=RunStatus.CRASHED, statistics=_stats(total_orders=42),
        orders_fetch=_fetch([]), dest_root=tmp_path, fetch_backoff=0, **BASE_KW,
    )
    result = json.loads((run_dir / "result.json").read_text())
    assert result["status"] == "CRASHED"
    assert result["statistics"]["Total Orders"] == 42  # whatever's retrievable
    assert result["config"] == CONFIG
    assert result["n_closed_trades"] == 0
    rows = _read_trades(run_dir)
    assert rows == []  # empty trades file is valid for a crash


def test_crashed_run_tolerates_fetch_failure(tmp_path):
    """CRASHED: even if orders_fetch raises, provenance survives (best-effort, empty trades)."""
    def _boom(bt_id):
        raise RuntimeError("API 500")

    run_dir = persist_run(
        backtest_id="bt-crash2", status=RunStatus.CRASHED, statistics=_stats(total_orders=10),
        orders_fetch=_boom, dest_root=tmp_path, fetch_backoff=0, **BASE_KW,
    )
    assert (run_dir / "result.json").is_file()
    assert _read_trades(run_dir) == []


# --------------------------------------------------------------------------- #
# Fail-loud: the silent-miss.
# --------------------------------------------------------------------------- #
def test_empty_trades_with_orders_gt_zero_fails_loud(tmp_path):
    with pytest.raises(EmptyTradesError, match="silently evaporate|Total Orders"):
        persist_run(
            backtest_id="bt-miss", status=RunStatus.COMPLETED_CLEAN, statistics=_stats(total_orders=5),
            orders_fetch=_fetch([]), dest_root=tmp_path, fetch_backoff=0, **BASE_KW,
        )


def test_empty_trades_with_zero_orders_is_ok(tmp_path):
    """A legitimately flat run (Total Orders 0) with no trades does NOT fail loud."""
    run_dir = persist_run(
        backtest_id="bt-flat", status=RunStatus.COMPLETED_CLEAN, statistics=_stats(total_orders=0),
        orders_fetch=_fetch([]), dest_root=tmp_path, fetch_backoff=0, **BASE_KW,
    )
    assert json.loads((run_dir / "result.json").read_text())["n_closed_trades"] == 0


# --------------------------------------------------------------------------- #
# Fail-loud: fetch retry + exhaustion.
# --------------------------------------------------------------------------- #
def test_fetch_retries_then_succeeds(tmp_path):
    calls = {"n": 0}

    def _flaky(bt_id):
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionError("transient")
        return _orders_one_clean_long()

    run_dir = persist_run(
        backtest_id="bt-retry", status=RunStatus.COMPLETED_CLEAN, statistics=_stats(),
        orders_fetch=_flaky, dest_root=tmp_path, fetch_retries=3, fetch_backoff=0, **BASE_KW,
    )
    assert calls["n"] == 3
    assert _read_trades(run_dir)[0]["symbol"] == "AAPL"


def test_fetch_exhausted_fails_loud(tmp_path):
    def _always_fail(bt_id):
        raise ConnectionError("down")

    with pytest.raises(OrdersFetchError, match="after 3 attempts"):
        persist_run(
            backtest_id="bt-down", status=RunStatus.COMPLETED_CLEAN, statistics=_stats(),
            orders_fetch=_always_fail, dest_root=tmp_path, fetch_retries=3, fetch_backoff=0, **BASE_KW,
        )


# --------------------------------------------------------------------------- #
# Schema validation rejects a malformed line.
# --------------------------------------------------------------------------- #
def test_schema_rejects_malformed_row():
    bad = {"schema_version": TRADE_SCHEMA_VERSION, "symbol": "X"}  # missing required fields
    with pytest.raises(SchemaValidationError):
        _validate_trade_row(bad)


def test_schema_rejects_bad_cond_pattern():
    """A decision_cond that is a string but not 8 binary chars must be rejected by the schema."""
    from sweeps.archive.snapshot import _trade_to_row
    from datetime import datetime, timezone

    row = _trade_to_row(
        {
            "symbol": "X", "entry_dt": datetime(2025, 1, 1, tzinfo=timezone.utc),
            "entry_px": 1.0, "exit_dt": datetime(2025, 1, 2, tzinfo=timezone.utc), "exit_px": 2.0,
            "qty": 1.0, "side": "long", "pnl": 1.0, "ret": 1.0, "duration_sec": 1.0,
            "exit_reason": None, "entry_tag": None,
        }
    )
    row["decision_cond"] = "XYZ"  # corrupt post-build
    with pytest.raises(SchemaValidationError):
        _validate_trade_row(row)


# --------------------------------------------------------------------------- #
# Atomic write — no partial file on mid-write failure.
# --------------------------------------------------------------------------- #
def test_atomic_write_no_partial_on_failure(tmp_path, monkeypatch):
    """If os.replace fails mid-write, no partial result.json/trades.jsonl.gz is left behind."""
    import sweeps.archive.snapshot as snap

    real_replace = os.replace
    state = {"calls": 0}

    def _failing_replace(src, dst):
        state["calls"] += 1
        # Let the trades.jsonl.gz write succeed, blow up on result.json.
        if str(dst).endswith("result.json"):
            raise OSError("disk full")
        return real_replace(src, dst)

    monkeypatch.setattr(snap.os, "replace", _failing_replace)
    with pytest.raises(OSError, match="disk full"):
        persist_run(
            backtest_id="bt-atomic", status=RunStatus.COMPLETED_CLEAN, statistics=_stats(),
            orders_fetch=_fetch(_orders_one_clean_long()), dest_root=tmp_path, fetch_backoff=0,
            **BASE_KW,
        )
    run_dir = tmp_path / "abc123def456" / "bt-atomic"
    # No result.json (the failed write), and NO leftover temp files in the dir.
    assert not (run_dir / "result.json").exists()
    leftover = list(run_dir.glob(".*tmp")) + list(run_dir.glob("*.tmp"))
    assert leftover == [], f"leftover temp files: {leftover}"


# --------------------------------------------------------------------------- #
# Idempotent re-run.
# --------------------------------------------------------------------------- #
def test_idempotent_rerun_same_bt_id(tmp_path):
    kw = dict(
        backtest_id="bt-idem", status=RunStatus.COMPLETED_CLEAN, statistics=_stats(),
        orders_fetch=_fetch(_orders_one_clean_long()), dest_root=tmp_path, fetch_backoff=0, **BASE_KW,
    )
    run_dir1 = persist_run(**kw)
    bytes1 = (run_dir1 / "trades.jsonl.gz").read_bytes()
    result1 = (run_dir1 / "result.json").read_bytes()
    run_dir2 = persist_run(**kw)  # re-run — atomic overwrite, no error
    assert run_dir1 == run_dir2
    # Deterministic gzip (mtime=0) → byte-identical re-run.
    assert (run_dir2 / "trades.jsonl.gz").read_bytes() == bytes1
    assert (run_dir2 / "result.json").read_bytes() == result1


# --------------------------------------------------------------------------- #
# gz readable + valid jsonl.
# --------------------------------------------------------------------------- #
def test_gz_is_readable_jsonl(tmp_path):
    run_dir = persist_run(
        backtest_id="bt-gz", status=RunStatus.COMPLETED_CLEAN, statistics=_stats(),
        orders_fetch=_fetch(_orders_one_clean_long()), dest_root=tmp_path, fetch_backoff=0, **BASE_KW,
    )
    raw = gzip.decompress((run_dir / "trades.jsonl.gz").read_bytes()).decode("utf-8")
    for line in raw.splitlines():
        json.loads(line)  # each line is valid JSON


# --------------------------------------------------------------------------- #
# Multi-trade pairing (FIFO) + a partial-fill split.
# --------------------------------------------------------------------------- #
def test_multi_symbol_and_partial_fill_pairing(tmp_path):
    """BUY 100 then exit in two SELLs (60 + 40) → two closed lots from one entry; a second symbol."""
    orders = [
        _buy("AAPL", 100, 100.0, "2025-01-02T05:00:00Z", "2025-01-02T21:00:00Z", tag=ENTRY_TAG, oid=1),
        _sell("AAPL", -60, 110.0, "2025-01-03T05:00:00Z", "2025-01-03T21:00:00Z", tag="partial", oid=2),
        _sell("AAPL", -40, 120.0, "2025-01-04T05:00:00Z", "2025-01-04T21:00:00Z", tag="final", oid=3),
        _buy("MSFT", 10, 200.0, "2025-01-02T05:00:00Z", "2025-01-02T21:00:00Z", tag=ENTRY_TAG, oid=4),
        _sell("MSFT", -10, 180.0, "2025-01-06T05:00:00Z", "2025-01-06T21:00:00Z", tag="loss", oid=5),
    ]
    run_dir = persist_run(
        backtest_id="bt-multi", status=RunStatus.COMPLETED_CLEAN, statistics=_stats(total_orders=5),
        orders_fetch=_fetch(orders), dest_root=tmp_path, fetch_backoff=0, **BASE_KW,
    )
    rows = _read_trades(run_dir)
    assert len(rows) == 3
    aapl = [r for r in rows if r["symbol"] == "AAPL"]
    assert len(aapl) == 2
    qtys = sorted(r["qty"] for r in aapl)
    assert qtys == [40.0, 60.0]
    # both AAPL closes inherit the SAME entry decision context (the opening fill's tag)
    assert all(r["decision_score"] == 8 and r["context_status"] == "OK" for r in aapl)
    # the 40-share lot: (120-100)*40 = 800
    big = next(r for r in aapl if r["qty"] == 40.0)
    assert big["pnl"] == pytest.approx(800.0)
    assert big["exit_reason"] == "final"
    msft = next(r for r in rows if r["symbol"] == "MSFT")
    assert msft["pnl"] == pytest.approx(-200.0) and msft["exit_reason"] == "loss"


# --------------------------------------------------------------------------- #
# Guard rails: bad inputs fail loud.
# --------------------------------------------------------------------------- #
def test_missing_backtest_id_fails_loud(tmp_path):
    with pytest.raises(ArchiveError, match="backtest_id is REQUIRED"):
        persist_run(
            backtest_id="", status=RunStatus.COMPLETED_CLEAN, statistics=_stats(),
            orders_fetch=_fetch([]), dest_root=tmp_path, fetch_backoff=0, **BASE_KW,
        )


def test_bad_status_type_fails_loud(tmp_path):
    with pytest.raises(ArchiveError, match="status must be a RunStatus"):
        persist_run(
            backtest_id="bt", status="CLEAN", statistics=_stats(),  # type: ignore[arg-type]
            orders_fetch=_fetch([]), dest_root=tmp_path, fetch_backoff=0, **BASE_KW,
        )


def test_zero_fill_price_fails_loud(tmp_path):
    """A filled order with no determinable non-zero price is corrupt data → fail loud, never bank 0."""
    bad_buy = _buy("X", 10, 0.0, "2025-01-01T05:00:00Z", "2025-01-01T21:00:00Z", oid=1)
    bad_buy["events"] = [{"status": "filled", "fillPrice": 0.0, "fillQuantity": 10, "direction": "buy"}]
    orders = [bad_buy, _sell("X", -10, 100.0, "2025-01-02T05:00:00Z", "2025-01-02T21:00:00Z", oid=2)]
    with pytest.raises(ArchiveError, match="no non-zero fill price"):
        persist_run(
            backtest_id="bt-zero", status=RunStatus.COMPLETED_CLEAN, statistics=_stats(),
            orders_fetch=_fetch(orders), dest_root=tmp_path, fetch_backoff=0, **BASE_KW,
        )


def test_bad_env_fails_loud(tmp_path):
    kw = {**BASE_KW, "env": "prod"}
    with pytest.raises(ArchiveError, match="env must be"):
        persist_run(
            backtest_id="bt", status=RunStatus.COMPLETED_CLEAN, statistics=_stats(),
            orders_fetch=_fetch(_orders_one_clean_long()), dest_root=tmp_path, fetch_backoff=0, **kw,
        )


def test_noncrashed_missing_total_orders_raises(tmp_path):
    # ② (HQ): a non-CRASHED run whose stats lack a parseable 'Total Orders' → ArchiveError. The
    # silent-miss guard can't run on an unverifiable count; an absent/wrong key must NOT silently
    # disable the single most important fail-loud check.
    import pytest
    from sweeps.archive.snapshot import ArchiveError
    with pytest.raises(ArchiveError, match="Total Orders"):
        persist_run(
            backtest_id="bt-no-orders", status=RunStatus.COMPLETED_CLEAN,
            statistics={"Sharpe Ratio": "1.3"},  # no Total Orders key
            orders_fetch=_fetch(_orders_one_clean_long()), dest_root=tmp_path, fetch_backoff=0, **BASE_KW,
        )


def test_crashed_tolerates_corrupt_fill_and_still_writes_result(tmp_path):
    # ③ (HQ): a CRASHED run with a corrupt (0-price) fill must NOT evaporate the run dir — the
    # pairing error is tolerated (degrade to empty trades), result.json STILL captures provenance.
    import json
    bad = [_buy("AAPL", 10, 0.0, "2025-01-03T14:32:00Z", "2025-01-03T14:32:00Z", oid=1)]  # 0-price → raises in pairing
    run_dir = persist_run(
        backtest_id="bt-crash-bad", status=RunStatus.CRASHED, statistics=_stats(total_orders=5),
        orders_fetch=_fetch(bad), dest_root=tmp_path, fetch_backoff=0, **BASE_KW,
    )
    assert (run_dir / "result.json").exists(), "provenance must survive a corrupt fill on CRASHED"
    doc = json.loads((run_dir / "result.json").read_text())
    assert doc["status"] == "CRASHED" and doc["n_closed_trades"] == 0


def test_noncrashed_corrupt_fill_still_fails_loud(tmp_path):
    # the mirror: a CLEAN run with a 0-price fill is a REAL fail-loud (not tolerated).
    import pytest
    from sweeps.archive.snapshot import ArchiveError
    bad = [_buy("AAPL", 10, 0.0, "2025-01-03T14:32:00Z", "2025-01-03T14:32:00Z", oid=1)]
    with pytest.raises(ArchiveError):
        persist_run(
            backtest_id="bt-clean-bad", status=RunStatus.COMPLETED_CLEAN, statistics=_stats(total_orders=5),
            orders_fetch=_fetch(bad), dest_root=tmp_path, fetch_backoff=0, **BASE_KW,
        )


# --------------------------------------------------------------------------- #
# CENSORED open-position rows (v2, #276b-1) — the let-winners blind-spot fix.
#
# The strategy is cut-losers/let-winners → the protective SELL stop is Submitted (status 1) but
# NEVER fills for a position that keeps running. The entry BUY filled (status 3) → the lot is OPEN
# at end-of-data. v1 dropped it (loser-biased substrate). v2 emits it as a censored, M2M row.
# --------------------------------------------------------------------------- #
END_OF_DATA = "2025-12-31T00:00:00Z"


def _submitted_sell(symbol: str, qty: float, time: str, tag: str = "", oid: int = 2) -> dict:
    """A protective SELL stop that was Submitted (status 1) but NEVER filled (no fill event). This
    is exactly the /orders feed shape for an open held-winner at end-of-data."""
    return {
        "id": oid,
        "symbol": {"value": symbol, "id": f"{symbol} R", "permtick": symbol},
        "price": 0.0,         # a never-filled stop has no fill price
        "quantity": qty,      # negative (a long protective stop)
        "time": time,
        "status": 1,          # Submitted — NOT 3 (Filled)
        "type": 2,            # stop_market
        "direction": 1,
        "tag": tag,
        "events": [{"status": "submitted", "fillPrice": 0.0, "fillQuantity": 0, "direction": "sell"}],
    }


def _mark(price_by_sym: dict, source: str = M2M_LOCAL_PARQUET):
    """An injected M2MMark mock: returns (price, source) from a fixture map, or (None, unavailable)."""
    def _m(symbol: str, end_of_data) -> tuple:
        assert isinstance(end_of_data, datetime)  # the caller passes a real datetime, not a clock
        if symbol in price_by_sym:
            return float(price_by_sym[symbol]), source
        return None, M2M_UNAVAILABLE
    return _m


def _open_winner_orders() -> list:
    """One open long: BUY 100 @ 100 (entry tag) + a Submitted-never-filled protective SELL stop."""
    return [
        _buy("AAPL", 100, 100.0, "2025-06-02T05:00:00Z", "2025-06-02T21:00:00Z", tag=ENTRY_TAG, oid=1),
        _submitted_sell("AAPL", -100, "2025-06-02T05:00:00Z", tag="stop @ 90", oid=2),
    ]


def test_open_lot_emits_censored_row_with_m2m(tmp_path):
    """A buy filled + sell unfilled → a CENSORED row: entry context + M2M ret from the injected mark."""
    run_dir = persist_run(
        backtest_id="bt-cens", status=RunStatus.COMPLETED_CLEAN, statistics=_stats(total_orders=1),
        orders_fetch=_fetch(_open_winner_orders()),
        end_of_data=END_OF_DATA, m2m_mark=_mark({"AAPL": 130.0}),
        dest_root=tmp_path, fetch_backoff=0, **BASE_KW,
    )
    rows = _read_trades(run_dir)
    assert len(rows) == 1
    r = rows[0]
    assert r["censored"] is True
    assert r["symbol"] == "AAPL"
    assert r["entry_px"] == 100.0
    assert r["qty"] == 100.0
    assert r["side"] == "long"
    assert r["exit_dt"].startswith("2025-12-31")     # marked at end-of-data
    assert r["exit_px"] == pytest.approx(130.0)       # the M2M mark
    assert r["exit_reason"] == CENSORED_EXIT_REASON
    # PROVISIONAL outcome from entry_px -> mark
    assert r["m2m_ret"] == pytest.approx(0.30)        # (130-100)/100
    assert r["ret"] == pytest.approx(0.30)            # ret mirrors the provisional m2m
    assert r["pnl"] == pytest.approx(3000.0)          # (130-100)*100
    assert r["m2m_source"] == M2M_LOCAL_PARQUET
    # the SAME decision context as a closed row (the entry tag)
    assert r["decision_score"] == 8
    assert r["decision_cond"] == "11110111"
    assert r["context_status"] == "OK"
    assert [r[f"cond_{i}"] for i in range(8)] == [True, True, True, True, False, True, True, True]
    assert r["schema_version"] == TRADE_SCHEMA_VERSION
    # result.json splits the counts
    result = json.loads((run_dir / "result.json").read_text())
    assert result["n_closed_trades"] == 0
    assert result["n_censored_trades"] == 1
    assert result["n_trade_rows"] == 1


def test_m2m_unavailable_is_null_not_faked(tmp_path):
    """No resolvable mark → m2m_ret null + m2m_source 'unavailable' (entry context still recorded)."""
    run_dir = persist_run(
        backtest_id="bt-cens-unav", status=RunStatus.COMPLETED_CLEAN, statistics=_stats(total_orders=1),
        orders_fetch=_fetch(_open_winner_orders()),
        end_of_data=END_OF_DATA, m2m_mark=_mark({}),   # empty map → unavailable
        dest_root=tmp_path, fetch_backoff=0, **BASE_KW,
    )
    r = _read_trades(run_dir)[0]
    assert r["censored"] is True
    assert r["m2m_ret"] is None        # NOT faked
    assert r["ret"] is None
    assert r["pnl"] is None
    assert r["exit_px"] is None        # no mark → no exit px
    assert r["m2m_source"] == M2M_UNAVAILABLE
    # entry context still has learn value
    assert r["decision_score"] == 8 and r["context_status"] == "OK"
    assert r["exit_reason"] == CENSORED_EXIT_REASON


def test_closed_and_censored_mix_preserves_closed(tmp_path):
    """A closed loser + an open winner → one censored=false row (real exit) + one censored=true row."""
    orders = [
        # closed loser: buy 50 @ 200 -> sell 50 @ 180 (real exit)
        _buy("MSFT", 50, 200.0, "2025-02-01T05:00:00Z", "2025-02-01T21:00:00Z", tag=ENTRY_TAG, oid=1),
        _sell("MSFT", -50, 180.0, "2025-02-03T05:00:00Z", "2025-02-03T21:00:00Z", tag="stop", oid=2),
        # open winner: buy 100 @ 100, stop submitted-never-filled
        _buy("AAPL", 100, 100.0, "2025-06-02T05:00:00Z", "2025-06-02T21:00:00Z", tag=ENTRY_TAG, oid=3),
        _submitted_sell("AAPL", -100, "2025-06-02T05:00:00Z", tag="stop", oid=4),
    ]
    run_dir = persist_run(
        backtest_id="bt-mix", status=RunStatus.COMPLETED_CLEAN, statistics=_stats(total_orders=3),
        orders_fetch=_fetch(orders),
        end_of_data=END_OF_DATA, m2m_mark=_mark({"AAPL": 150.0}),
        dest_root=tmp_path, fetch_backoff=0, **BASE_KW,
    )
    rows = _read_trades(run_dir)
    assert len(rows) == 2
    closed = [r for r in rows if not r["censored"]]
    censored = [r for r in rows if r["censored"]]
    assert len(closed) == 1 and len(censored) == 1
    # closed row UNCHANGED (real exit, realized loss)
    c = closed[0]
    assert c["symbol"] == "MSFT"
    assert c["exit_px"] == 180.0
    assert c["pnl"] == pytest.approx(-1000.0)   # (180-200)*50
    assert c["exit_reason"] == "stop"
    assert c["m2m_ret"] is None and c["m2m_source"] is None  # N/A on a realized row
    # censored row: provisional winner
    o = censored[0]
    assert o["symbol"] == "AAPL"
    assert o["m2m_ret"] == pytest.approx(0.50)  # (150-100)/100
    result = json.loads((run_dir / "result.json").read_text())
    assert result["n_closed_trades"] == 1
    assert result["n_censored_trades"] == 1


def test_no_m2m_wiring_skips_censored_capture(tmp_path):
    """Back-compat: without end_of_data/m2m_mark, censored capture is SKIPPED, closed unchanged."""
    orders = _open_winner_orders() + [
        # add a closed trade so Total Orders>0 doesn't trip the silent-miss with 0 rows
        _buy("MSFT", 10, 50.0, "2025-01-02T05:00:00Z", "2025-01-02T21:00:00Z", tag=ENTRY_TAG, oid=3),
        _sell("MSFT", -10, 55.0, "2025-01-03T05:00:00Z", "2025-01-03T21:00:00Z", tag="exit", oid=4),
    ]
    run_dir = persist_run(
        backtest_id="bt-nocap", status=RunStatus.COMPLETED_CLEAN, statistics=_stats(total_orders=3),
        orders_fetch=_fetch(orders), dest_root=tmp_path, fetch_backoff=0, **BASE_KW,
    )
    rows = _read_trades(run_dir)
    # only the closed MSFT trade — the open AAPL lot is NOT emitted (no m2m wiring)
    assert len(rows) == 1
    assert rows[0]["symbol"] == "MSFT" and rows[0]["censored"] is False
    result = json.loads((run_dir / "result.json").read_text())
    assert result["n_censored_trades"] == 0


def test_censored_short_lot_m2m_sign(tmp_path):
    """A censored SHORT lot marks correctly: a mark BELOW entry is a provisional WIN for a short."""
    orders = [
        _sell("XYZ", -100, 100.0, "2025-06-02T05:00:00Z", "2025-06-02T21:00:00Z", tag=ENTRY_TAG, oid=1),
        # a never-filled protective BUY-to-cover stop leaves the short open
        {**_buy("XYZ", 100, 0.0, "2025-06-02T05:00:00Z", "2025-06-02T21:00:00Z", oid=2), "status": 1,
         "events": [{"status": "submitted", "fillPrice": 0.0, "fillQuantity": 0, "direction": "buy"}]},
    ]
    run_dir = persist_run(
        backtest_id="bt-short", status=RunStatus.COMPLETED_CLEAN, statistics=_stats(total_orders=1),
        orders_fetch=_fetch(orders),
        end_of_data=END_OF_DATA, m2m_mark=_mark({"XYZ": 80.0}),
        dest_root=tmp_path, fetch_backoff=0, **BASE_KW,
    )
    r = _read_trades(run_dir)[0]
    assert r["censored"] is True and r["side"] == "short"
    # short entered @ 100, marked @ 80 → +20% provisional
    assert r["m2m_ret"] == pytest.approx(0.20)
    assert r["pnl"] == pytest.approx(2000.0)   # (80-100)*100*(-1)


def test_censored_rows_are_deterministic_idempotent(tmp_path):
    """Censored capture is byte-identical on re-run (deterministic ordering + gzip mtime=0)."""
    kw = dict(
        backtest_id="bt-cens-idem", status=RunStatus.COMPLETED_CLEAN, statistics=_stats(total_orders=1),
        orders_fetch=_fetch(_open_winner_orders()),
        end_of_data=END_OF_DATA, m2m_mark=_mark({"AAPL": 130.0}),
        dest_root=tmp_path, fetch_backoff=0, **BASE_KW,
    )
    d1 = persist_run(**kw)
    b1 = (d1 / "trades.jsonl.gz").read_bytes()
    d2 = persist_run(**kw)
    assert (d2 / "trades.jsonl.gz").read_bytes() == b1


def test_schema_version_bumped_to_2():
    assert TRADE_SCHEMA_VERSION == 2


@pytest.mark.parametrize("bad_price", [0.0, -5.0, float("nan"), float("inf")])
def test_degenerate_m2m_mark_degrades_to_unavailable_not_faked(tmp_path, bad_price):
    """A 0 / negative / NaN / inf mark is corrupt data → degrade to honest unavailable null, never
    bank a fabricated -100% (or a NaN that serialises to invalid JSON). Mirrors _fill_price."""
    run_dir = persist_run(
        backtest_id="bt-degen", status=RunStatus.COMPLETED_CLEAN, statistics=_stats(total_orders=1),
        orders_fetch=_fetch(_open_winner_orders()),
        end_of_data=END_OF_DATA, m2m_mark=lambda s, e: (bad_price, M2M_QC_NATIVE),
        dest_root=tmp_path, fetch_backoff=0, **BASE_KW,
    )
    r = _read_trades(run_dir)[0]
    assert r["censored"] is True
    assert r["m2m_ret"] is None       # NOT a fabricated -100% / NaN
    assert r["ret"] is None and r["pnl"] is None
    assert r["exit_px"] is None
    assert r["m2m_source"] == M2M_UNAVAILABLE
    # entry context still has learn value
    assert r["decision_score"] == 8
