#!/usr/bin/env python3
"""Generate data/MANIFEST.json — the SUBSTRATE fingerprint (#219).

The substrate is the SET of daily zip files in data/equity/usa/daily. The manifest
is a deterministic hash over that set ("what data exists"). It REPLACES the old
326-scoped manifest fintrack removed (which conflated substrate with a fixed universe).

Two fingerprint modes (the substrate is ~19k zips — content-hashing each is slow):

  --mode signature   (DEFAULT, fast): hash over sorted (ticker, file_size) pairs.
                     Detects added/removed tickers and any size change. Does NOT
                     detect a same-size content edit. Fast: stat() only, no reads.
                     (mtime is deliberately EXCLUDED — it is not reproducible across
                     a checkout/rsync, which would make the fingerprint non-deterministic.)

  --mode sha256      (slow, exact): hash over sorted (ticker, sha256(file_bytes)).
                     Detects ANY content change. ~19k full reads — minutes-scale.

Tradeoff: `signature` is the pragmatic default for a one-time/CI fingerprint; run
`sha256` when you need byte-exact substrate provenance (e.g. before a parity claim).
The chosen mode is recorded in the manifest so a reader knows the guarantee level.

Output (data/MANIFEST.json), TRACKED:
  {"fingerprint": "...", "mode": "...", "ticker_count": N, "generated_from": "..."}

NO timestamp (Date.now is blocked); the fingerprint IS the provenance handle.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


def _sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def compute_fingerprint(data_dir: Path, mode: str) -> tuple[str, int]:
    """Return (fingerprint_hex, ticker_count). Deterministic: tickers sorted; same
    substrate + same mode => same hash."""
    zips = sorted(data_dir.glob("*.zip"), key=lambda p: p.stem.lower())
    h = hashlib.sha256()
    for zp in zips:
        ticker = zp.stem.lower()
        if mode == "sha256":
            token = _sha256_file(zp)
        elif mode == "signature":
            token = str(zp.stat().st_size)
        else:
            raise SystemExit(f"unknown mode: {mode}")
        h.update(ticker.encode("utf-8"))
        h.update(b"\0")
        h.update(token.encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest(), len(zips)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", type=Path, default=Path("data/equity/usa/daily"))
    ap.add_argument("--out", type=Path, default=Path("data/MANIFEST.json"))
    ap.add_argument("--mode", choices=["signature", "sha256"], default="signature")
    args = ap.parse_args(argv)

    if not args.data_dir.is_dir():
        raise SystemExit(f"data dir not found: {args.data_dir}")

    fingerprint, ticker_count = compute_fingerprint(args.data_dir, args.mode)
    manifest = {
        "fingerprint": fingerprint,
        "mode": args.mode,
        "ticker_count": ticker_count,
        "generated_from": str(args.data_dir),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(f"wrote {args.out}")
    print(f"  mode={args.mode} ticker_count={ticker_count}")
    print(f"  fingerprint={fingerprint}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
