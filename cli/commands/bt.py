"""``kumo bt`` — local backtest run + result recording + parity.

Wraps the backtest keepers (each runs verbatim via :mod:`cli.lib.runner`):
  * ``run``     -> scripts/lean-bt.sh        (serialized local LEAN runner; shell — shelled out)
  * ``record``  -> scripts/record_bt_result.py (record a BT result to the store)
  * ``parity``  -> scripts/validate_parity.py  (local vs cloud parity check)
  * ``collect`` -> scripts/collect_results.py   (collect BT results)
"""

from __future__ import annotations

import typer

from cli.lib.runner import run_py, run_sh

app = typer.Typer(no_args_is_help=True, help="Local backtest run + result recording + parity.")


@app.command(
    "run",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def run(
    ctx: typer.Context,
    marker: str = typer.Option(
        "", "--marker", help="VERSION_MARKER substring the run's code must contain (MARKER env)."
    ),
) -> None:
    """Run a local LEAN backtest, serialized machine-wide (lean-bt.sh).

    All positional/extra args are forwarded verbatim to lean-bt.sh, e.g.
    ``kumo bt run algorithm/performance_bct --parameter foo bar``.
    """
    env_extra = {"MARKER": marker} if marker else None
    run_sh("lean-bt.sh", ctx.args, env_extra=env_extra)


@app.command("record")
def record(
    args: list[str] = typer.Argument(
        None, help="Flags forwarded to record_bt_result.py (e.g. --bt-id --window --status ...)."
    ),
) -> None:
    """Record a backtest result to the store (record_bt_result.py)."""
    run_py("record_bt_result.py", args)


@app.command("parity")
def parity(
    args: list[str] = typer.Argument(
        None, help="Args forwarded to validate_parity.py (local_json cloud_json [--tolerance ...])."
    ),
) -> None:
    """Validate local vs cloud parity for a pair of result JSONs (validate_parity.py)."""
    run_py("validate_parity.py", args)


@app.command("collect")
def collect() -> None:
    """Collect backtest results (collect_results.py)."""
    run_py("collect_results.py")
