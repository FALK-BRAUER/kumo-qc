"""#362 SPIKE increment-1 — unit tests for the warmup-snapshot capture/serialize/replay buffer.

Proves MY code (the buffer + serialization + replay driver), NOT the C# indicators — the
byte-identical-on-real-indicators proof is the LEAN BT (the increment-3 correctness gate). Here:
round-trip, fail-closed fp/schema, chronological-capture guard, replay ordering + count,
universe-gated registered-set, cold-restore for an unwarmed symbol.
"""
from __future__ import annotations

import datetime as _dt

import pytest

from runtime.warmup_snapshot import (
    SNAPSHOT_SCHEMA, WarmupSnapshot, load_snapshot_for_symbol, make_daily_bar,
    serialize_to_store, snapshot_key,
)


class _MockStore:
    """Dict-backed ObjectStore stub (contains_key/read/save) for the store-helper tests."""

    def __init__(self) -> None:
        self.d: dict[str, str] = {}

    def save(self, key: str, text: str) -> bool:
        self.d[key] = text
        return True

    def contains_key(self, key: str) -> bool:
        return key in self.d

    def read(self, key: str) -> str:
        return self.d[key]

FP = "90f2d7e3fb80d0a4d2eb286f6a43199e1519495a3ce9d787a4d7d0dfc70c535c"


def _bars(n: int, start: _dt.date = _dt.date(2024, 1, 2)) -> list:
    """n chronological daily bars (weekdays), deterministic OHLCV."""
    out = []
    d = start
    made = 0
    while made < n:
        if d.weekday() < 5:
            out.append(make_daily_bar(d, 10 + made, 11 + made, 9 + made, 10.5 + made, 1000 + made))
            made += 1
        d += _dt.timedelta(days=1)
    return out


def test_record_and_registered_set_is_universe_gated() -> None:
    snap = WarmupSnapshot(FP)
    for b in _bars(3):
        snap.record("AAPL", b)
    for b in _bars(2):
        snap.record("MSFT", b)
    # only recorded symbols are "warmed"; an unrecorded name is absent (restores cold = #358 fix)
    assert snap.registered_symbols() == frozenset({"AAPL", "MSFT"})
    assert "NVDA" not in snap.registered_symbols()
    assert len(snap.bars_for("AAPL")) == 3
    assert snap.bars_for("NVDA") == ()


def test_chronological_capture_guard_fails_loud() -> None:
    snap = WarmupSnapshot(FP)
    bars = _bars(3)
    snap.record("AAPL", bars[0])
    snap.record("AAPL", bars[2])
    # a bar at/<= the last captured date is a capture bug → fail loud, never silently corrupt state
    with pytest.raises(ValueError, match="non-chronological"):
        snap.record("AAPL", bars[1])
    # equal date also rejected (forward-only, mirrors IndicatorBase.Update)
    with pytest.raises(ValueError, match="non-chronological"):
        snap.record("AAPL", bars[2])


def test_replay_feeds_in_order_and_returns_count() -> None:
    snap = WarmupSnapshot(FP)
    captured = _bars(5)
    for b in captured:
        snap.record("AAPL", b)
    fed: list = []
    n = snap.replay("AAPL", fed.append)
    assert n == 5
    assert fed == captured  # exact sequence, exact order (deterministic replay)


def test_replay_absent_symbol_is_cold_noop() -> None:
    snap = WarmupSnapshot(FP)
    for b in _bars(3):
        snap.record("AAPL", b)
    fed: list = []
    n = snap.replay("NVDA", fed.append)  # never warmed → no replay → restores cold
    assert n == 0
    assert fed == []


def test_replay_propagates_feed_errors() -> None:
    snap = WarmupSnapshot(FP)
    for b in _bars(2):
        snap.record("AAPL", b)

    def boom(_bar) -> None:
        raise RuntimeError("wiring bug")

    # a wiring bug in the feed MUST propagate (fail loud), never silently diverge
    with pytest.raises(RuntimeError, match="wiring bug"):
        snap.replay("AAPL", boom)


