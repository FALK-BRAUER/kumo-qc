"""LocalLeanRun adapter tests (#214 D.2) — ZERO real LEAN / Docker.

The dist-build, lean-run, and result-locate steps are INJECTED fakes that touch a temp FS +
copy a fixture result JSON into the per-run output dir. Asserts: per-(config,window) dir
isolation; data symlink; marker verification (mismatch RAISES — the fabrication guard);
degraded run RAISES (G-DATA gate); non-zero LEAN exit RAISES; RunConfig Protocol conformance.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from sweeps.adapters.local_lean import LocalLeanRun
from sweeps.types import (
    DegradedDataError,
    MarkerMismatchError,
    ResultMetrics,
    ResultParseError,
    RunConfig,
    SweepConfig,
    Window,
)
from tests.sweeps.conftest import MOCK_CATALOG
from sweeps.enumerate import enumerate_catalog

FIXTURES = Path(__file__).parent / "fixtures"
MARKER = "champion-sweep-marker"
W = Window(name="w1", start="2025-01-01", end="2025-02-28")


def _write_run_output(run_dir: Path, *, fixture: str, marker: str | None) -> None:
    """Emulate what `lean backtest` leaves behind: backtests/<ts>/<id>.json + code/main.py."""
    bt = run_dir / "backtests" / "2025-06-02_00-00-00"
    bt.mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURES / fixture, bt / "1234.json")
    if marker is not None:
        code = bt / "code"
        code.mkdir(parents=True, exist_ok=True)
        (code / "main.py").write_text(f"# STRATEGY name = '{marker}'\nclass X: pass\n")


def _adapter(tmp_path: Path, *, fixture: str, deployed_marker: str = MARKER,
             executed_marker: str | None = MARKER, marker_check: bool = True,
             rc: int = 0) -> LocalLeanRun:
    data_root = tmp_path / "data"
    data_root.mkdir()
    runs_root = tmp_path / "runs"

    def dist_builder(config: SweepConfig, window: Window, run_dir: Path) -> str:
        # Fold step is faked: just emit the run output the way LEAN would, then return the marker.
        _write_run_output(run_dir, fixture=fixture, marker=executed_marker)
        return deployed_marker

    def run_lean(run_dir: Path) -> int:
        return rc  # output already written by dist_builder; emulate exit code

    return LocalLeanRun(
        dist_builder=dist_builder,
        data_root=data_root,
        runs_root=runs_root,
        marker_check=marker_check,
        run_lean=run_lean,
    )


def _config() -> SweepConfig:
    return enumerate_catalog(MOCK_CATALOG)[0]  # type: ignore[arg-type]


def test_satisfies_run_config_protocol(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path, fixture="lean_result_clean.json")
    assert isinstance(adapter, RunConfig)


def test_call_returns_metrics_trio(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path, fixture="lean_result_clean.json")
    m = adapter(_config(), W)
    assert isinstance(m, ResultMetrics)
    assert m.sharpe == 1.442 and m.ret_pct == 42.4 and m.dd_pct == 9.5 and m.orders == 8


def test_run_result_carries_trades_and_returns(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path, fixture="lean_result_clean.json")
    rr = adapter.run_result(_config(), W)
    assert len(rr.trades) == 4
    assert len(rr.daily_returns) == 7
    assert rr.is_degraded is False


def test_per_config_window_dir_isolation(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path, fixture="lean_result_clean.json")
    cfgs = enumerate_catalog(MOCK_CATALOG)[:2]  # type: ignore[arg-type]
    d0 = adapter._run_dir(cfgs[0], W)
    d1 = adapter._run_dir(cfgs[1], W)
    w2 = Window(name="w2", start="2025-03-01", end="2025-04-30")
    d0_w2 = adapter._run_dir(cfgs[0], w2)
    # distinct per config AND per window — no cross-run collision.
    assert d0 != d1 and d0 != d0_w2 and d1 != d0_w2
    assert cfgs[0].config_hash in str(d0) and "w1" in str(d0)


def test_data_symlink_created(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path, fixture="lean_result_clean.json")
    adapter(_config(), W)
    link = adapter._run_dir(_config(), W) / "data"
    assert link.is_symlink()
    assert link.resolve() == adapter.data_root.resolve()


def test_marker_mismatch_raises(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path, fixture="lean_result_clean.json",
                       deployed_marker="expected-X", executed_marker="actual-Y")
    with pytest.raises(MarkerMismatchError, match="expected-X"):
        adapter(_config(), W)


def test_missing_code_snapshot_raises_when_marker_check(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path, fixture="lean_result_clean.json", executed_marker=None)
    with pytest.raises(MarkerMismatchError, match="no code/main.py"):
        adapter(_config(), W)


def test_marker_check_disabled_skips_verification(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path, fixture="lean_result_clean.json",
                       executed_marker=None, marker_check=False)
    m = adapter(_config(), W)  # no code snapshot, but check disabled -> OK
    assert m.orders == 8


def test_degraded_run_raises(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path, fixture="lean_result_degraded.json")
    with pytest.raises(DegradedDataError, match="orders=0"):
        adapter(_config(), W)


def test_nonzero_lean_exit_raises(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path, fixture="lean_result_clean.json", rc=1)
    with pytest.raises(ResultParseError, match="exited 1"):
        adapter(_config(), W)


def test_missing_result_json_raises(tmp_path: Path) -> None:
    # dist_builder writes nothing -> find_result has no output to locate.
    data_root = tmp_path / "data"
    data_root.mkdir()

    def empty_build(config: SweepConfig, window: Window, run_dir: Path) -> str:
        return MARKER

    adapter = LocalLeanRun(
        dist_builder=empty_build,
        data_root=data_root,
        runs_root=tmp_path / "runs",
        run_lean=lambda d: 0,
    )
    with pytest.raises(ResultParseError, match="no backtests/"):
        adapter(_config(), W)


def test_nan_result_raises(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path, fixture="lean_result_nan.json")
    with pytest.raises(ResultParseError, match="non-finite"):
        adapter(_config(), W)
