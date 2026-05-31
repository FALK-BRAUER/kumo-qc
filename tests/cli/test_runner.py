"""Tests for the WRAP layer (cli.lib.runner) — path resolution + exit propagation.

No real keeper is executed. We assert the repo-root/scripts resolution and that a
missing keeper raises typer.Exit(2) instead of crashing.
"""

from __future__ import annotations

import pytest
import typer

from cli.lib import runner


def test_repo_root_points_at_repo() -> None:
    # cli/lib/runner.py -> repo root contains scripts/ and build/.
    assert (runner.REPO_ROOT / "scripts").is_dir()
    assert (runner.REPO_ROOT / "build").is_dir()
    assert runner.SCRIPTS_DIR == runner.REPO_ROOT / "scripts"


def test_run_py_missing_keeper_exits_2() -> None:
    with pytest.raises(typer.Exit) as exc:
        runner.run_py("definitely_not_a_real_keeper_xyz.py")
    assert exc.value.exit_code == 2


def test_run_sh_missing_keeper_exits_2() -> None:
    with pytest.raises(typer.Exit) as exc:
        runner.run_sh("definitely_not_a_real_keeper_xyz.sh")
    assert exc.value.exit_code == 2


def test_keepers_referenced_by_cli_exist() -> None:
    """Every keeper the CLI wraps must still exist on disk (post git-rm guard)."""
    py_keepers = [
        "build_daily_from_parquet.py",
        "build_manifest.py",
        "conform_coarse.py",
        "build_etf_universe.py",
        "extend_local_data_2026.py",
        "record_bt_result.py",
        "validate_parity.py",
        "collect_results.py",
        "qc_v2_cloud.py",
        "gate.py",
        "deploy.py",
    ]
    sh_keepers = [
        "lean-bt.sh",
        "install-hooks.sh",
        "pre-commit-hook.sh",
        "check-defaults.sh",
        "clean-lean-containers.sh",
        "worker-preflight.sh",
    ]
    for name in py_keepers + sh_keepers:
        assert (runner.SCRIPTS_DIR / name).exists(), f"keeper missing: {name}"
