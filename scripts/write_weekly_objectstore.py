"""#358 — write the offline weekly cache → a LEAN LocalObjectStore key (the in-container delivery).

Reads the #332 per-symbol jsonl cache (``results/warmup_cache/<fp>/*.jsonl``), extracts the 6 weekly
Ichimoku scalars per (sym, date), and writes the ObjectStore blob (loader.dump_weekly_blob) to
``<storage>/<per-symbol-key>`` (one key per symbol). The LOCAL harness then sets ONLY
``WARMUP_WEEKLY_CACHE_FP=<fp>``; the runtime DERIVES each per-symbol key from it via the shared
weekly_cache_key(fp, sym) + lazy-reads via ``self.object_store``, skipping the per-decision
history(560d) weekly re-derivation.

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
from runtime.warmup_weekly_cache import (  # noqa: E402
    ALL_SCALAR_FIELDS, WEEKLY_FIELDS, daily_scalar_cache_key, dump_weekly_blob, weekly_cache_key,
)

# scheme → (fields written per row, the shared key formula). weekly = the shipped #358 instance (6
# weekly scalars); daily_scalar = #358b warmup-skip (all 17, incl d_cloud_bottom + d_kijun).
_SCHEMES = {
    "weekly": (WEEKLY_FIELDS, weekly_cache_key),
    "daily_scalar": (ALL_SCALAR_FIELDS, daily_scalar_cache_key),
}


def _load_jsonl(cache_dir: Path, fields: tuple[str, ...]) -> dict[str, dict[_dt.date, dict[str, float]]]:
    """Read the per-symbol jsonl cache → {SYM: {date: {fields}}}. Fail-loud on a missing dir."""
    if not cache_dir.is_dir():
        raise SystemExit(f"cache dir not found: {cache_dir} — run build_warmup_cache.py first (fail-loud)")
    syms: dict[str, dict[_dt.date, dict[str, float]]] = {}
    for jf in sorted(cache_dir.glob("*.jsonl")):
        rows: dict[_dt.date, dict[str, float]] = {}
        for line in jf.read_text().splitlines():
            if not line:
                continue
            r = json.loads(line)
            rows[_dt.date.fromisoformat(r["date"])] = {k: float(r[k]) for k in fields}
        if rows:
            syms[jf.stem.upper()] = rows
    if not syms:
        raise SystemExit(f"no rows loaded from {cache_dir} (fail-loud)")
    return syms


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fp", required=True, help="data fingerprint (cache dir name + embedded guard)")
    ap.add_argument("--scheme", default="weekly", choices=list(_SCHEMES),
                    help="weekly (shipped #358) | daily_scalar (#358b warmup-skip, all 17 fields)")
    ap.add_argument("--cache-root", default=str(_ROOT / "results" / "warmup_cache"))
    ap.add_argument("--storage", default=str(_ROOT / "storage"), help="LEAN LocalObjectStore dir")
    args = ap.parse_args()

    fields, key_fn = _SCHEMES[args.scheme]
    cache_dir = Path(args.cache_root) / args.fp
    syms = _load_jsonl(cache_dir, fields)

    # PER-SYMBOL keys: one ObjectStore key per symbol (key_fn(fp, SYM)) so the runtime lazy-loads only
    # the active names it queries — full coverage, no giant-blob OOM.
    storage = Path(args.storage)
    storage.mkdir(parents=True, exist_ok=True)
    total_rows = total_bytes = 0
    for sym, rows in syms.items():
        blob = dump_weekly_blob({sym: rows}, args.fp, fields)  # single-symbol blob (round-trips via parse)
        keyfile = storage / key_fn(args.fp, sym)  # DERIVED — same formula the runtime reads
        keyfile.write_text(blob)
        total_rows += len(rows)
        total_bytes += len(blob)
    print(json.dumps({
        "scheme": args.scheme, "fp": args.fp, "keys": len(syms),
        "rows": total_rows, "bytes": total_bytes, "storage": str(storage),
        "sample_key": key_fn(args.fp, next(iter(syms))) if syms else None,
    }, indent=1))


if __name__ == "__main__":
    main()
