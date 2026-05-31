"""``kumo deploy`` — QC cloud driver + the LIVE-TRADING path.

Wraps three keepers, each invoked VERBATIM as a subprocess so their gate/safety
logic is byte-for-byte unchanged (they read the keychain; they touch real accounts).
NO option parsing or guard is reimplemented here — args pass straight through:

  * ``cloud`` -> scripts/qc_v2_cloud.py  (v2 cloud driver: deploy|run|orders|stepA)
  * ``gate``  -> scripts/gate.py         (re-homed: live-trading gate, Phase 5/7)
  * ``live``  -> scripts/deploy.py       (re-homed: live IBKR deploy)

The gate/live commands are the live-account path. The CLI is a thin transparent
pass-through; it never decides anything for them.
"""

from __future__ import annotations

import typer

from cli.lib.runner import run_py

app = typer.Typer(no_args_is_help=True, help="QC cloud driver + the live-trading path (gate/live).")


@app.command(
    "cloud",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def cloud(ctx: typer.Context) -> None:
    """Run the v2 QC cloud driver (qc_v2_cloud.py) — forwards: deploy | run | orders | stepA."""
    run_py("qc_v2_cloud.py", ctx.args)


@app.command(
    "gate",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def gate(ctx: typer.Context) -> None:
    """Live-trading gate (gate.py). Forwards: status | lock | unlock. Safety logic UNCHANGED."""
    run_py("gate.py", ctx.args)


@app.command(
    "live",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def live(ctx: typer.Context) -> None:
    """Live IBKR deploy (deploy.py). Forwards e.g. --dry. Gate + account checks UNCHANGED."""
    run_py("deploy.py", ctx.args)
