"""kumo — the typed operator CLI (root Typer app).

Six subcommand groups, each wrapping production-tested keepers:
  kumo data   — local backtest data substrate tooling
  kumo build  — package the active strategy closure src/ -> dist/
  kumo bt     — local backtest run + result recording + parity
  kumo deploy — QC cloud driver + the live-trading path (gate/live)
  kumo sweep  — config-permutation sweep driver (stub until #214)
  kumo lib    — shell hooks + infra keepers

Run ``kumo --help`` or ``kumo <group> --help``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import typer

# build/ holds cloud_package.py (imported by `kumo build`); src/ holds strategy
# modules it loads. Mirror pytest.ini's `pythonpath = src build` so the CLI runs
# standalone (outside pytest) too.
_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "src", _ROOT / "build"):
    _ps = str(_p)
    if _ps not in sys.path:
        sys.path.insert(0, _ps)

from cli.commands import bt as _bt  # noqa: E402
from cli.commands import build as _build  # noqa: E402
from cli.commands import data as _data  # noqa: E402
from cli.commands import deploy as _deploy  # noqa: E402
from cli.commands import lib as _lib  # noqa: E402
from cli.commands import sweep as _sweep  # noqa: E402

app = typer.Typer(
    name="kumo",
    no_args_is_help=True,
    add_completion=False,
    help="kumo — operator CLI for kumo-qc (data | build | bt | deploy | sweep | lib).",
)

app.add_typer(_data.app, name="data")
app.add_typer(_build.app, name="build")
app.add_typer(_bt.app, name="bt")
app.add_typer(_deploy.app, name="deploy")
app.add_typer(_sweep.app, name="sweep")
app.add_typer(_lib.app, name="lib")


def main() -> None:
    """Entry point for the ``kumo`` console script."""
    app()


if __name__ == "__main__":
    main()
