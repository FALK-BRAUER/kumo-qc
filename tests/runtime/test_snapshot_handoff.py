"""#276b-0 — daily→intraday SNAPSHOT handoff (the GH#25 execution enabler).

Pins the 3 hardenings (HQ-locked, real-money correctness):
- REUSE-IDENTITY capture: the snapshot is keyed by the SAME canonical Symbol `_active`/`_intraday`
  hold (never a re-created one) → a subscribed≠decided desync cannot occur by construction.
- H1 snapshot-is-authority: a symbol with no decided thesis → skip-loud, NEVER an unauthorized entry.
- H2 staleness fail-loud: a stale decision_date → DegradedDataError (the SG9 desync tripwire).
- H3/SG9: session-end clears the confirm PROGRESS (no T+1→T+2 bleed); snapshot survives (overwritten
  only by the next daily decision).
Each guard paired with a control (mutation-bite).
"""
from __future__ import annotations

from datetime import date, datetime

import pytest

from engine.base import DegradedDataError
from runtime.lean_entry import BctEngineAlgorithm


class FakeSym:
    def __init__(self, v: str) -> None:
        self.value = v

    def __hash__(self) -> int:
        return hash(self.value)

    def __eq__(self, o: object) -> bool:
        return isinstance(o, FakeSym) and o.value == self.value


class FakeKijun:
    def __init__(self, v: float) -> None:
        self.current = type("C", (), {"value": v})()


class FakeDIchi:
    def __init__(self, kijun: float, ready: bool = True) -> None:
        self.is_ready = ready
        self.kijun = FakeKijun(kijun)


class FakeSec:
    def __init__(self, price: float) -> None:
        self.price = price


class FakeSecurities:
    def __init__(self, prices: dict) -> None:
        self._p = prices

    def __getitem__(self, sym: object) -> FakeSec:
        return FakeSec(self._p[sym])


def _algo(active_syms: list, ranked: list[str], indicators: dict, prices: dict,
          *, decision: date = date(2025, 6, 2)) -> BctEngineAlgorithm:
    a = BctEngineAlgorithm()  # QCAlgorithm == object locally; __init__ sets the handoff dicts
    a._active = set(active_syms)
    a._intraday = {s: {} for s in active_syms}  # subscribed set — SAME canonical identities
    a._indicators = indicators
    a._ranked_today = ranked
    a.securities = FakeSecurities(prices)  # type: ignore[assignment]
    a.time = datetime(decision.year, decision.month, decision.day)  # type: ignore[assignment]
    a.logged = []  # type: ignore[attr-defined]
    a.log = lambda m: a.logged.append(m)  # type: ignore[assignment,method-assign]
    return a


# ── reuse-identity capture ──

def test_capture_keys_by_canonical_symbol_identity() -> None:
    aapl, msft = FakeSym("AAPL"), FakeSym("MSFT")
    inds = {aapl: {"d_ichi": FakeDIchi(140.0)}, msft: {"d_ichi": FakeDIchi(400.0)}}
    a = _algo([aapl, msft], ["aapl", "msft"], inds, {aapl: 150.0, msft: 410.0})
    a._capture_candidate_snapshot()
    assert set(a._candidate_snapshot) == {aapl, msft}
    for k in a._candidate_snapshot:
        # the desync tripwire AS A TEST: every snapshot key is the SAME object _active/_intraday
        # hold (identity, not just equality) — proves no Symbol was re-created.
        assert any(k is s for s in a._active), "snapshot key must BE a canonical _active Symbol"
        assert k in a._intraday
    assert a._candidate_snapshot[aapl] == {
        "signal_price": 150.0, "daily_kijun": 140.0, "decision_date": date(2025, 6, 2)
    }


def test_capture_skips_unsubscribed_candidate() -> None:
    # a ranked ticker with NO canonical _active Symbol (subscription lag) is skipped — never
    # re-created. H1 covers it on the intraday side.
    aapl = FakeSym("AAPL")
    a = _algo([aapl], ["aapl", "tsla"], {aapl: {"d_ichi": FakeDIchi(140.0)}}, {aapl: 150.0})
    a._capture_candidate_snapshot()
    assert set(a._candidate_snapshot) == {aapl}


