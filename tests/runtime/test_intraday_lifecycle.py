"""#275b — the dynamic intraday (5-min) subscription LIFECYCLE: leak / cold-seed / cap.

Option C: candidates get a Resolution.MINUTE subscription (our Massive is 5-min, consumed
directly), with seed-on-subscribe (warm before first score) + EXPLICIT teardown on rotation
(RemoveSecurity does NOT auto-dispose user indicators — confirmed in LEAN source — so a missing
teardown LEAKS, the #213e scar). These tests pin: subscribe→rotate→removed (leak), seed-warms
(cold), cap binds, held names keep their feed.
"""
from __future__ import annotations

from datetime import datetime

import pytest

import runtime.lean_entry as lean_entry
from runtime.lean_entry import BctEngineAlgorithm


class FakeSym:
    def __init__(self, v: str) -> None:
        self.value = v

    def __hash__(self) -> int:
        return hash(self.value)

    def __eq__(self, o: object) -> bool:
        return isinstance(o, FakeSym) and o.value == self.value


class FakeEquity:
    def __init__(self) -> None:
        self.norm = None

    def set_data_normalization_mode(self, m: object) -> None:
        self.norm = m


class FakeHolding:
    def __init__(self, invested: bool) -> None:
        self.invested = invested


class FakePortfolio:
    def __init__(self) -> None:
        self._held: dict[FakeSym, bool] = {}

    def __getitem__(self, sym: FakeSym) -> FakeHolding:
        return FakeHolding(self._held.get(sym, False))


def _make_algo(monkeypatch, *, warming: bool = False) -> BctEngineAlgorithm:
    """A BctEngineAlgorithm with just enough state to run the intraday lifecycle locally."""
    monkeypatch.setattr(lean_entry, "DataNormalizationMode", type("DN", (), {"RAW": 1}))
    monkeypatch.setattr(lean_entry, "Resolution", type("R", (), {"MINUTE": 1, "DAILY": 2}))
    # IchimokuKinkoHyo / RollingWindow are None in the dev venv — stub minimal constructibles.
    monkeypatch.setattr(lean_entry, "IchimokuKinkoHyo",
                        lambda *a, **k: type("I", (), {"update": lambda self, b: None})())
    monkeypatch.setattr(lean_entry, "RollingWindow",
                        type("RW", (), {"__class_getitem__": classmethod(lambda cls, t: (
                            lambda n: type("W", (), {"add": lambda self, v: None})()))}))
    algo = BctEngineAlgorithm()  # QCAlgorithm == object locally
    algo.time = datetime(2025, 6, 2)
    algo.is_warming_up = warming
    algo._active = set()
    algo._intraday = {}
    algo._intraday_active = set()
    algo.portfolio = FakePortfolio()
    algo.logged: list[str] = []
    algo.log = lambda m: algo.logged.append(m)  # type: ignore[method-assign,assignment]
    algo._added: list[str] = []
    algo._removed: list[FakeSym] = []
    algo.add_equity = lambda v, res: (algo._added.append(v), FakeEquity())[1]  # type: ignore
    algo.remove_security = lambda s: algo._removed.append(s)  # type: ignore
    # seed-on-subscribe: stub history so the seed path is exercised but inert (no QC types)
    algo.history = lambda *a, **k: None  # type: ignore
    return algo


# ── subscribe ──

def test_subscribe_adds_minute_feed_and_indicators(monkeypatch) -> None:
    algo = _make_algo(monkeypatch)
    sym = FakeSym("AAPL")
    algo._subscribe_intraday(sym)
    assert sym in algo._intraday and sym in algo._intraday_active
    assert "AAPL" in algo._added  # add_equity(MINUTE) called
    assert set(algo._intraday[sym]) >= {"intraday_tenkan", "vol_window", "last_close", "last_bar"}


def test_subscribe_is_idempotent(monkeypatch) -> None:
    algo = _make_algo(monkeypatch)
    sym = FakeSym("AAPL")
    algo._subscribe_intraday(sym)
    algo._subscribe_intraday(sym)
    assert algo._added.count("AAPL") == 1  # not double-subscribed


# ── the LEAK test (the load-bearing one) ──

def test_unsubscribe_tears_down_completely(monkeypatch) -> None:
    # subscribe → rotate out → assert the indicators AND the security subscription are removed
    # (no accumulation across rotation — RemoveSecurity doesn't auto-dispose, so we must).
    algo = _make_algo(monkeypatch)
    sym = FakeSym("AAPL")
    algo._subscribe_intraday(sym)
    algo._unsubscribe_intraday(sym)
    assert sym not in algo._intraday, "intraday indicator state leaked after rotation"
    assert sym not in algo._intraday_active
    assert sym in algo._removed, "remove_security not called → 5-min subscription leaked"


