"""kumo — the operator CLI for kumo-qc.

One typed Typer entry point with six subcommand groups
(data | build | bt | deploy | sweep | lib). Each WRAPS an existing,
production-tested keeper (scripts/*.py / *.sh or build/cloud_package.py)
rather than reimplementing its logic — behavior is preserved verbatim.

Dev tooling only; NOT shipped to dist/.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
