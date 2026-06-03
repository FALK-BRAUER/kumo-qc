from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any
from urllib.parse import parse_qs, urlencode

COND_BITS = 8

KEY_SCORE = "decision_score"
KEY_COND = "decision_cond"
KEY_GAP = "decision_gap"
KEY_VOL = "decision_vol"
KEY_TDIST = "decision_tdist"
KEY_RANK = "decision_rank"
TAG_KEYS: tuple[str, ...] = (KEY_SCORE, KEY_COND, KEY_GAP, KEY_VOL, KEY_TDIST, KEY_RANK)
CORE_KEYS: tuple[str, ...] = (KEY_SCORE, KEY_COND)


def encode_entry_tag(
    *,
    score: int | None = None,
    conditions: Sequence[Any] | None = None,
    gap: float | None = None,
    vol: float | None = None,
    tdist: float | None = None,
    rank: int | None = None,
) -> str:
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
    return urlencode(fields)


def parse_entry_tag(tag: str | None) -> dict[str, Any]:
    out: dict[str, Any] = {k: None for k in TAG_KEYS}
    if not tag:
        return out
    parsed = parse_qs(tag, keep_blank_values=False)

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
    cond = _first(KEY_COND)
    if cond is not None and len(cond) == COND_BITS and set(cond) <= {"0", "1"}:
        out[KEY_COND] = cond
    return out


def expand_cond(cond: str | None) -> dict[str, bool | None]:
    if cond is None:
        return {f"cond_{i}": None for i in range(COND_BITS)}
    return {f"cond_{i}": (cond[i] == "1") for i in range(COND_BITS)}


def has_core(parsed: dict[str, Any]) -> bool:
    return all(parsed.get(k) is not None for k in CORE_KEYS)
