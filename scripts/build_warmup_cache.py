"""#332 — OFFLINE warmup-cache builder. Runs the LEAN-faithful ports (table_builder) over each
universe symbol's daily zip in ONE streaming pass and writes a per-symbol cache file of the 15
SCALAR_FIELDS per date. The live strategy (lean_entry, flag-gated) LOADS these per-symbol files +
skips the 560-day warmup.

OFFLINE by design (avoids look-ahead): the table holds ALL dates, computed from the full daily
history; the strategy at decision date T reads ONLY row T, whose scalars are as-of <=T (the
WeeklyIchimokuAsOf enforces no-look-ahead within the weekly). RAM-safe: one symbol streamed at a
time (the 160GB OOM lesson). Fingerprint-keyed: the cache dir name pins the data fingerprint so a
LOCAL cache is never wrongly reused on a different data source.

Usage:
  python3 scripts/build_warmup_cache.py [--symbols a,b,c | --symbols-file f] [--out DIR]
  (default symbols = every <ticker>.zip in the daily dir.)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_ROOT), str(_ROOT / "src")]

from sweeps.warmup_cache.table_builder import (  # noqa: E402
    SCALAR_FIELDS, build_ticker_scalars, read_daily_zip,
)

_DAILY = Path("/Users/falk/projects/kumo-qc/data/equity/usa/daily")
_MANIFEST = _ROOT / "data" / "MANIFEST.json"
_DEFAULT_OUT = _ROOT / "results" / "warmup_cache"


def _data_fingerprint() -> str:
    if _MANIFEST.exists():
        return str(json.loads(_MANIFEST.read_text()).get("fingerprint", "local-data"))
    return "local-data"


def build(symbols: list[str], out_root: Path, daily: Path = _DAILY) -> dict:
    """Stream each symbol's daily zip → per-symbol <out>/<fingerprint>/<sym>.jsonl (date + 15
    scalars). Returns a summary (counts, peak rows). RAM-safe — one symbol in flight."""
    fp = _data_fingerprint()
    out = out_root / fp
    out.mkdir(parents=True, exist_ok=True)
    (out / "_FIELDS.json").write_text(json.dumps({"fields": list(SCALAR_FIELDS), "fingerprint": fp}))
    t0 = time.time()
    built = missing = total_rows = 0
    for sym in symbols:
        sym = sym.strip().lower()
        if not sym:
            continue
        zp = daily / f"{sym}.zip"
        if not zp.exists():
            missing += 1
            continue
        lines = []
        for d, sc in build_ticker_scalars(read_daily_zip(zp)):  # streaming generator (RAM-safe)
            row = {"date": d.isoformat()}
            row.update({k: sc[k] for k in SCALAR_FIELDS})
            lines.append(json.dumps(row, separators=(",", ":")))
        (out / f"{sym}.jsonl").write_text("\n".join(lines) + ("\n" if lines else ""))
        built += 1
        total_rows += len(lines)
    return {
        "fingerprint": fp, "out": str(out), "built": built, "missing": missing,
        "total_rows": total_rows, "seconds": round(time.time() - t0, 1),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default=None, help="comma-separated tickers")
    ap.add_argument("--symbols-file", default=None, help="file with one ticker per line")
    ap.add_argument("--out", default=str(_DEFAULT_OUT))
    args = ap.parse_args()
    if args.symbols:
        syms = args.symbols.split(",")
    elif args.symbols_file:
        syms = Path(args.symbols_file).read_text().split()
    else:
        syms = sorted(p.stem for p in _DAILY.glob("*.zip"))
    summary = build(syms, Path(args.out))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
