"""#362 SPIKE increment-1 — unit tests for the warmup-snapshot capture/serialize/replay buffer.

Proves MY code (the buffer + serialization + replay driver), NOT the C# indicators — the
byte-identical-on-real-indicators proof is the LEAN BT (the increment-3 correctness gate). Here:
round-trip, fail-closed fp/schema, chronological-capture guard, replay ordering + count,
universe-gated registered-set, cold-restore for an unwarmed symbol.
"""
from __future__ import annotations

import datetime as _dt
from decimal import Decimal

import pytest

from runtime.warmup_snapshot import (
    SNAPSHOT_SCHEMA, WarmupSnapshot, feed_daily_indicators, load_snapshot_for_symbol,
    make_daily_bar, restore_warmup_days, serialize_to_store, snapshot_key,
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


# ── #365 RESTORE seam — feed_daily_indicators wiring + replay-driven restore ──────────────────


class _Rec:
    """Records .update(...) call args. Models a forward-only indicator: stores the last full-bar
    update so the suite-order + per-indicator routing can be asserted without QC's C# indicators."""

    def __init__(self) -> None:
        self.calls: list = []

    def update(self, *args: object) -> None:
        self.calls.append(args)

    def add(self, x: object) -> None:  # RollingWindow-style (high_window)
        self.calls.append(("add", x))


class _Tenkan:
    def __init__(self, value: float) -> None:
        self.current = type("C", (), {"value": value})()


class _DIchi(_Rec):
    """d_ichi stub: is_ready + a tenkan.current.value (read by the tbounce wiring AFTER update)."""

    def __init__(self, ready: bool, tenkan_value: float) -> None:
        super().__init__()
        self.is_ready = ready
        self.tenkan = _Tenkan(tenkan_value)


def _suite(d_ichi: _DIchi) -> dict:
    keys = ("adx", "sma200", "roc13", "macd", "vol_sma20", "tbounce", "high_window")
    suite: dict = {k: _Rec() for k in keys}
    suite["d_ichi"] = d_ichi
    return suite


def test_feed_daily_indicators_routes_each_consumer_correctly() -> None:
    d_ichi = _DIchi(ready=True, tenkan_value=42.0)
    suite = _suite(d_ichi)
    et = _dt.datetime(2024, 1, 5)
    bar = object()  # the full-bar token routed to the forward-only consumers
    # #365 v2: OHLCV are EXACT decimal STRINGS. Core indicators get Decimal; high_window/tbounce float.
    feed_daily_indicators(tradebar=bar, end_time=et, o="10.0", h="11.0", lo="9.0", c="10.5",
                          v="1000.0", indicators=suite)
    # full-bar consumers get the TradeBar token (caller builds it with exact Decimal OHLCV)
    assert d_ichi.calls == [(bar,)]
    assert suite["adx"].calls == [(bar,)]
    # price-series consumers get (end_time, Decimal(close)) — exact, NOT float
    assert suite["sma200"].calls == [(et, Decimal("10.5"))]
    assert suite["roc13"].calls == [(et, Decimal("10.5"))]
    assert suite["macd"].calls == [(et, Decimal("10.5"))]
    # volume-series consumer gets (end_time, Decimal(volume))
    assert suite["vol_sma20"].calls == [(et, Decimal("1000.0"))]
    # high_window gets float(high) (matches the live _on_daily float(bar.high))
    assert suite["high_window"].calls == [("add", 11.0)]
    # tbounce gets float OHLC + the LIVE tenkan (read AFTER d_ichi.update → ready → 42.0)
    assert suite["tbounce"].calls == [(10.0, 11.0, 9.0, 10.5, 42.0)]


def test_feed_daily_indicators_tbounce_tenkan_zero_until_ready() -> None:
    # d_ichi not ready → the seed idiom feeds tbounce a 0.0 Tenkan (matches _seed_daily exactly)
    d_ichi = _DIchi(ready=False, tenkan_value=999.0)
    suite = _suite(d_ichi)
    feed_daily_indicators(tradebar=object(), end_time=_dt.datetime(2024, 1, 5),
                          o="1.0", h="2.0", lo="0.5", c="1.5", v="10.0", indicators=suite)
    assert suite["tbounce"].calls == [(1.0, 2.0, 0.5, 1.5, 0.0)]


def test_restore_replays_full_stream_in_chronological_order() -> None:
    # the lean_entry restore is `snap.replay(sym, _feed)`; here _feed drives the suite per bar →
    # prove the WHOLE captured stream replays in capture order (the byte-identical-by-construction
    # property at MY layer; the C#-indicator byte-identical is the full-FY BT gate).
    bars = _bars(5)
    snap = WarmupSnapshot(FP)
    for b in bars:
        snap.record("AAPL", b)
    d_ichi = _DIchi(ready=True, tenkan_value=5.0)
    suite = _suite(d_ichi)
    seen: list = []

    def _feed(bar: tuple) -> None:
        iso, o, h, lo, c, v = bar
        seen.append(iso)
        feed_daily_indicators(tradebar=("tb", iso), end_time=_dt.datetime.fromisoformat(iso),
                              o=o, h=h, lo=lo, c=c, v=v, indicators=suite)

    n = snap.replay("AAPL", _feed)
    assert n == 5
    assert seen == [b[0] for b in bars]                 # chronological, every bar
    assert len(suite["sma200"].calls) == 5              # each consumer fed once per bar
    # high_window gets float(high); the captured bar's high (b[2]) is an exact decimal string
    assert suite["high_window"].calls == [("add", float(b[2])) for b in bars]  # highs, in order


def test_restore_cold_for_unwarmed_symbol() -> None:
    # a symbol absent from the snapshot replays 0 bars → stays COLD (the #358 (ii) universe-gated fix)
    snap = WarmupSnapshot(FP)
    for b in _bars(3):
        snap.record("AAPL", b)
    suite = _suite(_DIchi(ready=False, tenkan_value=0.0))

    def _feed(bar: tuple) -> None:  # pragma: no cover — must NOT be called
        feed_daily_indicators(tradebar=object(), end_time=_dt.datetime(2024, 1, 5),
                              o=bar[1], h=bar[2], lo=bar[3], c=bar[4], v=bar[5], indicators=suite)

    assert snap.replay("NVDA", _feed) == 0
    assert suite["sma200"].calls == []  # nothing fed → cold


def test_restore_warmup_days_fail_closed_gate() -> None:
    # ARMED: a fp + a local object_store → minimal (the coarse-DV fill) + armed=True
    days, armed = restore_warmup_days(restore_fp=FP, has_object_store=True,
                                      minimal_days=40, full_days=560)
    assert (days, armed) == (40, True)
    # no object_store (cloud analogue) → full 560d, fail-closed
    assert restore_warmup_days(restore_fp=FP, has_object_store=False,
                               minimal_days=40, full_days=560) == (560, False)
    # no fp (default / cloud) → full 560d, byte-untouched
    assert restore_warmup_days(restore_fp=None, has_object_store=True,
                               minimal_days=40, full_days=560) == (560, False)
    assert restore_warmup_days(restore_fp="", has_object_store=True,
                               minimal_days=40, full_days=560) == (560, False)


# ── #368 fail-loud guard: weekly_miss_action (in-window throw vs legit skip vs canonical value) ──


def test_weekly_miss_action_in_window_trimmed_throws() -> None:
    from runtime.warmup_weekly_cache import weekly_miss_action
    # computable (ready) + armed + trimmed (320<560) → THROW (real cache gap, would silently drop)
    assert weekly_miss_action(rederive_ready=True, armed=True, warmup_days=320, weekly_floor=560) == "throw"


def test_weekly_miss_action_legit_uncomputable_skips() -> None:
    from runtime.warmup_weekly_cache import weekly_miss_action
    # NOT ready (pre-78wk-from-listing / post-delisting) → SKIP, never throw — even armed+trimmed
    assert weekly_miss_action(rederive_ready=False, armed=True, warmup_days=320, weekly_floor=560) == "skip"
    assert weekly_miss_action(rederive_ready=False, armed=True, warmup_days=560, weekly_floor=560) == "skip"


def test_weekly_miss_action_untrimmed_returns_value() -> None:
    from runtime.warmup_weekly_cache import weekly_miss_action
    # full warmup (not trimmed) → canonical re-derive value, NO throw
    assert weekly_miss_action(rederive_ready=True, armed=True, warmup_days=560, weekly_floor=560) == "value"
    # unarmed (no cache) → value (the no-cache 560-baseline path) — never throws
    assert weekly_miss_action(rederive_ready=True, armed=False, warmup_days=320, weekly_floor=560) == "value"
