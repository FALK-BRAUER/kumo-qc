"""``kumo data`` group tests — command resolution + typed options.

Read-only: only --help is invoked. The data keepers are NOT executed (they write
zips / fetch yfinance); we assert wiring + that each command resolves.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from cli.app import app

runner = CliRunner()

DATA_COMMANDS = ["build-daily", "manifest", "conform-coarse", "etf-universe", "extend"]


def test_data_help_lists_commands() -> None:
    result = runner.invoke(app, ["data", "--help"])
    assert result.exit_code == 0
    for cmd in DATA_COMMANDS:
        assert cmd in result.stdout


@pytest.mark.parametrize("cmd", DATA_COMMANDS)
def test_data_command_help_resolves(cmd: str) -> None:
    result = runner.invoke(app, ["data", cmd, "--help"])
    assert result.exit_code == 0
