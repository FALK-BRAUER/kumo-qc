"""BASE-VALIDITY GATE (#364 hard-stop P1) — baseline-0.0 must reproduce the mainV2 champion byte-identical.

HQ's gate: if baseline-0.0 (mainV2 + the cherry-picked lever, hard_stop_pct=0.0) does NOT produce the
SAME fills as the plain mainV2 champion, the base is wrong → STOP, trust no X result. Source proof
already shows 0.0 → identical protective_stop line; this is the empirical confirmation.

Compares the FILLS (symbol, utc-time, qty, price) from two FY-full backtests' *-order-events.json:
  A = plain mainV2 champion (run in the kumo-qc-mainv2 worktree, choices=() — built body == S1-0.0)
  B = baseline-0.0 here (mainV2 + lever @0.0)
Identical fill-set → GATE PASS. Any divergence → first-difference reported, exit 1.

Usage: python3 scripts/gate_base_validity.py <ref_backtests_dir> <baseline_backtests_dir>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def _fills(backtests_dir: Path) -> list[tuple]:
    """Sorted (symbol, utc_time, fill_qty, fill_price) over filled order-events in the latest BT."""
    runs = sorted(backtests_dir.glob("*/"), key=lambda d: d.stat().st_mtime, reverse=True)
    if not runs:
        raise SystemExit(f"no backtest dir under {backtests_dir} — cannot gate (fail-loud)")
    latest = runs[0]
    oe = next(latest.glob("*-order-events.json"), None)
    if oe is None:
        raise SystemExit(f"no *-order-events.json in {latest} — missing artifact, cannot gate")
    events = json.loads(oe.read_text())
    if isinstance(events, dict):  # some LEAN versions wrap in {"orderEvents": [...]}
        events = events.get("orderEvents", events.get("order-events", []))
    fills = []
    for e in events:
        status = str(e.get("status", "")).lower()
        if status not in ("filled", "partiallyfilled"):
            continue
        sym = e.get("symbol", {})
        sym = sym.get("value", sym) if isinstance(sym, dict) else sym
        fills.append((str(sym), str(e.get("time", e.get("utcTime", ""))),
                      round(float(e.get("fillQuantity", 0)), 6), round(float(e.get("fillPrice", 0)), 4)))
    fills.sort()
    return fills


def main() -> None:
    ref_dir, base_dir = Path(sys.argv[1]), Path(sys.argv[2])
    ref, base = _fills(ref_dir), _fills(base_dir)
    print(f"=== BASE-VALIDITY GATE — mainV2-champion vs baseline-0.0 fills ===")
    print(f"  ref   (plain mainV2): {len(ref)} fills  [{ref_dir}]")
    print(f"  base  (lever @0.0):   {len(base)} fills  [{base_dir}]")
    if ref == base:
        print(f"\n  GATE PASS ✓ — {len(ref)} fills BYTE-IDENTICAL. 0.0 is the OFF-sentinel; base is clean mainV2.")
        return
    print(f"\n  GATE FAIL ✗ — fill-sets DIFFER (ref {len(ref)} vs base {len(base)}).")
    # first divergence
    for i, (a, b) in enumerate(zip(ref, base)):
        if a != b:
            print(f"  first divergence @ index {i}:\n    ref : {a}\n    base: {b}")
            break
    else:
        extra = ref[len(base):] or base[len(ref):]
        print(f"  length mismatch; tail-only-in-longer (first): {extra[0] if extra else '?'}")
    sys.exit(1)


if __name__ == "__main__":
    main()
