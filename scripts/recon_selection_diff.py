"""Reconciliation: local-vs-cloud trade-SELECTION diff + skip-ledger intersection (#325 gate).

The gate between fast-local-sweep and trustworthy-local-sweep (CONVENTIONS). Compares the symbols a
config traded LOCALLY vs CLOUD on the SAME window, and classifies any mismatch:
  - in the skip-ledger (a spacing-guard-skipped ticker-day) → skip-divergence (expected, bounded).
  - NOT in the skip-ledger → a DIFFERENT cause: vendor-residual at a decision margin (the #173
    cloud-vs-local data delta flipping a borderline gap-confirm), OR a real bug to surface.

Inputs (all VERIFIED artifacts, never assumed):
  --cloud   /tmp/val_<label>.json  (validate_run.py output: cloud orders, symbol dicts)
  --local   the LEAN backtest dir (algorithm/.../backtests/<ts>/) — reads <id>-order-events.json
  --skiplog the backfill log with SKIP lines (default /tmp/backfill_325.log)
Usage: python3 scripts/recon_selection_diff.py --cloud /tmp/val_recon-sep.json --local <bt_dir>
"""
import argparse
import glob
import json
import re
from collections import defaultdict
from pathlib import Path


def _cloud_symbols(path: Path) -> set[str]:
    d = json.loads(path.read_text())
    out: set[str] = set()
    for o in d.get("orders", []):
        s = o.get("symbol")
        v = (s.get("value") if isinstance(s, dict) else s) or ""
        if v:
            out.add(str(v).lower())
    return out


def _local_filled_symbols(bt_dir: Path) -> set[str]:
    ev_files = glob.glob(str(bt_dir / "*-order-events.json"))
    if not ev_files:
        raise SystemExit(f"no *-order-events.json under {bt_dir}")
    ev = json.loads(Path(ev_files[0]).read_text())
    evs = ev if isinstance(ev, list) else ev.get("order-events", ev.get("orderEvents", []))
    out: set[str] = set()
    for e in evs:
        if str(e.get("status", "")).lower() in ("filled", "partiallyfilled"):
            out.add(str(e.get("symbol", "")).split()[0].lower())
    return out


def _skip_ledger(path: Path) -> dict[str, set[str]]:
    skips: dict[str, set[str]] = defaultdict(set)
    if not path.exists():
        return skips
    for line in path.read_text().splitlines():
        m = re.search(r"SKIP (\S+) (\d{4})(\d{2})(\d{2})", line)
        if m:
            skips[m.group(1).lower()].add(f"{m.group(2)}-{m.group(3)}-{m.group(4)}")
    return skips


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cloud", required=True)
    ap.add_argument("--local", required=True)
    ap.add_argument("--skiplog", default="/tmp/backfill_325.log")
    a = ap.parse_args()

    cloud = _cloud_symbols(Path(a.cloud))
    local = _local_filled_symbols(Path(a.local))
    skips = _skip_ledger(Path(a.skiplog))

    both = cloud & local
    union = cloud | local
    cloud_only = cloud - local
    local_only = local - cloud
    print(f"selection-match: {len(both)}/{len(union)} = {len(both)/len(union)*100:.0f}%" if union else "no trades")
    print(f"BOTH: {sorted(both)}")
    print(f"CLOUD-only (local missed): {sorted(cloud_only)}")
    print(f"LOCAL-only (cloud missed): {sorted(local_only)}")
    for t in sorted(cloud_only | local_only):
        in_skip = t in skips
        print(f"  {t}: {'SKIP-DIVERGENCE (in skip-ledger, expected)' if in_skip else 'NOT a skip → vendor-residual at margin OR bug — investigate'}")


if __name__ == "__main__":
    main()
