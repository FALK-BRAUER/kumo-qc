"""#358 — ObjectStore-native delivery for the warmup cache (the framework's standard read path).

The live strategy reads NO files in-container (universe is live; the retired stored-universe artifact
proved the disk/ObjectStore dual-path divergence trap). So the cache is delivered the QC-NATIVE way:
the offline builder writes a blob to the LEAN LocalObjectStore key; the runtime reads it via
``self.object_store`` (portable in-container, no raw-mount-path gamble). The blob is
``{"fingerprint": fp, "syms": {SYM: {date_iso: {6 weekly scalars}}}}``.

FAIL-CLOSED — the charter cloud guard, now TWO independent layers:
  1. the key is LOCAL-ONLY (never uploaded to cloud) → cloud ``object_store.contains_key`` False → None.
  2. fingerprint mismatch (even if a key were present) → None.
Either → the caller re-derives live (the canonical path). The cache is a LOCAL accelerator yielding
results IDENTICAL to the live warmup, NEVER a divergent path.
"""
from __future__ import annotations

import datetime as _dt
import json
from typing import Any

# the 6 weekly Ichimoku scalars the CONTINUOUS_WEEKLY decision re-derives (== table_builder subset).
WEEKLY_FIELDS = ("w_tenkan", "w_kijun", "w_senkou_a", "w_senkou_b", "w_close_0", "w_close_26")


def dump_weekly_blob(syms: dict[str, dict[_dt.date, dict[str, float]]], fingerprint: str) -> str:
    """Serialize a ``{SYM: {date: {6 weekly scalars}}}`` map → the ObjectStore JSON blob. The offline
    builder calls this; ``parse_weekly_cache`` is its exact inverse (round-trip-identical)."""
    return json.dumps({
        "fingerprint": str(fingerprint),
        "syms": {
            sym: {d.isoformat(): {k: float(wk[k]) for k in WEEKLY_FIELDS} for d, wk in rows.items()}
            for sym, rows in syms.items()
        },
    }, separators=(",", ":"))


def parse_weekly_cache(
    text: str | None,
    expected_fingerprint: str | None,
) -> dict[str, dict[_dt.date, dict[str, float]]] | None:
    """Parse the ObjectStore blob → ``{SYM: {date: {6 weekly scalars}}}``. FAIL-CLOSED → ``None`` on:
    falsy text/fp; bad JSON; fingerprint mismatch (incl cloud's different vendor data); malformed/
    missing weekly fields. Pure — unit-testable without a runtime."""
    if not text or not expected_fingerprint:
        return None
    try:
        blob = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(blob, dict) or str(blob.get("fingerprint")) != str(expected_fingerprint):
        return None  # FAIL-CLOSED: fingerprint mismatch — the cloud-divergence guard
    syms = blob.get("syms")
    if not isinstance(syms, dict):
        return None
    out: dict[str, dict[_dt.date, dict[str, float]]] = {}
    for sym, rows in syms.items():
        if not isinstance(rows, dict):
            return None
        m: dict[_dt.date, dict[str, float]] = {}
        for date_iso, wk in rows.items():
            if not isinstance(wk, dict) or not set(WEEKLY_FIELDS).issubset(wk):
                return None  # malformed row — don't half-load
            try:
                m[_dt.date.fromisoformat(date_iso)] = {k: float(wk[k]) for k in WEEKLY_FIELDS}
            except (ValueError, TypeError):
                return None
        if m:
            out[str(sym).upper()] = m
    return out or None


def load_weekly_cache_from_store(
    object_store: Any,
    key: str | None,
    expected_fingerprint: str | None,
) -> dict[str, dict[_dt.date, dict[str, float]]] | None:
    """Fetch the cache blob from the LEAN ObjectStore + parse. FAIL-CLOSED → ``None`` when the
    ``object_store``/``key``/``fingerprint`` is falsy, the key is ABSENT (cloud: never uploaded →
    contains_key False → live re-derive), or read/parse fails. Never raises — a read error falls back
    to the live canonical path (the failure is surfaced by the caller's init LOADED/NOT-loaded log)."""
    if object_store is None or not key or not expected_fingerprint:
        return None
    try:
        if not object_store.contains_key(key):
            return None  # key absent → cloud / not-populated → fail-closed
        text = object_store.read(key)
    except Exception:  # noqa: BLE001 — fail-closed-to-live is intended; init logs LOADED/NOT-loaded
        return None
    return parse_weekly_cache(text, expected_fingerprint)
