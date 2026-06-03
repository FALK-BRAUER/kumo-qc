"""#358 — write the offline weekly cache → a LEAN LocalObjectStore key (the in-container delivery).

Reads the #332 per-symbol jsonl cache (``results/warmup_cache/<fp>/*.jsonl``), extracts the 6 weekly
Ichimoku scalars per (sym, date), and writes the ObjectStore blob (loader.dump_weekly_blob) to
``<storage>/<key>``. The LOCAL harness then sets ``WARMUP_WEEKLY_CACHE_KEY=<key>`` +
``WARMUP_WEEKLY_CACHE_FP=<fp>``; the runtime reads it via ``self.object_store`` and skips the
per-decision history(560d) weekly re-derivation.

LOCAL-ONLY: this key is a perf accelerator — NEVER upload it to the cloud project (cloud's
ObjectStore won't have the key → contains_key False → fail-closed → live re-derive). The embedded
fingerprint is the second guard.

Usage:
  python3 scripts/write_weekly_objectstore.py --fp <data_fingerprint> [--cache-root results/warmup_cache]
                                              [--storage ./storage] [--key warmup_weekly_cache]
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_ROOT), str(_ROOT / "src")]

# SHARED key formula + serializer from src/ (bundled) → write_key == read_key, one source.
from runtime.warmup_weekly_cache import WEEKLY_FIELDS, dump_weekly_blob, weekly_cache_key  # noqa: E402


def _load_jsonl_weekly(cache_dir: Path) -> dict[str, dict[_dt.date, dict[str, float]]]:
    """Read the per-symbol jsonl cache → {SYM: {date: {6 weekly}}}. Fail-loud on a missing dir."""
    if not cache_dir.is_dir():
        raise SystemExit(f"cache dir not found: {cache_dir} — run build_warmup_cache.py first (fail-loud)")
    syms: dict[str, dict[_dt.date, dict[str, float]]] = {}
    for jf in sorted(cache_dir.glob("*.jsonl")):
        rows: dict[_dt.date, dict[str, float]] = {}
        for line in jf.read_text().splitlines():
            if not line:
                continue
            r = json.loads(line)
            rows[_dt.date.fromisoformat(r["date"])] = {k: float(r[k]) for k in WEEKLY_FIELDS}
        if rows:
            syms[jf.stem.upper()] = rows
    if not syms:
        raise SystemExit(f"no rows loaded from {cache_dir} (fail-loud)")
    return syms


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fp", required=True, help="data fingerprint (cache dir name + embedded guard)")
    ap.add_argument("--cache-root", default=str(_ROOT / "results" / "warmup_cache"))
    ap.add_argument("--storage", default=str(_ROOT / "storage"), help="LEAN LocalObjectStore dir")
    args = ap.parse_args()

    cache_dir = Path(args.cache_root) / args.fp
    syms = _load_jsonl_weekly(cache_dir)

    # PER-SYMBOL keys: one ObjectStore key per symbol (weekly_cache_key(fp, SYM)) so the runtime
    # lazy-loads only the active names it queries — full coverage, no 1.8GB single-blob OOM.
    storage = Path(args.storage)
    storage.mkdir(parents=True, exist_ok=True)
    total_rows = total_bytes = 0
    for sym, rows in syms.items():
        blob = dump_weekly_blob({sym: rows}, args.fp)  # single-symbol blob (round-trips via parse)
        keyfile = storage / weekly_cache_key(args.fp, sym)  # DERIVED — same formula the runtime reads
        keyfile.write_text(blob)
        total_rows += len(rows)
        total_bytes += len(blob)
    print(json.dumps({
        "scheme": "per-symbol", "fp": args.fp, "keys": len(syms),
        "rows": total_rows, "bytes": total_bytes, "storage": str(storage),
        "sample_key": weekly_cache_key(args.fp, next(iter(syms))) if syms else None,
    }, indent=1))


if __name__ == "__main__":
    main()