def test_no_leak_across_many_rotations(monkeypatch) -> None:
    # subscribe/rotate 100 distinct names → _intraday must never accumulate (the #213e leak guard).
    algo = _make_algo(monkeypatch)
    for i in range(100):
        s = FakeSym(f"T{i}")
        algo._subscribe_intraday(s)
        algo._unsubscribe_intraday(s)
    assert len(algo._intraday) == 0 and len(algo._intraday_active) == 0


def test_held_name_keeps_its_feed(monkeypatch) -> None:
    # an INVESTED name must NOT be torn down (exits run on the intraday clock — don't drop the feed).
    algo = _make_algo(monkeypatch)
    sym = FakeSym("AAPL")
    algo._subscribe_intraday(sym)
    algo.portfolio._held[sym] = True  # now invested
    algo._unsubscribe_intraday(sym)
    assert sym in algo._intraday, "held name's intraday feed was wrongly torn down"
    assert sym not in algo._removed


# ── cold-seed ──

def test_post_warmup_entrant_is_seeded(monkeypatch) -> None:
    # post-warmup subscribe → the seed path runs (warm before first score, anti-cold-mirage).
    algo = _make_algo(monkeypatch, warming=False)
    seeded: list[object] = []
    algo._seed_intraday = lambda *a, **k: seeded.append(a[0])  # type: ignore
    sym = FakeSym("AAPL")
    algo._subscribe_intraday(sym)
    assert seeded == [sym], "post-warmup entrant not seeded → cold on first intraday bar"


def test_warmup_subscribe_does_not_seed(monkeypatch) -> None:
    # during warmup QC auto-warms the subscription → no manual seed (mirrors _seed_daily guard).
    algo = _make_algo(monkeypatch, warming=True)
    seeded: list[object] = []
    algo._seed_intraday = lambda *a, **k: seeded.append(a[0])  # type: ignore
    algo._subscribe_intraday(FakeSym("AAPL"))
    assert seeded == [], "seeded during warmup (QC already auto-warms the subscription)"


# ── the CAP + sync ──

def test_sync_caps_the_candidate_slice(monkeypatch) -> None:
    # candidate set > CAP → only CAP-many intraday subscriptions, and the cap is logged.
    algo = _make_algo(monkeypatch)
    algo.INTRADAY_SUBSCRIBE_CAP = 5
    cands = [f"T{i}" for i in range(20)]
    algo._active = {FakeSym(t) for t in cands}
    algo._sync_intraday_subscriptions(cands)
    assert len(algo._intraday_active) == 5, "cap did not bind the intraday subscription set"
    assert any("INTRADAY_CAP" in m for m in algo.logged), "cap not logged"


def test_sync_rotates_subscriptions(monkeypatch) -> None:
    # day 1 candidates {A,B} → day 2 {B,C}: A torn down (not held), B kept, C added.
    algo = _make_algo(monkeypatch)
    a, b, c = FakeSym("A"), FakeSym("B"), FakeSym("C")
    algo._active = {a, b, c}
    algo._sync_intraday_subscriptions(["A", "B"])
    assert algo._intraday_active == {a, b}
    algo._sync_intraday_subscriptions(["B", "C"])
    assert algo._intraday_active == {b, c}, "rotation wrong: A should drop, C should add, B stay"
    assert a in algo._removed


def test_sync_keeps_held_even_if_dropped_from_candidates(monkeypatch) -> None:
    # a held name dropped from the candidate list keeps its feed (exits run intraday).
    algo = _make_algo(monkeypatch)
    a, b = FakeSym("A"), FakeSym("B")
    algo._active = {a, b}
    algo._sync_intraday_subscriptions(["A", "B"])
    algo.portfolio._held[a] = True       # A now invested
    algo._sync_intraday_subscriptions(["B"])  # A dropped from candidates
    assert a in algo._intraday_active, "held name's feed dropped on candidate rotation"


def test_held_then_closed_is_torn_down_no_slow_leak(monkeypatch) -> None:
    # The slow-leak guard: a held name dropped from candidates keeps its feed WHILE invested, but
    # once EXITED (no longer invested) the next daily sync MUST tear it down — else held-then-closed
    # names accumulate forever (the #213e slow-leak the build-risks note flagged).
    algo = _make_algo(monkeypatch)
    a, b = FakeSym("A"), FakeSym("B")
    algo._active = {a, b}
    algo._sync_intraday_subscriptions(["A", "B"])
    algo.portfolio._held[a] = True
    algo._sync_intraday_subscriptions(["B"])           # A held + off-candidates → kept
    assert a in algo._intraday_active
    algo.portfolio._held[a] = False                    # A now exited
    algo._sync_intraday_subscriptions(["B"])           # next daily sync
    assert a not in algo._intraday_active, "held-then-closed name leaked (never torn down)"
    assert a in algo._removed
