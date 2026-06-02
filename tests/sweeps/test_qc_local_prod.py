"""Tests for the production LOCAL adapter (#214/#325) — the DistBuilder that was the missing piece.

Builds a REAL sweep-config dist (fast, local) into a tmp run_dir and asserts the cloud-PARITY
window injection + the lean project + the fabrication marker — so the local sweep deploys correctly
+ the local-vs-cloud diff reflects data/skip, never a window-boundary mismatch.
"""
from __future__ import annotations

from pathlib import Path

from sweeps.adapters.qc_local_prod import local_dist_builder, make_local_run
from sweeps.adapters.local_lean import LocalLeanRun
from sweeps.grids.windows_fy2025 import FY2025_PANEL
from sweeps.types import PhaseChoice, SweepConfig


def _cap_config(cap: int) -> SweepConfig:
    from phases.signal.oracle_signal.oracle_signal import DvRankPredictor
    params = tuple(sorted(
        [("min_score", 7), ("parabolic_threshold", 0.25),
         ("predictor", DvRankPredictor(min_score=7, rank_cap=cap))], key=lambda kv: kv[0]
    ))
    return SweepConfig(choices=(
        PhaseChoice(kind="signal", impl_name="oracle_signal", params=params, free_params=2),
    ))


def test_local_dist_builder_window_marker_leanjson(tmp_path: Path) -> None:
    cfg = _cap_config(250)
    run_dir = tmp_path / "cell"
    marker = local_dist_builder(cfg, FY2025_PANEL[0], run_dir)  # w1_2025q1 = 2025-01-01..03-31 (#338-ws3)
    main = (run_dir / "main.py").read_text()
    # cloud-PARITY window injection: dates from the Window's ISO start/end as BCTAlgorithm class attrs.
    assert "START_DATE = (2025, 1, 1)" in main
    assert "END_DATE = (2025, 3, 31)" in main
    # config-specific fabrication marker, present + returned.
    assert marker == f"SWEEP_MARKER {cfg.config_hash}"
    assert marker in main
    # the lean project config + the codegen-fix injected-impl import.
    assert (run_dir / "lean.json").exists()
    assert "import DvRankPredictor" in main


def test_local_dist_builder_idempotent_window(tmp_path: Path) -> None:
    # a second build into the same run_dir must NOT double-inject the window (idempotent).
    cfg = _cap_config(100)
    run_dir = tmp_path / "cell"
    local_dist_builder(cfg, FY2025_PANEL[0], run_dir)
    local_dist_builder(cfg, FY2025_PANEL[0], run_dir)
    main = (run_dir / "main.py").read_text()
    assert main.count("START_DATE = (2025, 1, 1)") == 1


def test_make_local_run_wires_adapter() -> None:
    adapter = make_local_run(archive=False)
    assert isinstance(adapter, LocalLeanRun)
    assert adapter.dist_builder is local_dist_builder
    assert adapter.marker_check is True
