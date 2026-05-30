#!/usr/bin/env python3
"""Precompute step 2 of 2 — RANK + CAP (#220, rescoped).

ARCH2 universe pipeline: filter (build_filter.py, #233) -> rank+cap (THIS, #220).
Seam (B): reads the ELIGIBLE artifact (date -> {ticker -> trailing_mean_dv}) produced by
build_filter.py and turns it into the RANKED CANDIDATE artifact the universe phase
consumes at runtime. No substrate re-read — the DV needed for ranking is carried in the
eligible artifact.

filter -> RANK -> CAP:
  RANK each date's eligible tickers by trailing-mean dollar-volume DESC (baseline
        criterion — not ideal, improved later; deterministic).
  TIES  break by ticker ASC (never alphabetical as the PRIMARY key — that was the #182
        scar: local=alphabetical vs cloud=volume -> divergent sets).
  CAP   to coarse_max (param, default 9999 = effectively unbounded). This is universe
        SCAN BREADTH, NOT a position/slot count — distinct from the charter's "no count
        caps" (which forbids position/slot/max-hold caps). "No fixed universe" forbids a
        FROZEN snapshot (the 326), NOT a dynamic rank/cap.

THE #182 FIX: the rank+cap is DETERMINISTIC and the output list is stored in RANK ORDER
(never alphabetical), so local and cloud scan the SAME set in the SAME order from day 1.
The order fingerprint (sha256 over date->LIST, order-sensitive) pins it; compare it to
the cloud build to prove parity. SELECTION still happens downstream (bct_score_full,
score>=7); this stage only bounds the scan.

OUTPUT: data/universe/<auto>.json -> {"YYYY-MM-DD": [ranked tickers], ..., "_universe_meta": {...}}
Sibling .meta.json -> params + order fingerprint. Every date from the filter artifact is
preserved (empty list stays empty) — no silent gap (#182). NO timestamp (Date.now blocked).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Single-source the fingerprint algorithm: build-time order_hash MUST equal the load-time
# verify in runtime/lean_entry.py (the anti-#182 fp guardrail). Never reimplement here.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from runtime.fingerprints import order_hash  # noqa: E402


def load_filter_artifact(path: Path) -> dict[str, dict[str, float]]:
    """Read build_filter.py output: {date -> {ticker -> dv}}. Strips the _filter_meta key."""
    if not path.exists():
        raise SystemExit(f"filter artifact not found: {path} (run build_filter.py first)")
    raw = json.loads(path.read_text())
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def rank_and_cap(
    eligible: dict[str, dict[str, float]],
    coarse_max: int = 9999,
) -> dict[str, list[str]]:
    """Return {date -> [tickers in rank order]}: eligible tickers sorted by DV desc
    (tiebreak ticker asc), capped to coarse_max. Empty dates stay empty.

    Deterministic by construction: sort key is (-dv, ticker), so equal-DV ties resolve
    alphabetically and the result is independent of dict iteration order (the #182
    determinism property — identical local+cloud).
    """
    out: dict[str, list[str]] = {}
    for date in sorted(eligible):
        day = eligible[date]
        if not day:
            out[date] = []
            continue
        ranked = sorted(day.items(), key=lambda kv: (-kv[1], kv[0]))
        out[date] = [t for t, _dv in ranked[:coarse_max]]
    return out


def auto_out_name(coarse_max: int) -> str:
    return f"universe_ranked_n{coarse_max}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--filter-artifact", type=Path, required=True,
                    help="path to build_filter.py output (date -> {ticker -> dv})")
    ap.add_argument("--coarse-max", type=int, default=9999,
                    help="cap on candidates per day after DV-desc rank (scan breadth; 9999 = unbounded)")
    ap.add_argument("--out", type=Path, default=None, help="output JSON path (auto under data/universe if omitted)")
    args = ap.parse_args(argv)

    eligible = load_filter_artifact(args.filter_artifact)
    universe = rank_and_cap(eligible, coarse_max=args.coarse_max)

    fingerprint = order_hash(universe)
    params: dict[str, Any] = {
        "filter_artifact": str(args.filter_artifact),
        "coarse_max": args.coarse_max,
    }

    out_path = args.out
    if out_path is None:
        out_path = Path("data/universe") / (auto_out_name(args.coarse_max) + ".json")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    meta_block = {
        "model": "rank+cap (#220): DV-desc rank, ticker-asc tiebreak, coarse_max cap; rank order stored, identical local+cloud",
        "params": params,
        "coarse_max": args.coarse_max,
        "filter_artifact": str(args.filter_artifact),
        "order_fingerprint": fingerprint,
        "num_dates": len(universe),
    }

    payload: dict[str, Any] = {date: universe[date] for date in sorted(universe)}
    payload["_universe_meta"] = meta_block
    out_path.write_text(json.dumps(payload, separators=(",", ":"), sort_keys=False))

    meta_path = out_path.with_suffix(".meta.json")
    meta_path.write_text(json.dumps(meta_block, indent=2, sort_keys=True))

    print(f"wrote {out_path} ({len(universe)} trading dates)")
    print(f"wrote {meta_path}")
    print(f"order_fingerprint: {fingerprint}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
