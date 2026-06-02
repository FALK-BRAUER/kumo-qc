"""#10 storage-uniformity — MAIN-SIDE merge of worktree-local sweep indices into bt-results.csv.

bt-results.csv is single-writer on `main`. A sweep (in a worktree) writes results/sweeps/<grid>/
sweep_index.csv (bt-results format). This tool — run ON MAIN — reads those indices and dedup-appends
new rows into bt-results.csv. Idempotent: a row already present (by the dedup key) is skipped, so
re-running never duplicates. The archive is the source of truth; this only refreshes the flat index.

Dedup key = (commit, window, config-from-notes) — the unique (code, period, config) identity of a
cell. bt-results.csv is regenerable from the archive, so this is a convenience projection, not a
ledger of record.

Usage (on main):  python3 scripts/merge_sweep_index.py [--dry-run] [<index.csv> ...]
With no paths, globs results/sweeps/*/sweep_index.csv.
"""
from __future__ import annotations

import csv
import glob
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
BT_RESULTS = _ROOT / "bt-results.csv"
_CONFIG_RE = re.compile(r"config=(\w+)")


def _key(row: dict[str, str]) -> tuple[str, str, str]:
    """(commit, window, config) — the cell identity. config parsed from the notes tag (sweep rows)."""
    m = _CONFIG_RE.search(row.get("notes", "") or "")
    return (row.get("commit", ""), row.get("window", ""), m.group(1) if m else "")


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="") as fh:
        reader = csv.DictReader(fh)
        return (reader.fieldnames or []), list(reader)


def merge(index_paths: list[Path], *, dry_run: bool = False, bt_results: Path = BT_RESULTS) -> int:
    """Append non-duplicate index rows into bt-results.csv. Returns the count of rows added."""
    if not bt_results.exists():
        raise SystemExit(f"{bt_results} not found — run on the main worktree (single-writer).")
    header, existing = _read_csv(bt_results)
    seen = {_key(r) for r in existing}

    new_rows: list[dict[str, str]] = []
    for p in index_paths:
        _, rows = _read_csv(p)
        for row in rows:
            k = _key(row)
            if k in seen:
                continue
            seen.add(k)
            new_rows.append(row)

    if not new_rows:
        print("merge_sweep_index: 0 new rows (all present) — bt-results.csv unchanged.")
        return 0
    print(f"merge_sweep_index: {len(new_rows)} new row(s) from {len(index_paths)} index file(s).")
    if dry_run:
        for r in new_rows:
            print(f"  + {r.get('commit','')[:8]} {r.get('window','')} {r.get('notes','')[:60]}")
        return len(new_rows)

    with bt_results.open("a", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=header, extrasaction="ignore")
        for row in new_rows:
            writer.writerow({c: row.get(c, "") for c in header})
    print(f"merge_sweep_index: appended {len(new_rows)} row(s) to {bt_results}.")
    return len(new_rows)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--dry-run"]
    dry = "--dry-run" in sys.argv[1:]
    paths = [Path(a) for a in args] or [Path(p) for p in glob.glob(str(_ROOT / "results/sweeps/*/sweep_index.csv"))]
    if not paths:
        raise SystemExit("no sweep_index.csv files found (results/sweeps/*/sweep_index.csv).")
    merge(paths, dry_run=dry)
