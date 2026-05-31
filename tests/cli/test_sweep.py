"""``kumo sweep`` group tests — stub behavior (#214 not yet landed).

Safe to invoke: the stub only prints a notice (no keeper, no side effects).
"""

from __future__ import annotations

from typer.testing import CliRunner

from cli.app import app

runner = CliRunner()


def test_sweep_help_resolves() -> None:
    result = runner.invoke(app, ["sweep", "--help"])
    assert result.exit_code == 0


def test_sweep_stub_prints_not_wired() -> None:
    result = runner.invoke(app, ["sweep"])
    assert result.exit_code == 0
    assert "not yet wired" in result.stdout
    assert "#214" in result.stdout
