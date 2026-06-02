"""#332 warmup-cache — THE END-TO-END PARITY GATE (committed, repeatable; HQ's hard checkpoint).

Validates the WHOLE cache pipeline (indicator ports → weekly as-of → table builder → score_symbol_
cached) against the LIVE strategy's ACTUAL decisions — not a one-off. The champion fy2025_full run
captured, per entry, the live score_symbol_native output (decision_score + the cond_0..7 bits) that
LEAN's RUNTIME indicators produced. This gate rebuilds the cache from the same RAW daily zips and
asserts the cached score reproduces EVERY live decision BYTE-IDENTICALLY (score + all 8 conditions).

This closes the runtime gap the golden files can't: a port that diverged from LEAN's RUNTIME
indicator (incl roc13, the weekly Calendar.WEEKLY as-of, the ADX Wilder smoothing) would flip a
condition here → the gate fails. One flipped condition = FAIL (never rounded away).

Skips if the champion archive or the local daily zips aren't present (CI without the data substrate).
"""
from __future__ import annotations

import datetime as _dt
import glob
import gzip
import json
import os
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(_ROOT), str(_ROOT / "src")]

from phases.shared.oracle_helpers import score_symbol_cached  # noqa: E402
from sweeps.warmup_cache.table_builder import build_ticker_scalars, read_daily_zip  # noqa: E402

_CFG = "4c2fc8e40607"  # the CONTINUOUS-WEEKLY (corrected) champion (#336/#338 flag-ON identity).
# NB: the flag-OFF identity e3b0c44298fc reproduces only 79/81 vs this cache BY DESIGN — its gappy
# subscription-gated weekly diverges from the continuous-weekly cache on 2 entries (URBN/PEN). That
# divergence DROVE the fix; the gate now targets the corrected flag-ON champion, where cache==live.
_ARCHIVE = _ROOT / "results" / "archive" / _CFG
_DAILY = Path("/Users/falk/projects/kumo-qc/data/equity/usa/daily")


def _champion_entries() -> list[dict]:
    """Live entry decisions captured across ALL champion archive cells (the fy2025 panels + the
    full-FY + realize runs): (symbol, entry date, decision_score, cond bits). Every entry the LIVE
    score_symbol_native fired on — the more cells, the stronger the gate. Deduped by
    (symbol, entry_date, cond)."""
    out: dict[tuple, dict] = {}
    for tj in glob.glob(str(_ARCHIVE / "*" / "trades.jsonl.gz")):
        for line in gzip.decompress(Path(tj).read_bytes()).decode().splitlines():
            r = json.loads(line)
            if r.get("decision_score") is None or not r.get("entry_dt"):
                continue
            key = (r["symbol"].lower(), r["entry_dt"][:10], r.get("decision_cond"))
            out[key] = {
                "symbol": r["symbol"].lower(),
                "entry_date": _dt.date.fromisoformat(r["entry_dt"][:10]),
                "score": int(r["decision_score"]),
                "cond": r.get("decision_cond"),
            }
    return list(out.values())


pytestmark = pytest.mark.skipif(
    not _ARCHIVE.exists() or not _DAILY.exists(),
    reason="champion archive or local daily zips not present",
)


def test_end_to_end_cache_reproduces_live_decisions() -> None:
    """For every champion entry, the cache (built from the RAW daily zips) scored at the DECISION
    date (the last cached trading day strictly before the T+1 entry) must reproduce the LIVE
    decision_score + cond bits BYTE-IDENTICALLY. Full BctScoreFull score path, all 15 scalars."""
    entries = _champion_entries()
    if not entries:
        pytest.skip("no champion entries captured")

    # cache one symbol at a time (RAM-safe), score at each entry's decision date.
    by_symbol: dict[str, list[dict]] = {}
    for e in entries:
        by_symbol.setdefault(e["symbol"], []).append(e)

    checked = 0
    mismatches: list[str] = []
    for sym, evs in by_symbol.items():
        zp = _DAILY / f"{sym}.zip"
        if not zp.exists():
            continue
        rows = {d: s for d, s in build_ticker_scalars(read_daily_zip(zp))}
        dates = sorted(rows)
        for e in evs:
            # decision date = last cached trading day STRICTLY before the T+1 entry (the close T the
            # daily signal scored on, after which it picked the name for T+1).
            prior = [d for d in dates if d < e["entry_date"]]
            if not prior:
                continue
            decision_date = prior[-1]
            sc = score_symbol_cached(rows[decision_date])
            cond = "".join("1" if c else "0" for c in sc["conditions"])
            ok = (sc["score"] == e["score"]) and (e["cond"] is None or cond == e["cond"])
            checked += 1
            if not ok:
                mismatches.append(
                    f"{sym.upper()} entry={e['entry_date']} decision={decision_date}: "
                    f"cache score={sc['score']} cond={cond} vs LIVE score={e['score']} cond={e['cond']}")

    assert checked >= 10, f"too few entries validated ({checked}) — gate not meaningfully exercised"
    assert not mismatches, "CACHE DIVERGES FROM LIVE on:\n" + "\n".join(mismatches)
