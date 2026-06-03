"""Retro-flag run_class on archived result.json files (Falk 2026-06-02, CONVENTIONS run-class).

The FY2021-2025 (and FY2020) substrate runs predate the run_class field — they were generated as
mine fuel (substrate-generation) but their result.json had no class declaration, so a reader could
mistake a substrate-gen full-year Sharpe for a validation grade. This ADDITIVELY stamps
run_class on any result.json under a config_hash that lacks it (or has it null), defaulting to
"substrate-generation" (the #303 substrate dirs are all substrate-gen). Idempotent + re-runnable
(re-run after FY2020 lands to flag it too). NO re-persist, NO metric change — only the class field.

Usage: python3 scripts/retroflag_run_class.py [config_hash] [run_class]
  defaults: config_hash=fd8248b34265, run_class=substrate-generation
"""
import json
import sys
from pathlib import Path

ARCHIVE = Path(__file__).resolve().parents[1] / "results" / "archive"
VALID = {"validation", "substrate-generation"}


def retroflag(config_hash, run_class):
    if run_class not in VALID:
        raise SystemExit(f"run_class must be one of {VALID}, got {run_class!r}")
    root = ARCHIVE / config_hash
    if not root.is_dir():
        raise SystemExit(f"no archive dir for config_hash {config_hash}: {root}")
    flagged, already, skipped = [], [], []
    for run_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        rj = run_dir / "result.json"
        if not rj.exists():
            skipped.append(run_dir.name)
            continue
        doc = json.loads(rj.read_text())
        if doc.get("run_class") in VALID:
            already.append((run_dir.name, doc["run_class"]))
            continue
        doc["run_class"] = run_class
        # write back with the same formatting the snapshotter uses (indent=2, sorted keys)
        rj.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
        flagged.append(run_dir.name)
    print(f"config_hash {config_hash}: flagged {len(flagged)} as run_class={run_class!r}")
    for b in flagged:
        print(f"  + {b}")
    if already:
        print(f"  ({len(already)} already classed: {already})")
    if skipped:
        print(f"  (skipped {len(skipped)} dir(s) without result.json: {skipped})")


if __name__ == "__main__":
    cfg = sys.argv[1] if len(sys.argv) > 1 else "fd8248b34265"
    rc = sys.argv[2] if len(sys.argv) > 2 else "substrate-generation"
    retroflag(cfg, rc)
