"""``kumo build`` group tests — resolution only.

The build command imports build/cloud_package and writes dist/; we do NOT run it.
Only --help is invoked (resolution + the typed STRATEGY_MODULE arg + --verbose flag).
"""

from __future__ import annotations

from typer.testing import CliRunner

from cli.app import app

runner = CliRunner()


def test_build_help_resolves() -> None:
    result = runner.invoke(app, ["build", "--help"])
    assert result.exit_code == 0
    assert "STRATEGY_MODULE" in result.stdout
    # --verbose/--quiet flag is exposed.
    assert "verbose" in result.stdout or "quiet" in result.stdout
