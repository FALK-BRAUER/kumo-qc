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

# One captured daily bar: (iso_date, open, high, low, close, volume). The OHLCV are EXACT DECIMAL
# STRINGS (str(bar.<field>) of the native QC Decimal) — NOT floats. Float truncation shifts indicator
# values at the margin → threshold scores flip → order-count divergence (the 48≠72 bug); the #362
# spike proved byte-identical ONLY with exact Decimal-string preservation. Tuple → compact, JSON-
# round-trippable (strings survive json verbatim), ordered.
DailyBar = tuple[str, str, str, str, str, str]

# blob schema marker — bump if the on-disk format changes (a restore checks it, fail-closed). v2 =
# the float→exact-Decimal-string fix (v1 floats gave 48≠72; v2 strings restore byte-identical).
SNAPSHOT_SCHEMA = "warmup_snapshot_v2"


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
            (str(r[0]), str(r[1]), str(r[2]), str(r[3]), str(r[4]), str(r[5]))
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


def make_daily_bar(d: _dt.date | str, o: Any, h: Any, l: Any, c: Any, v: Any) -> DailyBar:
    """Construct a capture bar with an ISO-date key (chronological-sortable). OHLCV stored as EXACT
    strings — pass str(bar.<field>) of the native QC Decimal (NOT float — that truncates → 48≠72).
    str() here is idempotent on already-string values and exact on a Decimal."""
    iso = d.isoformat() if isinstance(d, _dt.date) else str(d)
    return (iso, str(o), str(h), str(l), str(c), str(v))


def restore_warmup_days(*, restore_fp: "str | None", has_object_store: bool,
                        minimal_days: int, full_days: int) -> tuple[int, bool]:
    """#365 — pick the warmup length, fail-closed. RESTORE is ARMED iff a fingerprint is set AND a
    local object_store exists; armed → `minimal_days` (the cheap coarse-DV fill; the heavy per-symbol
    indicators restore from the snapshot at warmup-end) + True. Else → `full_days` (the canonical
    560d warmup) + False — the cloud path (no fp / no store) and the default both take this branch,
    byte-untouched. Pure → unit-testable without QC."""
    armed = bool(restore_fp) and has_object_store
    return (minimal_days if armed else full_days), armed


def feed_daily_indicators(*, tradebar: Any, end_time: Any, o: float, h: float, lo: float,
                          c: float, v: float, indicators: dict) -> None:
    """#365 RESTORE — feed ONE daily bar into the daily indicator suite, mirroring `_seed_daily`'s
    EXACT per-indicator wiring (the single-code-path seam: restore drives the SAME public update()
    sequence warmup/seed do → byte-identical state by construction). Pure + QC-free → unit-testable
    with stub indicators; the caller (lean_entry) builds the cloud-safe `tradebar` for the
    forward-only full-bar consumers (d_ichi/adx) and passes the scalars for the price/volume-series
    consumers.

    o/h/lo/c/v are EXACT decimal STRINGS (the v2 snapshot). TYPE DISCIPLINE = match each indicator's
    LIVE feed so the restored state is byte-identical to the warmup:
      - d_ichi/adx : the `tradebar` (built by the caller with Decimal OHLCV — QC's native warmup feed
                     is Decimal). adx.updated cascades adx_window.
      - sma200/roc13/macd/vol_sma20.update(end_time, Decimal): the #362 spike proved byte-identical
        with DECIMAL scalars (NOT float). macd.updated cascades macd_hist_window.
      - high_window.add(float) / tbounce.update(float...): the LIVE _on_daily feeds these float(bar.x)
        → restore matches with float (str→float == the live float(Decimal), since str(Decimal) is exact).
    Order is load-bearing (tbounce reads d_ichi's freshly-updated Tenkan)."""
    from decimal import Decimal
    d_ichi = indicators["d_ichi"]
    d_ichi.update(tradebar)
    indicators["adx"].update(tradebar)            # cascades adx_window via adx.updated
    dc, dv = Decimal(c), Decimal(v)
    indicators["sma200"].update(end_time, dc)
    indicators["roc13"].update(end_time, dc)
    indicators["macd"].update(end_time, dc)       # cascades macd_hist_window via macd.updated
    indicators["vol_sma20"].update(end_time, dv)
    indicators["high_window"].add(float(h))
    tk = d_ichi.tenkan.current.value if getattr(d_ichi, "is_ready", False) else 0.0
    indicators["tbounce"].update(float(o), float(h), float(lo), float(c), float(tk))


# ── ObjectStore delivery (RUN1 write / RUNn restore-read) — mirrors the #358 weekly-cache pattern ──
# LOCAL-ONLY key (never uploaded → cloud contains_key False → restore falls back to live warmup) +
# the embedded fp guard. Separator '-' (the cache_key APFS lesson — ':' maps to '/' on macOS).
SNAPSHOT_CACHE_TYPE = "warmup_snapshot"


def snapshot_key(data_fingerprint: str, symbol: str) -> str:
    """Per-symbol ObjectStore key. Same formula RUN1 writes and a restore reads (no drift)."""
    return "-".join((SNAPSHOT_CACHE_TYPE, data_fingerprint, symbol))


def serialize_to_store(snap: "WarmupSnapshot", object_store: Any, fp: str,
                       log: Callable[[str], None] | None = None) -> int:
    """RUN1 warmup-end: write each registered symbol's stream to its per-symbol ObjectStore key.
    Returns the count written (== the warmed-set size). No-op (0) if object_store/fp falsy
    (fail-closed — never half-write). The registered SET is implicit in which keys exist."""
    if object_store is None or not fp:
        return 0
    syms = snap.registered_symbols()
    for sym in syms:
        object_store.save(snapshot_key(fp, sym), snap.to_blob(sym))
    if log is not None:
        log(f"WARMUP_SNAPSHOT_WRITE|fp={fp[:12]}|symbols={len(syms)}")
    return len(syms)


def load_snapshot_for_symbol(object_store: Any, fp: str, symbol: str) -> "WarmupSnapshot | None":
    """Restore-read: a single symbol's snapshot → a replay-ready WarmupSnapshot, or None when
    object_store/fp/symbol falsy, the key is ABSENT (cloud never uploaded → contains_key False →
    live warmup), or read/parse fails (FAIL-CLOSED). Lazy per-symbol (no giant-blob OOM)."""
    if object_store is None or not fp or not symbol:
        return None
    key = snapshot_key(fp, symbol)
    try:
        if not object_store.contains_key(key):
            return None
        text = object_store.read(key)
    except Exception:  # noqa: BLE001 — any store error → fail-closed to live warmup
        return None
    parsed = WarmupSnapshot.parse_blob(text, fp)
    if parsed is None:
        return None
    sym, bars = parsed
    return WarmupSnapshot.from_symbol_bars(fp, sym, bars)