def test_blob_round_trip_preserves_bars_and_types() -> None:
    snap = WarmupSnapshot(FP)
    captured = _bars(4)
    for b in captured:
        snap.record("AAPL", b)
    blob = snap.to_blob("AAPL")
    parsed = WarmupSnapshot.parse_blob(blob, FP)
    assert parsed is not None
    sym, bars = parsed
    assert sym == "AAPL"
    assert bars == captured  # tuple types + values preserved across JSON round-trip
    # and the rebuilt snapshot replays identically
    rebuilt = WarmupSnapshot.from_symbol_bars(FP, sym, bars)
    fed: list = []
    assert rebuilt.replay("AAPL", fed.append) == 4
    assert fed == captured


def test_parse_blob_fail_closed_on_fp_mismatch() -> None:
    snap = WarmupSnapshot(FP)
    for b in _bars(2):
        snap.record("AAPL", b)
    blob = snap.to_blob("AAPL")
    # a blob from a different dataset MUST NOT replay (the #358/8b50c1a fail-closed lesson)
    assert WarmupSnapshot.parse_blob(blob, "different_fp") is None


def test_parse_blob_fail_closed_on_schema_and_garbage() -> None:
    assert WarmupSnapshot.parse_blob("not json", FP) is None
    assert WarmupSnapshot.parse_blob('{"schema":"wrong","fp":"' + FP + '"}', FP) is None
    # right schema+fp but malformed bars → None (no half-restore)
    bad = '{"schema":"' + SNAPSHOT_SCHEMA + '","fp":"' + FP + '","symbol":"AAPL","bars":"x"}'
    assert WarmupSnapshot.parse_blob(bad, FP) is None


def test_snapshot_key_apfs_safe_and_per_symbol() -> None:
    k = snapshot_key(FP, "AAPL")
    assert ":" not in k  # APFS maps ':'→'/' — must use '-'
    assert k.endswith("-AAPL") and FP in k
    assert snapshot_key(FP, "AAPL") != snapshot_key(FP, "MSFT")


def test_serialize_to_store_writes_warmed_set_and_round_trips() -> None:
    snap = WarmupSnapshot(FP)
    a, m = _bars(5), _bars(3)
    for b in a:
        snap.record("AAPL", b)
    for b in m:
        snap.record("MSFT", b)
    store = _MockStore()
    n = serialize_to_store(snap, store, FP)
    assert n == 2  # warmed-set size
    assert set(store.d) == {snapshot_key(FP, "AAPL"), snapshot_key(FP, "MSFT")}
    # restore each → replay-identical to capture
    ra = load_snapshot_for_symbol(store, FP, "AAPL")
    assert ra is not None
    fed: list = []
    assert ra.replay("AAPL", fed.append) == 5
    assert fed == a


def test_serialize_to_store_noop_without_store_or_fp() -> None:
    snap = WarmupSnapshot(FP)
    snap.record("AAPL", _bars(1)[0])
    assert serialize_to_store(snap, None, FP) == 0       # no store → fail-closed no-op
    assert serialize_to_store(snap, _MockStore(), "") == 0  # no fp → fail-closed no-op


def test_load_snapshot_fail_closed_absent_and_fp_mismatch() -> None:
    snap = WarmupSnapshot(FP)
    snap.record("AAPL", _bars(2)[0])
    store = _MockStore()
    serialize_to_store(snap, store, FP)
    # absent symbol → None (cloud never-uploaded analogue → live warmup)
    assert load_snapshot_for_symbol(store, FP, "NVDA") is None
    # fp mismatch → None even though a key exists under the real fp (cross-dataset guard)
    assert load_snapshot_for_symbol(store, "other_fp", "AAPL") is None
    # falsy args → None
    assert load_snapshot_for_symbol(None, FP, "AAPL") is None
    assert load_snapshot_for_symbol(store, FP, "") is None
