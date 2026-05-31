"""``kumo deploy`` group tests — RESOLUTION ONLY.

This group wraps the live-trading path (gate.py / deploy.py) + the QC cloud driver.
These touch real accounts / the keychain / the cloud, so they are NEVER executed
in tests — we assert only that the commands resolve and their help renders.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from cli.app import app

runner = CliRunner()

DEPLOY_COMMANDS = ["cloud", "gate", "live"]


def test_deploy_help_lists_commands() -> None:
    result = runner.invoke(app, ["deploy", "--help"])
    assert result.exit_code == 0
    for cmd in DEPLOY_COMMANDS:
        assert cmd in result.stdout


@pytest.mark.parametrize("cmd", DEPLOY_COMMANDS)
def test_deploy_command_help_resolves(cmd: str) -> None:
    result = runner.invoke(app, ["deploy", cmd, "--help"])
    assert result.exit_code == 0
