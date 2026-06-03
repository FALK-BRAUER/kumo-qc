"""#358 — runtime LOADER for the #332 offline warmup cache (the consumption-hook half).

Loads the precomputed weekly Ichimoku scalars from the offline cache (build_warmup_cache.py output:
``<root>/<fingerprint>/<sym>.jsonl`` + ``_FIELDS.json``) into an in-memory
``{sym_upper: {date: {6 weekly scalars}}}`` map, so the live daily decision reads a CACHED weekly
instead of re-deriving it from ``history(560d)`` per candidate per day (the #358 ~5-10x lever; the
offline table already holds the weekly via the same WeeklyIchimokuAsOf, so the cached value is
byte-identical to the live re-derivation → trade-neutral).

FAIL-CLOSED — the charter cloud guard (the 8b50c1a dual-path lesson): the cache loads ONLY when the
expected data fingerprint matches the cache dir's ``_FIELDS.json`` fingerprint. Cloud /
fingerprint-mismatch / missing table / unreadable / garbage → returns ``None`` → the caller falls
back to the LIVE re-derivation (the canonical path). The cache is a LOCAL-harness accelerator that
yields results IDENTICAL to the live warmup, NEVER a second/divergent path. The runtime never
computes the fingerprint itself — the LOCAL harness injects the expected fingerprint; cloud never
sets it → no match → no load. A single corrupt per-symbol file skips ONLY that symbol (it falls back
live), never poisoning the rest.
"""
from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

# the 6 weekly Ichimoku scalars the CONTINUOUS_WEEKLY decision re-derives (== table_builder SCALAR_FIELDS subset).
WEEKLY_FIELDS = ("w_tenkan", "w_kijun", "w_senkou_a", "w_senkou_b", "w_close_0", "w_close_26")


def load_weekly_cache(
    cache_dir: str | Path | None,
    expected_fingerprint: str | None,
) -> dict[str, dict[_dt.date, dict[str, float]]] | None:
    """Load the offline weekly cache at ``cache_dir`` → ``{SYM: {date: {weekly scalars}}}``.

    FAIL-CLOSED → ``None`` (caller re-derives live) on ANY of: ``cache_dir``/``expected_fingerprint``
    falsy; dir or ``_FIELDS.json`` missing; ``_FIELDS.json`` unreadable; fingerprint mismatch (incl
    cloud's different vendor data); the cache's fields don't cover the weekly keys; or no usable rows.
    Never raises on a missing/garbage cache.
    """
    if not cache_dir or not expected_fingerprint:
        return None  # cloud / no injected fingerprint → never load
    root = Path(cache_dir)
    fields_path = root / "_FIELDS.json"
    if not root.is_dir() or not fields_path.is_file():
        return None
    try:
        meta = json.loads(fields_path.read_text())
    except (OSError, ValueError):
        return None
    if str(meta.get("fingerprint")) != str(expected_fingerprint):
        return None  # FAIL-CLOSED: data fingerprint mismatch — the cloud-divergence guard
    if not set(WEEKLY_FIELDS).issubset(set(meta.get("fields", []))):
        return None  # cache predates the weekly scalars — don't half-load

    out: dict[str, dict[_dt.date, dict[str, float]]] = {}
    for jf in sorted(root.glob("*.jsonl")):
        sym = jf.stem.upper()
        rows: dict[_dt.date, dict[str, float]] = {}
        try:
            for line in jf.read_text().splitlines():
                if not line:
                    continue
                r = json.loads(line)
                d = _dt.date.fromisoformat(r["date"])
                rows[d] = {k: float(r[k]) for k in WEEKLY_FIELDS}
        except (OSError, ValueError, KeyError):
            continue  # skip ONLY this corrupt symbol → it falls back to live re-derivation (per-symbol fail-closed)
        if rows:
            out[sym] = rows
    return out or None
