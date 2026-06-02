"""Provenance + ledger (#214 component 7) — pin every result to (commit, config, data).

Charter (CONVENTIONS §Parity / §Build: "Every result is pinned to (git commit + config-hash
+ data-fingerprint)"; the 1.079-not-pinned-to-its-data lesson). NO result enters the ledger
without all three. This module:

  - Provenance: stamps a scored result with the git commit, the config-hash (from the
    SweepConfig itself), and the data fingerprint (the substrate the run used). Reuses the
    dist/_metadata provenance triple SHAPE (GIT_COMMIT / CONFIG_HASH / DATA_FINGERPRINT) and
    digest discipline — but the config-hash is NOT cross-matchable to a built-dist config-hash
    (different inputs: the dist hash also folds name+version+per-slot enabled). Same format,
    not interchangeable; compare sweep-to-sweep and dist-to-dist, never across.
  - Ledger: writes the master results rows to results/ in the canonical schema
    (results/README): config_hash · data_fingerprint · commit · bt_id · marker · sharpe ·
    ret_pct · dd_pct · orders · window · verdict. Round-trips (write -> read -> identical).

A sweep emits ONE ledger row per (config, window) — the per-window metrics are the atomic
ledgered facts (the distribution lives in the leaderboard; the ledger is the audit trail of
the underlying backtests). `verdict` is the promotion decision (e.g. "sweep" for a raw sweep
row, "promoted" once a winner graduates into results/bt-results.csv).
"""
from __future__ import annotations

import csv
import io
import subprocess
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from sweeps.types import ConfigRun

LEDGER_COLUMNS = (
    "config_hash",
    "data_fingerprint",
    "commit",
    "bt_id",
    "marker",
    "sharpe",
    "ret_pct",
    "dd_pct",
    "orders",
    "window",
    "verdict",
)


@dataclass(frozen=True, slots=True)
class Provenance:
    """The mandatory pinning triple for any ledgered result (+ run marker).

    `commit` = git HEAD when the run was produced; `config_hash` = the SweepConfig digest;
    `data_fingerprint` = the substrate (data/MANIFEST.json fingerprint) the run consumed.
    `marker` = the run's version marker (e.g. the phase version_marker / a run id), the
    fabrication guard so a row traces to a real artifact (CLAUDE.md data-integrity rule).
    """

    commit: str
    config_hash: str
    data_fingerprint: str
    marker: str

    def validate(self) -> None:
        """Refuse incomplete pinning — a row missing any of the triple is invalid."""
        missing = [
            name
            for name, val in (
                ("commit", self.commit),
                ("config_hash", self.config_hash),
                ("data_fingerprint", self.data_fingerprint),
            )
            if not val
        ]
        if missing:
            raise ValueError(
                f"incomplete provenance — missing {missing}. A result without "
                "(commit + config-hash + data-fingerprint) is NOT valid "
                "(the 1.079-not-pinned-to-its-data lesson)."
            )


@dataclass(frozen=True, slots=True)
class LedgerRow:
    """One ledger row = one (config, window) backtest fact, fully pinned."""

    config_hash: str
    data_fingerprint: str
    commit: str
    bt_id: str
    marker: str
    sharpe: float
    ret_pct: float
    dd_pct: float
    orders: int
    window: str
    verdict: str


def git_commit(repo_root: Path | None = None) -> str:
    """Current git HEAD (full sha). The code pin of the provenance triple."""
    cwd = str(repo_root) if repo_root is not None else None
    out = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip()


def git_branch(repo_root: Path | None = None) -> str:
    """Current git branch (abbreviated ref). For the bt-results `branch` column. Detached HEAD →
    'HEAD'; never raises into the caller's path on a benign read (returns 'unknown' on failure)."""
    cwd = str(repo_root) if repo_root is not None else None
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=cwd, capture_output=True, text=True, check=True,
        )
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def ledger_rows(
    run: ConfigRun,
    provenance: Provenance,
    *,
    bt_id: str,
    verdict: str = "sweep",
) -> list[LedgerRow]:
    """Expand one ConfigRun into per-window ledger rows, each fully pinned.

    Validates the provenance triple first (no unpinned row). `bt_id` identifies the sweep
    run; `marker` comes from the provenance (run/version marker). The per-config config_hash
    is taken from the SweepConfig, NOT the provenance, and asserted to match — a mismatch
    means the provenance was stamped against a different config (fail loud).
    """
    provenance.validate()
    if provenance.config_hash != run.config.config_hash:
        raise ValueError(
            f"provenance config_hash {provenance.config_hash} != run config_hash "
            f"{run.config.config_hash} — provenance stamped against the wrong config."
        )
    rows: list[LedgerRow] = []
    for wr in run.window_results:
        m = wr.metrics
        rows.append(
            LedgerRow(
                config_hash=run.config.config_hash,
                data_fingerprint=provenance.data_fingerprint,
                commit=provenance.commit,
                bt_id=f"{bt_id}:{wr.window.name}",
                marker=provenance.marker,
                sharpe=m.sharpe,
                ret_pct=m.ret_pct,
                dd_pct=m.dd_pct,
                orders=m.orders,
                window=wr.window.name,
                verdict=verdict,
            )
        )
    return rows


def to_csv(rows: Sequence[LedgerRow], *, include_header: bool = True) -> str:
    """Serialise ledger rows to CSV in the canonical schema (results/README)."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    if include_header:
        writer.writerow(LEDGER_COLUMNS)
    for r in rows:
        writer.writerow(
            (
                r.config_hash,
                r.data_fingerprint,
                r.commit,
                r.bt_id,
                r.marker,
                r.sharpe,
                r.ret_pct,
                r.dd_pct,
                r.orders,
                r.window,
                r.verdict,
            )
        )
    return buf.getvalue()


def from_csv(text: str) -> list[LedgerRow]:
    """Parse ledger CSV back into rows (the round-trip inverse of to_csv)."""
    reader = csv.DictReader(io.StringIO(text))
    rows: list[LedgerRow] = []
    for rec in reader:
        rows.append(
            LedgerRow(
                config_hash=rec["config_hash"],
                data_fingerprint=rec["data_fingerprint"],
                commit=rec["commit"],
                bt_id=rec["bt_id"],
                marker=rec["marker"],
                sharpe=float(rec["sharpe"]),
                ret_pct=float(rec["ret_pct"]),
                dd_pct=float(rec["dd_pct"]),
                orders=int(rec["orders"]),
                window=rec["window"],
                verdict=rec["verdict"],
            )
        )
    return rows


def write_ledger(path: Path, rows: Sequence[LedgerRow], *, append: bool = False) -> None:
    """Write (or append) ledger rows to a CSV file in the canonical schema.

    Append mode omits the header when the file already exists (the master ledger grows by
    appending sweep rows; the header is written once on creation).
    """
    file_exists = path.exists()
    header = not (append and file_exists)
    mode = "a" if append and file_exists else "w"
    with path.open(mode, newline="", encoding="utf-8") as fh:
        fh.write(to_csv(rows, include_header=header))


def read_ledger(path: Path) -> list[LedgerRow]:
    """Read a ledger CSV file back into rows."""
    return from_csv(path.read_text(encoding="utf-8"))
