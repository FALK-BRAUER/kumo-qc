"""``kumo data`` — local backtest data substrate tooling.

Wraps the data keepers (each runs verbatim via :mod:`cli.lib.runner`):
  * ``build-daily``   -> scripts/build_daily_from_parquet.py  (RAW daily zips from SIP parquet)
  * ``manifest``      -> scripts/build_manifest.py            (data/MANIFEST.json fingerprint)
  * ``conform-coarse``-> scripts/conform_coarse.py            (local coarse-fundamental CSVs)
  * ``etf-universe``  -> scripts/build_etf_universe.py        (ETF LEAN data + universe JSON)
  * ``extend``        -> scripts/extend_local_data_2026.py    (re-homed: extend the data window)
"""

from __future__ import annotations

import typer

from cli.lib.runner import run_py

app = typer.Typer(no_args_is_help=True, help="Local backtest data substrate tooling.")

# Keepers that take no CLI args (read hardcoded/local config). We forward nothing.
# Keepers with argparse (manifest, conform-coarse) accept a passthrough arg list.


@app.command("build-daily")
def build_daily() -> None:
    """Rebuild LEAN daily equity zips from RAW intraday SIP parquet (build_daily_from_parquet.py)."""
    run_py("build_daily_from_parquet.py")


@app.command("manifest")
def manifest(
    args: list[str] = typer.Argument(
        None, help="Flags forwarded to build_manifest.py (e.g. --mode --out --data-dir)."
    ),
) -> None:
    """Generate data/MANIFEST.json — the substrate fingerprint (build_manifest.py)."""
    run_py("build_manifest.py", args)


@app.command("conform-coarse")
def conform_coarse(
    args: list[str] = typer.Argument(
        None, help="Flags forwarded to conform_coarse.py (e.g. --start --end YYYYMMDD)."
    ),
) -> None:
    """Regenerate local LEAN coarse-fundamental CSVs in QC-standard format (conform_coarse.py)."""
    run_py("conform_coarse.py", args)


@app.command("etf-universe")
def etf_universe() -> None:
    """Build ETF LEAN data + etf_universe_fy2025.json from Parquet (build_etf_universe.py)."""
    run_py("build_etf_universe.py")


@app.command("extend")
def extend() -> None:
    """Extend local LEAN daily data forward as the window moves (extend_local_data_2026.py)."""
    run_py("extend_local_data_2026.py")
