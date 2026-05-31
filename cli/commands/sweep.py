"""``kumo sweep`` — config-permutation research driver.

STUB: no keeper exists yet. Wired when #214 (sweep driver) lands. Until then the
command resolves (so the group + help are testable) but only prints a notice.
"""

from __future__ import annotations

import typer

app = typer.Typer(no_args_is_help=False, help="Config-permutation sweep driver (stub until #214).")


@app.callback(invoke_without_command=True)
def sweep(ctx: typer.Context) -> None:
    """Sweep driver — not yet wired (#214)."""
    if ctx.invoked_subcommand is not None:
        return
    typer.echo("kumo sweep: not yet wired (#214)")
