"""``kumo bt`` group tests — command resolution + typed options.

A real backtest is never run here (no LEAN/docker). Only --help is invoked.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from cli.app import app

runner = CliRunner()

BT_COMMANDS = ["run", "record", "parity", "collect"]


def test_bt_help_lists_commands() -> None:
    result = runner.invoke(app, ["bt", "--help"])
    assert result.exit_code == 0
    for cmd in BT_COMMANDS:
        assert cmd in result.stdout


@pytest.mark.parametrize("cmd", BT_COMMANDS)
def test_bt_command_help_resolves(cmd: str) -> None:
    result = runner.invoke(app, ["bt", cmd, "--help"])
    assert result.exit_code == 0


def test_bt_run_exposes_marker_option() -> None:
    result = runner.invoke(app, ["bt", "run", "--help"])
    assert result.exit_code == 0
    assert "marker" in result.stdout
