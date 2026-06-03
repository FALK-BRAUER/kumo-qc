"""CloudLeanRun adapter tests (#214 D.5) — ZERO real QC spend (cloud calls MOCKED).

Asserts the assert_cloud_clean gate (mirrors qc_v2_cloud's contract, fail-loud):
clean -> RunResult; runtime error -> raise; partial progress -> raise; null/zero/unparseable
orders -> raise (the silent-zero-champion hole, #326); NaN metric -> raise. A failing cloud
gate DROPS the winner (raises) — never promotes a mirage.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from sweeps.adapters.cloud_lean import CloudLeanRun, CloudResult, assert_cloud_clean
from sweeps.types import CloudValidationError, ResultMetrics, RunConfig, SweepConfig, Window
from sweeps.enumerate import enumerate_catalog
from tests.sweeps.conftest import MOCK_CATALOG

FIXTURES = Path(__file__).parent / "fixtures"
W = Window(name="fy2025_stress", start="2025-01-01", end="2025-12-31")


def _cloud_result(fixture: str, bid: str = "bt-abc") -> CloudResult:
    raw = json.loads((FIXTURES / fixture).read_text())
    return CloudResult(
        backtest_id=bid,
        progress=raw.get("progress", 0),
        error=raw.get("error") or raw.get("stacktrace"),
        raw=raw,
    )


def _adapter(fixture: str) -> CloudLeanRun:
    def deploy(config: SweepConfig, window: Window) -> str:
        return "compile-id-123"

    def run_backtest(name: str, compile_id: str) -> CloudResult:
        return _cloud_result(fixture)

    return CloudLeanRun(deploy=deploy, run_backtest=run_backtest)


def _config() -> SweepConfig:
    return enumerate_catalog(MOCK_CATALOG)[0]  # type: ignore[arg-type]


# --- assert_cloud_clean unit contract --- #


def test_assert_clean_passes() -> None:
    assert_cloud_clean(_cloud_result("cloud_read_clean.json"))  # no raise


def test_assert_runtime_error_raises() -> None:
    with pytest.raises(CloudValidationError, match="runtime error"):
        assert_cloud_clean(_cloud_result("cloud_read_crashed.json"))


def test_assert_partial_progress_raises() -> None:
    with pytest.raises(CloudValidationError, match="incomplete"):
        assert_cloud_clean(_cloud_result("cloud_read_partial.json"))


def test_assert_null_orders_raises() -> None:
    with pytest.raises(CloudValidationError, match="UNVERIFIABLE"):
        assert_cloud_clean(_cloud_result("cloud_read_nullorders.json"))


def test_assert_zero_orders_raises() -> None:
    r = CloudResult(backtest_id="x", progress=1, error=None,
                    raw={"statistics": {"Total Orders": "0"}})
    with pytest.raises(CloudValidationError, match="0 orders"):
        assert_cloud_clean(r)


def test_assert_unparseable_orders_raises() -> None:
    r = CloudResult(backtest_id="x", progress=1, error=None,
                    raw={"statistics": {"Total Orders": "lots"}})
    with pytest.raises(CloudValidationError, match="unparseable"):
        assert_cloud_clean(r)


def test_assert_nan_metric_raises() -> None:
    r = CloudResult(backtest_id="x", progress=1, error=None,
                    raw={"statistics": {"Total Orders": "5", "Sharpe Ratio": "inf"}})
    with pytest.raises(CloudValidationError, match="non-finite"):
        assert_cloud_clean(r)


# --- adapter end-to-end (mocked cloud) --- #


def test_satisfies_run_config_protocol() -> None:
    assert isinstance(_adapter("cloud_read_clean.json"), RunConfig)


def test_clean_run_returns_metrics() -> None:
    m = _adapter("cloud_read_clean.json")(_config(), W)
    assert isinstance(m, ResultMetrics)
    assert m.sharpe == 1.442 and m.orders == 8


def test_clean_run_result_has_trades() -> None:
    rr = _adapter("cloud_read_clean.json").run_result(_config(), W)
    assert len(rr.trades) == 4
    assert rr.is_degraded is False


def test_crashed_run_raises_not_promoted() -> None:
    # The #318 trap: completed=True but crashed. The adapter RAISES — winner dropped.
    with pytest.raises(CloudValidationError, match="runtime error"):
        _adapter("cloud_read_crashed.json")(_config(), W)


def test_bt_name_includes_config_and_window() -> None:
    adapter = _adapter("cloud_read_clean.json")
    name = adapter._bt_name(_config(), W)
    assert _config().config_hash in name and "fy2025_stress" in name


def test_deploy_then_run_called_in_order() -> None:
    calls: list[str] = []

    def deploy(config: SweepConfig, window: Window) -> str:
        calls.append("deploy")
        return "cid"

    def run_backtest(name: str, compile_id: str) -> CloudResult:
        calls.append(f"run:{compile_id}")
        return _cloud_result("cloud_read_clean.json")

    CloudLeanRun(deploy=deploy, run_backtest=run_backtest)(_config(), W)
    assert calls == ["deploy", "run:cid"]
