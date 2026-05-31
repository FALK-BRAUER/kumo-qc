"""App-level wiring tests for the kumo CLI (#221).

Verifies the Typer app builds, every group + command resolves via --help, and
the six expected groups are present. No keeper is executed here (those are
subprocess-invoked; see per-group resolution tests).
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from cli.app import app

runner = CliRunner()

GROUPS = ["data", "build", "bt", "deploy", "sweep", "lib"]


def test_app_help_lists_all_six_groups() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for group in GROUPS:
        assert group in result.stdout


@pytest.mark.parametrize("group", GROUPS)
def test_group_help_resolves(group: str) -> None:
    result = runner.invoke(app, [group, "--help"])
    assert result.exit_code == 0


def test_no_args_shows_help() -> None:
    # no_args_is_help=True -> exit 0 (or 2) with usage; never a crash.
    result = runner.invoke(app, [])
    assert result.exit_code in (0, 2)
    assert "Usage" in result.stdout or "kumo" in result.stdout
