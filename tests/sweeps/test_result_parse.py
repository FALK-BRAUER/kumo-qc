"""Result-parse tests (#214 D.5) — QC stats block -> RunResult, on CAPTURED fixtures.

Single parse path: the same parser handles local LEAN JSON and cloud /backtests/read
statistics (identical QC key names). Fail-loud: NaN/inf -> ResultParseError; empty-orders ->
is_degraded (the empty-warmup-coarse +3.9% artifact); missing mandatory stat -> raise.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from sweeps.adapters.result_parse import (
    parse_daily_returns,
    parse_metrics,
    parse_run_result,
    parse_trades,
)
from sweeps.types import ResultParseError

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def test_parse_clean_metrics_trio() -> None:
    rr = parse_run_result(_load("lean_result_clean.json"))
    assert rr.metrics.sharpe == 1.442
    assert rr.metrics.ret_pct == 42.4  # "42.4%" -> 42.4
    assert rr.metrics.dd_pct == 9.5
    assert rr.metrics.orders == 8
    assert rr.is_degraded is False


def test_parse_clean_trades() -> None:
    rr = parse_run_result(_load("lean_result_clean.json"))
    assert len(rr.trades) == 4
    aapl = rr.trades[0]
    assert aapl.symbol == "AAPL"
    assert aapl.pnl == 1200.0
    # ret = pnl / (entry_price * qty) = 1200 / (200 * 50) = 0.12
    assert aapl.ret == pytest.approx(0.12)
    assert aapl.entry_dt < aapl.exit_dt


def test_parse_clean_daily_returns() -> None:
    rr = parse_run_result(_load("lean_result_clean.json"))
    assert len(rr.daily_returns) == 7
    assert rr.daily_returns[1] == pytest.approx(0.012)


def test_parse_string_and_numeric_stats_equivalent() -> None:
    # QC sends strings ("1.442") OR numbers; both coerce identically.
    m_str = parse_metrics({"Sharpe Ratio": "1.5", "Net Profit": "10%", "Drawdown": "3%", "Total Orders": "4"})
    m_num = parse_metrics({"Sharpe Ratio": 1.5, "Net Profit": 10.0, "Drawdown": 3.0, "Total Orders": 4})
    assert m_str == m_num


def test_parse_thousands_separator_orders() -> None:
    m = parse_metrics({"Sharpe Ratio": "1.0", "Net Profit": "5%", "Drawdown": "1%", "Total Orders": "1,234"})
    assert m.orders == 1234


def test_degraded_zero_orders_flagged_not_raised_by_parser() -> None:
    # The PARSER classifies degraded; the ADAPTER decides to raise (a legitimately-flat config
    # could be inspected). Empty-orders = the empty-warmup-coarse +3.9% artifact.
    rr = parse_run_result(_load("lean_result_degraded.json"))
    assert rr.is_degraded is True
    assert rr.metrics.orders == 0
    assert rr.metrics.ret_pct == 3.9


def test_nan_metric_raises() -> None:
    with pytest.raises(ResultParseError, match="non-finite"):
        parse_run_result(_load("lean_result_nan.json"))


def test_missing_mandatory_stat_raises() -> None:
    with pytest.raises(ResultParseError, match="Sharpe Ratio"):
        parse_metrics({"Net Profit": "10%", "Drawdown": "3%", "Total Orders": "4"})


def test_unparseable_stat_raises() -> None:
    with pytest.raises(ResultParseError, match="unparseable"):
        parse_metrics({"Sharpe Ratio": "abc", "Net Profit": "1%", "Drawdown": "1%", "Total Orders": "1"})


def test_no_statistics_block_raises() -> None:
    with pytest.raises(ResultParseError, match="no 'statistics'"):
        parse_run_result({"totalPerformance": {}, "charts": {}})


def test_trades_absent_yields_empty_tuple() -> None:
    assert parse_trades({}) == ()


def test_daily_returns_absent_yields_empty_tuple() -> None:
    assert parse_daily_returns({}) == ()
