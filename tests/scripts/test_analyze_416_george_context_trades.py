from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from analyze_416_george_context_trades import (  # noqa: E402
    _compare_to_baseline,
    extract_trades,
    parse_decision_tag,
)


def _write_result(path: Path, *, symbol: str = "ABC", sell_filled: bool = True) -> None:
    sell_status = 3 if sell_filled else 1
    closed_trades = []
    if sell_filled:
        closed_trades.append(
            {
                "symbols": [{"value": symbol}],
                "entryTime": "2025-01-02T14:31:00Z",
                "entryPrice": 10.0,
                "quantity": 10.0,
                "exitTime": "2025-01-10T14:31:00Z",
                "exitPrice": 8.0,
                "profitLoss": -22.0,
                "totalFees": 2.0,
                "mae": -30.0,
                "mfe": 12.0,
                "duration": "8.00:00:00",
                "orderIds": [1, 2],
            }
        )
    payload = {
        "orders": {
            "1": {
                "id": 1,
                "symbol": {"value": symbol},
                "direction": 0,
                "status": 3,
                "lastFillTime": "2025-01-02T14:31:00Z",
                "time": "2025-01-02T14:31:00Z",
                "price": 10.0,
                "quantity": 10.0,
                "tag": (
                    "decision_score=7&decision_cond=11111101&decision_gap=0.031"
                    "&decision_vol=2.5&decision_tdist=0&decision_rank=42"
                ),
            },
            "2": {
                "id": 2,
                "symbol": {"value": symbol},
                "direction": 1,
                "status": sell_status,
                "lastFillTime": "2025-01-10T14:31:00Z" if sell_filled else None,
                "time": "2025-01-02T14:31:00Z",
                "price": 8.0 if sell_filled else 0.0,
                "quantity": -10.0,
                "tag": "",
            },
        },
        "totalPerformance": {"closedTrades": closed_trades},
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_parse_decision_tag_typed_metrics() -> None:
    parsed = parse_decision_tag(
        "decision_score=8&decision_cond=1111&decision_gap=0.04"
        "&decision_vol=9.2&decision_tdist=0.1&decision_rank=12"
    )

    assert parsed["decision_score"] == 8
    assert parsed["decision_cond"] == "1111"
    assert parsed["decision_gap"] == 0.04
    assert parsed["decision_vol"] == 9.2
    assert parsed["decision_tdist"] == 0.1
    assert parsed["decision_rank"] == 12


def test_extract_trades_joins_closed_trade_stats(tmp_path: Path) -> None:
    result = tmp_path / "result.json"
    _write_result(result, symbol="XYZ", sell_filled=True)

    trades = extract_trades({
        "variant_id": "v1",
        "family": "fam",
        "result_path": str(result),
    })

    assert len(trades) == 1
    trade = trades[0]
    assert trade.symbol == "XYZ"
    assert trade.status == "closed"
    assert trade.pnl == -22.0
    assert trade.mfe == 12.0
    assert trade.mae == -30.0
    assert trade.duration_days == 8.0
    assert trade.decision_rank == 42


def test_extract_trades_marks_unclosed_entries_open(tmp_path: Path) -> None:
    result = tmp_path / "result.json"
    _write_result(result, symbol="OPEN", sell_filled=False)

    trades = extract_trades({
        "variant_id": "v1",
        "family": "fam",
        "result_path": str(result),
    })

    assert trades[0].status == "open"
    assert trades[0].pnl is None
    assert trades[0].exit_time == ""


def test_compare_to_baseline_counts_added_and_missed_entries(tmp_path: Path) -> None:
    base_result = tmp_path / "base.json"
    variant_result = tmp_path / "variant.json"
    _write_result(base_result, symbol="BASE", sell_filled=True)
    _write_result(variant_result, symbol="NEW", sell_filled=True)
    baseline = extract_trades({
        "variant_id": "baseline",
        "family": "fam",
        "result_path": str(base_result),
    })
    variant = extract_trades({
        "variant_id": "variant",
        "family": "fam",
        "result_path": str(variant_result),
    })

    row = _compare_to_baseline(
        {"variant_id": "variant", "family": "fam", "ret_pct": "1", "dd_pct": "2"},
        variant,
        baseline,
    )

    assert row["same_entry_count"] == "0"
    assert row["added_entry_count"] == "1"
    assert row["missed_entry_count"] == "1"
    assert row["added_symbols"] == "NEW"
    assert row["missed_symbols"] == "BASE"
