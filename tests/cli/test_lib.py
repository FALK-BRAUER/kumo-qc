"""``kumo lib`` group tests — command resolution.

These shell out to git-hook / infra scripts (install-hooks, pre-commit,
check-defaults, clean-containers, preflight). They mutate hooks / docker / git
state, so they are NOT executed here — only resolution + help is asserted.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from cli.app import app

runner = CliRunner()

LIB_COMMANDS = ["install-hooks", "pre-commit", "check-defaults", "clean-containers", "preflight"]


def test_lib_help_lists_commands() -> None:
    result = runner.invoke(app, ["lib", "--help"])
    assert result.exit_code == 0
    for cmd in LIB_COMMANDS:
        assert cmd in result.stdout


@pytest.mark.parametrize("cmd", LIB_COMMANDS)
def test_lib_command_help_resolves(cmd: str) -> None:
    result = runner.invoke(app, ["lib", cmd, "--help"])
    assert result.exit_code == 0
