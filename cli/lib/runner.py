"""Subprocess runners — the WRAP layer.

Every keeper is executed AS-IS (its own ``__main__`` block runs verbatim), so
its production-tested logic is preserved byte-for-byte. The CLI only resolves
the keeper's path, forwards args, and propagates the exit code. No keeper
internals are reimplemented here.

Two runners:
  * ``run_py``  — run ``scripts/<name>.py`` with the SAME interpreter that runs
                  the CLI (so it inherits the active venv).
  * ``run_sh``  — run ``scripts/<name>.sh`` (or any tracked shell keeper) via bash,
                  forwarding env (e.g. MARKER for lean-bt.sh).

Both stream stdout/stderr straight through (no capture) and ``raise typer.Exit``
with the child's exit code, so ``kumo`` is a transparent pass-through.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from collections.abc import Mapping, Sequence

import typer

# cli/lib/runner.py -> repo root is two parents up from this file's dir (cli/).
REPO_ROOT: Path = Path(__file__).resolve().parents[2]
SCRIPTS_DIR: Path = REPO_ROOT / "scripts"
BUILD_DIR: Path = REPO_ROOT / "build"


def _exec(argv: Sequence[str], *, env_extra: Mapping[str, str] | None = None) -> int:
    """Run ``argv`` from the repo root, streaming I/O. Returns the exit code."""
    import os

    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    proc = subprocess.run(  # noqa: S603 — args are CLI-controlled keeper paths
        list(argv),
        cwd=str(REPO_ROOT),
        env=env,
        check=False,
    )
    return proc.returncode


def run_py(script_name: str, args: Sequence[str] | None = None) -> None:
    """Execute ``scripts/<script_name>`` with the current Python interpreter.

    ``script_name`` may be a bare name (``"build_manifest.py"``) resolved under
    ``scripts/``, or an absolute/relative path (used by ``kumo build``).
    """
    target = Path(script_name)
    if not target.is_absolute() and target.parent == Path("."):
        target = SCRIPTS_DIR / script_name
    if not target.exists():
        typer.secho(f"keeper not found: {target}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)
    code = _exec([sys.executable, str(target), *(args or [])])
    if code != 0:
        raise typer.Exit(code=code)


def run_sh(
    script_name: str,
    args: Sequence[str] | None = None,
    *,
    env_extra: Mapping[str, str] | None = None,
) -> None:
    """Execute ``scripts/<script_name>`` (a shell keeper) via bash, unchanged."""
    target = SCRIPTS_DIR / script_name
    if not target.exists():
        typer.secho(f"keeper not found: {target}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)
    code = _exec(["bash", str(target), *(args or [])], env_extra=env_extra)
    if code != 0:
        raise typer.Exit(code=code)
