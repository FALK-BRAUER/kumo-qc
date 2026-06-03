"""#362 SPIKE — warmup-state snapshot via deterministic INPUT-REPLAY (Option B).

The strategy warms its per-symbol indicators over a 560d `set_warmup`. That warmup is the
heavy per-cell cost (~200s) AND the WarmupGate-serialized memory pressure that blocks parallel
fan-out. #358 tried to cache per-(symbol,date) VALUES and got readiness WRONG (universe-blind →
the (ii) FUNDAMENTAL boundary).

This module snapshots the RIGHT layer: the EXACT per-symbol input-bar STREAM the engine fed each
indicator DURING warmup (from that symbol's first warmup-subscription bar). Restoring = recreate
the indicators and RE-FEED that captured stream via the public `update()` path — byte-identical by
construction (deterministic replay reproduces window AND EWM state alike, no reflection), and
universe-membership-CORRECT by construction (only names actually warmed have a buffer → unwarmed
names restore cold → matches the champion → solves the #358 readiness killer).

Reflection-free: uses ONLY public `update()`. Window indicators (Ichimoku/SMA/ROC) and recursive
EWM indicators (ADX/MACD) both reproduce exactly because the same input sequence drives the same
deterministic compute. See GH #362 for the design + the 3 go/no-go gates (correctness/speed/RSS).

FAIL-CLOSED (the #358/8b50c1a lesson): the blob embeds the data fingerprint; a restore against a
mismatched fp refuses (returns None → caller falls back to live warmup). LOCAL-only accelerator.
"""
from __future__ import annotations

import datetime as _dt
import json
from typing import Any, Callable, Iterable

# One captured daily bar: (iso_date, open, high, low, close, volume). RAW prices (the champion's
# universe_settings normalization). Stored as a tuple → compact, JSON-round-trippable, ordered.
DailyBar = tuple[str, float, float, float, float, float]

# blob schema marker — bump if the on-disk format changes (a restore checks it, fail-closed).
SNAPSHOT_SCHEMA = "warmup_snapshot_v1"


class WarmupSnapshot:
    """Accumulates the per-symbol warmup input-bar stream, then serializes / replays it.

    Capture (during the ONE real warmup): `record(symbol_value, bar)` per daily bar the engine
    feeds while `is_warming_up`. The registered SET emerges from which symbols got any bar — that
    set IS the universe-membership readiness (the #358 fix).

    Replay (per variant, warmup skipped): `replay(symbol_value, feed)` calls `feed(bar)` for each
    captured bar IN CHRONOLOGICAL ORDER. `feed` mirrors the live wiring (update the daily indicators
    + drive the consolidators) — identical to `_seed_daily`, but from the captured buffer (no
    history() I/O, no universe re-selection).
    """

    def __init__(self, data_fingerprint: str) -> None:
        self._fp = data_fingerprint
        self._bars: dict[str, list[DailyBar]] = {}

    # -- capture --------------------------------------------------------------------------------
    def record(self, symbol_value: str, bar: DailyBar) -> None:
        """Append one captured daily bar for a symbol. Enforces CHRONOLOGICAL order (forward-only,
        mirrors IndicatorBase.Update's forward-only guard) — an out-of-order bar is a capture bug,
        fail-loud rather than silently corrupt the replayed state."""
        rows = self._bars.setdefault(symbol_value, [])
        if rows and bar[0] <= rows[-1][0]:
            raise ValueError(
                f"WarmupSnapshot.record: non-chronological bar for {symbol_value}: "
                f"{bar[0]} <= last {rows[-1][0]} (forward-only capture)"
            )
        rows.append(bar)

    def registered_symbols(self) -> frozenset[str]:
        """The set of symbols with a captured stream = the names warmed during this warmup. A
        symbol absent here restores COLD (no replay) → matches the champion's universe-gated
        readiness (the #358 fix)."""
        return frozenset(self._bars)

    def bars_for(self, symbol_value: str) -> tuple[DailyBar, ...]:
        return tuple(self._bars.get(symbol_value, ()))

    # -- replay ---------------------------------------------------------------------------------
    def replay(self, symbol_value: str, feed: Callable[[DailyBar], None]) -> int:
        """Re-feed a symbol's captured stream via `feed`, chronologically. Returns the bar count
        fed (0 = symbol not in the snapshot → caller leaves it cold). `feed` raising propagates
        (a wiring bug must fail loud, never silently diverge)."""
        rows = self._bars.get(symbol_value)
        if not rows:
            return 0
        for bar in rows:
            feed(bar)
        return len(rows)

    # -- serialize (per-symbol blob, fail-closed on fp) -----------------------------------------
    def to_blob(self, symbol_value: str) -> str:
        """One symbol's stream → a JSON blob (fp-stamped). Per-symbol so a variant restore lazy-
        loads only the names it registers (no giant-blob OOM — the #358 per-symbol lesson)."""
        return json.dumps({
            "schema": SNAPSHOT_SCHEMA,
            "fp": self._fp,
            "symbol": symbol_value,
            "bars": self._bars.get(symbol_value, []),
        }, separators=(",", ":"))

    @staticmethod
    def parse_blob(text: str, expect_fp: str) -> tuple[str, list[DailyBar]] | None:
        """Parse a per-symbol blob → (symbol_value, bars), or None if schema/fp mismatch
        (FAIL-CLOSED — a stale/cross-dataset cache must NOT be replayed). Bars round-trip as
        tuples (json gives lists → coerce) so the replayed `feed` sees the capture types."""
        try:
            obj = json.loads(text)
        except (ValueError, TypeError):
            return None
        if obj.get("schema") != SNAPSHOT_SCHEMA or obj.get("fp") != expect_fp:
            return None
        sym = obj.get("symbol")
        raw = obj.get("bars")
        if not isinstance(sym, str) or not isinstance(raw, list):
            return None
        bars: list[DailyBar] = [
            (str(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5]))
            for r in raw
        ]
        return sym, bars

    @classmethod
    def from_symbol_bars(cls, data_fingerprint: str, symbol_value: str,
                         bars: Iterable[DailyBar]) -> "WarmupSnapshot":
        """Rebuild a single-symbol snapshot from parsed bars (the restore side, post parse_blob)."""
        snap = cls(data_fingerprint)
        for bar in bars:
            snap.record(symbol_value, bar)
        return snap


def make_daily_bar(d: _dt.date | str, o: float, h: float, l: float, c: float, v: float) -> DailyBar:
    """Construct a capture bar with an ISO-date key (chronological-sortable, round-trip-stable)."""
    iso = d.isoformat() if isinstance(d, _dt.date) else str(d)
    return (iso, float(o), float(h), float(l), float(c), float(v))