def test_capture_skips_cold_daily_ichimoku() -> None:
    aapl = FakeSym("AAPL")
    a = _algo([aapl], ["aapl"], {aapl: {"d_ichi": FakeDIchi(140.0, ready=False)}}, {aapl: 150.0})
    a._capture_candidate_snapshot()
    assert a._candidate_snapshot == {}, "a cold daily thesis must NOT be snapshotted"


def test_capture_rebuilt_fresh_drops_stale_name() -> None:
    # rebuilt each decision: a name dropped from today's ranked set disappears from the snapshot.
    aapl, msft = FakeSym("AAPL"), FakeSym("MSFT")
    inds = {aapl: {"d_ichi": FakeDIchi(140.0)}, msft: {"d_ichi": FakeDIchi(400.0)}}
    a = _algo([aapl, msft], ["aapl", "msft"], inds, {aapl: 150.0, msft: 410.0})
    a._capture_candidate_snapshot()
    assert set(a._candidate_snapshot) == {aapl, msft}
    a._ranked_today = ["aapl"]  # msft dropped from today's decision
    a._capture_candidate_snapshot()
    assert set(a._candidate_snapshot) == {aapl}


# ── H1 snapshot-is-authority ──

def test_snapshot_for_entry_missing_is_skiploud_not_entry() -> None:
    aapl, ghost = FakeSym("AAPL"), FakeSym("GHOST")
    a = _algo([aapl], ["aapl"], {aapl: {"d_ichi": FakeDIchi(140.0)}}, {aapl: 150.0})
    a._capture_candidate_snapshot()
    a._last_daily_date = date(2025, 6, 2)
    assert a.snapshot_for_entry(ghost) is None, "undecided symbol must NOT be enterable"
    assert any("SNAPSHOT_SKIP" in m for m in a.logged), "must skip-LOUD, not silently"


# ── H2 staleness fail-loud ──

def test_snapshot_for_entry_stale_raises() -> None:
    aapl = FakeSym("AAPL")
    a = _algo([aapl], ["aapl"], {aapl: {"d_ichi": FakeDIchi(140.0)}}, {aapl: 150.0})
    a._capture_candidate_snapshot()  # decision_date = 2025-06-02
    a._last_daily_date = date(2025, 6, 4)  # a later decision ran → the snapshot is 2-day stale
    with pytest.raises(DegradedDataError, match="stale candidate snapshot"):
        a.snapshot_for_entry(aapl)


def test_snapshot_for_entry_fresh_returns() -> None:
    # MUTATION-BITE control for the stale case: matching decision_date → returns the thesis.
    aapl = FakeSym("AAPL")
    a = _algo([aapl], ["aapl"], {aapl: {"d_ichi": FakeDIchi(140.0)}}, {aapl: 150.0})
    a._capture_candidate_snapshot()
    a._last_daily_date = date(2025, 6, 2)
    snap = a.snapshot_for_entry(aapl)
    assert snap is not None and snap["daily_kijun"] == 140.0 and snap["signal_price"] == 150.0


# ── H3 / SG9 session-end clear ──

def test_session_end_clears_entry_confirm_progress() -> None:
    a = _algo([], [], {}, {})
    a._entry_confirm = {FakeSym("AAPL"): {"bars_seen": 3}}  # partial confirm at T+1 close
    a.on_end_of_day()
    assert a._entry_confirm == {}, "confirm progress must clear at session end (no T+2 bleed, SG9)"


def test_session_end_clear_preserves_snapshot() -> None:
    # boundary precision: the session-end clear touches the confirm PROGRESS only, NOT the snapshot
    # (the snapshot is overwritten by the next daily decision, not the session-end event).
    aapl = FakeSym("AAPL")
    a = _algo([aapl], ["aapl"], {aapl: {"d_ichi": FakeDIchi(140.0)}}, {aapl: 150.0})
    a._capture_candidate_snapshot()
    a._entry_confirm = {aapl: {"bars_seen": 2}}
    a.on_end_of_day()
    assert a._entry_confirm == {}
    assert aapl in a._candidate_snapshot, "snapshot must survive the session-end boundary"
