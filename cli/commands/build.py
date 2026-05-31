"""``kumo build`` — package the active strategy's phase closure src/ -> dist/.

Wraps ``build/cloud_package.py``. Unlike the other groups (which subprocess the
keeper), the build keeper already exposes a clean, typed, importable
``build(strategy_module, *, dist_dir, verbose) -> BuildResult``, so the CLI
imports and calls it directly — no behavior change, the closure logic is untouched.
"""

from __future__ import annotations

import typer

app = typer.Typer(no_args_is_help=False, help="Package the active strategy closure src/ -> dist/.")


@app.callback(invoke_without_command=True)
def build(
    strategy_module: str = typer.Argument(
        "strategies._build_sample",
        help="Dotted strategy module to package (defaults to the build sample fixture).",
    ),
    verbose: bool = typer.Option(True, "--verbose/--quiet", help="Print closure + manifest detail."),
) -> None:
    """Build the AST closure of the strategy's enabled phases into dist/ (cloud_package.build)."""
    # Lazy import: pulls src/build deps + strategy module only when actually building,
    # keeping `kumo --help` fast and import-safe.
    from cloud_package import build as _build  # type: ignore[import-not-found]

    result = _build(strategy_module, verbose=verbose)
    typer.echo(f"built {strategy_module} -> dist/ ({result})")
