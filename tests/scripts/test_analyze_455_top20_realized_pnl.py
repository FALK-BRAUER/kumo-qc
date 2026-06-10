from __future__ import annotations

import csv
import json
from pathlib import Path

from scripts.analyze_455_top20_realized_pnl import parse_exit_events, run


BASE = "strategies.realized_giveback_no_bull"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def _order(order_id: int, symbol: str, qty: float, price: float, when: str, tag: str = "") -> dict:
    return {
        "id": order_id,
        "symbol": {"value": symbol, "id": f"{symbol} XOF4GF67NMG5"},
        "quantity": qty,
        "price": price,
        "time": when,
        "lastFillTime": when,
        "status": 3,
        "direction": 0 if qty > 0 else 1,
        "tag": tag,
    }


def _result(symbol: str, open_symbol: str, closed_pnl: float) -> dict:
    return {
        "orders": {
            "1": _order(
                1,
                symbol,
                10,
                100.0,
                "2025-01-02T14:31:00Z",
                "decision_rank=5&decision_gap=0.02&decision_vol=2.5",
            ),
            "2": _order(2, symbol, -10, 105.0, "2025-01-10T20:00:00Z"),
            "3": _order(3, open_symbol, 4, 50.0, "2025-12-01T14:31:00Z", "decision_rank=7"),
        },
        "totalPerformance": {
            "closedTrades": [
                {
                    "symbols": [{"value": symbol}],
                    "entryTime": "2025-01-02T14:31:00Z",
                    "entryPrice": 100.0,
                    "quantity": 10,
                    "exitTime": "2025-01-10T20:00:00Z",
                    "exitPrice": 105.0,
                    "profitLoss": closed_pnl,
                    "totalFees": 2.0,
                    "mae": -20.0,
                    "mfe": 80.0,
                    "duration": "8.05:29:00",
                    "orderIds": [1, 2],
                }
            ],
            "tradeStatistics": {"totalProfitLoss": closed_pnl},
        },
    }


def _summary_row(variant: str, setting: str, result_path: str, run_dir: str, unrealized: str) -> dict[str, str]:
    return {
        "rank": "1",
        "variant_id": variant,
        "scanner_setting": setting,
        "base_module": BASE,
        "source_sweep_id": "fixture",
        "ret_pct": "1.0",
        "dd_pct": "2.0",
        "sharpe": "0.1",
        "orders": "3",
        "realized_net": "100.0",
        "unrealized": unrealized,
        "closed_trades": "1",
        "closed_win_rate": "100.0",
        "delta_ret_vs_off": "0",
        "delta_dd_vs_off": "0",
        "delta_orders_vs_off": "0",
        "delta_realized_vs_off": "0",
        "delta_unrealized_vs_off": "0",
        "result_path": result_path,
    } | {"run_dir": run_dir}


