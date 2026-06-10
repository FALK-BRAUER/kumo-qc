"""Shared entry-order TAG schema (#archive ① — the emit↔parse SINGLE SOURCE OF TRUTH).

The entry-context TAG is the ONE durable learn-substrate channel (logs/charts/ObjectStore are
unretrievable; the order tag, recovered via /orders/read, is). `lean_entry._build_entry_tag`
EMITS it (cloud-side, bundled into dist/ via the build import-closure); `sweeps.archive.snapshot`
PARSES it (local-side). If the key names OR the encoding drift between the two, the parser silently
returns all-None → every trade row goes CORE_MISSING → the ENTIRE learn-substrate is null, SILENTLY
— the exact silent-corruption the archive exists to prevent, one level up.

So BOTH sides import `encode_entry_tag` / `parse_entry_tag` from HERE. A rename or a format change
is then guaranteed to round-trip (test_tag_schema's round-trip test is the contract guarantee). This
module lives under src/runtime so the build closure bundles it into dist/ alongside lean_entry (the
cloud side needs it to EMIT); the local snapshot imports it off src/ (not bundled — fine).
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any
from urllib.parse import parse_qs, urlencode

COND_BITS = 8  # the 8 BCT conditions (stable bit order == CLAUDE.md BCT stack; a change = schema bump)

# The decision/scanner tag keys — the SINGLE source. Rename here → both emit + parse move together.
KEY_SCORE = "decision_score"
KEY_COND = "decision_cond"
KEY_GAP = "decision_gap"
KEY_VOL = "decision_vol"
KEY_TDIST = "decision_tdist"
KEY_RANK = "decision_rank"
KEY_SCANNER_RANK = "scanner_rank"
KEY_SCANNER_SCORE = "scanner_score"
TAG_KEYS: tuple[str, ...] = (
    KEY_SCORE,
    KEY_COND,
    KEY_GAP,
    KEY_VOL,
    KEY_TDIST,
    KEY_RANK,
    KEY_SCANNER_RANK,
    KEY_SCANNER_SCORE,
)
CORE_KEYS: tuple[str, ...] = (KEY_SCORE, KEY_COND)  # the learn-substrate core (else row is suspect)


def encode_entry_tag(
    *,
    score: int | None = None,
    conditions: Sequence[Any] | None = None,
    gap: float | None = None,
    vol: float | None = None,
    tdist: float | None = None,
    rank: int | None = None,
    scanner_rank: int | None = None,
    scanner_score: float | None = None,
) -> str:
    """Emit the URL-query entry tag from raw values. OMITS a field whose value is None — NEVER
    fakes a missing piece. `conditions` = a length-8 truthy sequence → the 8-bit string. Float
    formatting is fixed HERE (the single source), so parse round-trips the emitted precision."""
    fields: dict[str, Any] = {}
    if score is not None:
        fields[KEY_SCORE] = int(score)
    if conditions:
        fields[KEY_COND] = "".join("1" if c else "0" for c in conditions)
    if gap is not None:
        fields[KEY_GAP] = f"{float(gap):.4f}"
    if vol is not None:
        fields[KEY_VOL] = f"{float(vol):.3f}"
    if tdist is not None:
        fields[KEY_TDIST] = f"{float(tdist):.4f}"
    if rank is not None:
        fields[KEY_RANK] = int(rank)
    if scanner_rank is not None:
        fields[KEY_SCANNER_RANK] = int(scanner_rank)
    if scanner_score is not None:
        fields[KEY_SCANNER_SCORE] = f"{float(scanner_score):.5f}"
    return urlencode(fields)


def parse_entry_tag(tag: str | None) -> dict[str, Any]:
    """Parse the entry tag → typed decision_* fields. Missing/uncastable → None (NEVER faked). A
    malformed decision_cond (wrong length / non-binary) is treated as ABSENT, not banked as garbage."""
    out: dict[str, Any] = {k: None for k in TAG_KEYS}
    if not tag:
        return out
    parsed = parse_qs(tag, keep_blank_values=False)  # urldecodes; empty pieces drop out

    def _first(key: str) -> str | None:
        vals = parsed.get(key)
        return vals[0] if vals else None

    def _as_int(key: str) -> int | None:
        raw = _first(key)
        try:
            return int(raw) if raw is not None else None
        except (ValueError, TypeError):
            return None

    def _as_float(key: str) -> float | None:
        raw = _first(key)
        if raw is None:
            return None
        try:
            v = float(raw)
        except (ValueError, TypeError):
            return None
        return v if math.isfinite(v) else None

    out[KEY_SCORE] = _as_int(KEY_SCORE)
    out[KEY_GAP] = _as_float(KEY_GAP)
    out[KEY_VOL] = _as_float(KEY_VOL)
    out[KEY_TDIST] = _as_float(KEY_TDIST)
    out[KEY_RANK] = _as_int(KEY_RANK)
    out[KEY_SCANNER_RANK] = _as_int(KEY_SCANNER_RANK)
    out[KEY_SCANNER_SCORE] = _as_float(KEY_SCANNER_SCORE)
    cond = _first(KEY_COND)
    if cond is not None and len(cond) == COND_BITS and set(cond) <= {"0", "1"}:
        out[KEY_COND] = cond
    return out


def expand_cond(cond: str | None) -> dict[str, bool | None]:
    """decision_cond "11110111" → cond_0..cond_7 booleans. None (NOT all-False) when absent → the
    row is flagged CORE_MISSING by the consumer rather than silently treated as 8 failed conditions."""
    if cond is None:
        return {f"cond_{i}": None for i in range(COND_BITS)}
    return {f"cond_{i}": (cond[i] == "1") for i in range(COND_BITS)}


def has_core(parsed: dict[str, Any]) -> bool:
    """The learn-substrate core present? (both decision_score AND decision_cond). Else CORE_MISSING."""
    return all(parsed.get(k) is not None for k in CORE_KEYS)
