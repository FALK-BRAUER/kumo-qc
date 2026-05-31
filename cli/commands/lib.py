"""``kumo lib`` — shell hooks + infra keepers.

These stay as ``.sh`` files in ``scripts/`` (they are the git-hook install targets
and infra utilities — rewriting shell->python would add risk, not value). ``kumo lib``
just shells out to each, unchanged, for discoverability under one entry point:

  * ``install-hooks``   -> scripts/install-hooks.sh      (install the git hooks)
  * ``pre-commit``      -> scripts/pre-commit-hook.sh     (the pre-commit hook body)
  * ``check-defaults``  -> scripts/check-defaults.sh      (defaults guard, run by the hook)
  * ``clean-containers``-> scripts/clean-lean-containers.sh (clear stale LEAN docker containers)
  * ``preflight``       -> scripts/worker-preflight.sh    (worktree-isolation preflight gate)
"""

from __future__ import annotations

import typer

from cli.lib.runner import run_sh

app = typer.Typer(no_args_is_help=True, help="Shell hooks + infra keepers (shelled out, unchanged).")


@app.command("install-hooks")
def install_hooks() -> None:
    """Install the repo git hooks (install-hooks.sh)."""
    run_sh("install-hooks.sh")


@app.command("pre-commit")
def pre_commit() -> None:
    """Run the pre-commit hook body (pre-commit-hook.sh)."""
    run_sh("pre-commit-hook.sh")


@app.command("check-defaults")
def check_defaults() -> None:
    """Run the defaults guard (check-defaults.sh)."""
    run_sh("check-defaults.sh")


@app.command("clean-containers")
def clean_containers() -> None:
    """Clear stale LEAN docker containers (clean-lean-containers.sh)."""
    run_sh("clean-lean-containers.sh")


@app.command(
    "preflight",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def preflight(ctx: typer.Context) -> None:
    """Worktree-isolation preflight gate (worker-preflight.sh <worker_id>)."""
    run_sh("worker-preflight.sh", ctx.args)