def _write_summary(report_dir: Path, rows: list[dict[str, str]]) -> None:
    report_dir.mkdir(parents=True)
    columns = list(rows[0])
    with (report_dir / "summary.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def test_parse_exit_events_handles_wrapped_lean_log(tmp_path: Path) -> None:
    log = tmp_path / "lean-stdout.txt"
    log.write_text(
        "20260610 TRACE:: Log: EXIT_EVENT|2025-01-10|AAA|event=PROACTIVE_STRENGTH_EXIT|"
        "module=exit.proactive_strength_exit|reason=giveback|days_held=8|qty=10|"
        "entry_price=100|exit_price=105|pnl=50|return_pct=0.05|mfe_pct=0.08|\n"
        "mae_pct=-0.02|peak_return_pct=0.08|giveback_from_peak_pct=0.03\n",
        encoding="utf-8",
    )

    events = parse_exit_events(log, "variant_a")

    assert len(events) == 1
    assert events[0].symbol == "AAA"
    assert events[0].reason == "giveback"
    assert events[0].mfe_pct == 0.08
    assert events[0].giveback_from_peak_pct == 0.03


def test_run_writes_top20_vs_off_diagnostics_from_external_source_root(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    report_dir = tmp_path / "report"
    output_dir = tmp_path / "out"

    off_result_rel = Path("sweeps/runs/fixture/off/hash/fy/backtests/ts/1.json")
    top_result_rel = Path("sweeps/runs/fixture/top20/hash/fy/backtests/ts/2.json")
    off_run_rel = Path("sweeps/runs/fixture/off/hash/fy")
    top_run_rel = Path("sweeps/runs/fixture/top20/hash/fy")
    _write_json(source_root / off_result_rel, _result("AAA", "BBB", -25.0))
    _write_json(source_root / top_result_rel, _result("AAA", "CCC", 75.0))
    (source_root / off_run_rel / "lean-stdout.txt").write_text(
        "EXIT_EVENT|2025-01-10|AAA|event=PROACTIVE_STRENGTH_EXIT|module=exit.proactive_strength_exit|"
        "reason=giveback|days_held=8|qty=10|entry_price=100|exit_price=105|pnl=-25|"
        "return_pct=-0.025|mfe_pct=0.080|mae_pct=-0.020|peak_return_pct=0.080|giveback_from_peak_pct=0.105\n",
        encoding="utf-8",
    )
    (source_root / top_run_rel / "lean-stdout.txt").write_text(
        "EXIT_EVENT|2025-01-10|AAA|event=PROACTIVE_STRENGTH_EXIT|module=exit.proactive_strength_exit|"
        "reason=target|days_held=8|qty=10|entry_price=100|exit_price=105|pnl=75|"
        "return_pct=0.075|mfe_pct=0.090|mae_pct=-0.010|peak_return_pct=0.090|giveback_from_peak_pct=0.000\n",
        encoding="utf-8",
    )
    _write_summary(
        report_dir,
        [
            _summary_row("giveback_no_bull_scanner_off", "off", str(off_result_rel), str(off_run_rel), "$-120.00"),
            _summary_row(
                "giveback_no_bull_scanner_top20",
                "top20",
                str(top_result_rel),
                str(top_run_rel),
                "$-200.00",
            ),
        ],
    )

    run(report_dir, source_root, output_dir)

    with (output_dir / "symbol_delta_top20_vs_off.csv").open(newline="", encoding="utf-8") as fh:
        deltas = {row["symbol"]: row for row in csv.DictReader(fh)}
    assert deltas["BBB"]["relation"] == "removed_by_top20"
    assert deltas["CCC"]["relation"] == "added_by_top20"
    assert deltas["AAA"]["delta_closed_pnl"] == "100.00"

    with (output_dir / "entry_delta_top20_vs_off.csv").open(newline="", encoding="utf-8") as fh:
        entry_deltas = {(row["symbol"], row["entry_date"]): row for row in csv.DictReader(fh)}
    assert entry_deltas[("BBB", "2025-12-01")]["relation"] == "removed_by_top20"
    assert entry_deltas[("CCC", "2025-12-01")]["relation"] == "added_by_top20"

    with (output_dir / "decision_rank_buckets.csv").open(newline="", encoding="utf-8") as fh:
        buckets = list(csv.DictReader(fh))
    assert any(row["decision_rank_bucket"] == "001_010" for row in buckets)

    with (output_dir / "open_lot_unrealized_allocation.csv").open(newline="", encoding="utf-8") as fh:
        open_rows = list(csv.DictReader(fh))
    assert {row["symbol"] for row in open_rows} == {"BBB", "CCC"}
    assert next(row for row in open_rows if row["symbol"] == "CCC")["allocated_unrealized_est"] == "-200.00"

    diagnostics = (output_dir / "diagnostics.md").read_text(encoding="utf-8")
    assert "Per-symbol open PnL is an allocation estimate" in diagnostics
    assert "do not include LambdaMART scanner score/rank" in diagnostics
    assert "`giveback_no_bull_scanner_top20`" in diagnostics
