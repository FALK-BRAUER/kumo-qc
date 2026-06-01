"""#276b-1 — candidate-injection + the entry PENDING-STATE machine (the two-clock seam).

ctx.bar_state is fresh per 5-min tick; standing daily candidates live in qc._candidate_snapshot
(276b-0). _inject_intraday_candidates seeds qty=0 OrderIntent STUBS into the intraday bar_state so
entry_selection can gate them. The HQ/Gemini-reviewed invariants pinned here:
  1. RE-INJECTION via a PENDING-STATE machine (Gemini fix #1) — an in-flight entry is not re-injected
     (double-entry), but a broker REJECT (Canceled/Invalid via on_order_event) makes it re-injectable
     (a transient reject is not a permanently-lost trade). NOT a binary on-fire flag.
  2. ZERO-QTY stub never reaches the broker (Gemini fix #2) — covered by the existing engine test
     tests/engine/test_engine.py::test_fire_entries_skips_nonpositive_qty (the FIRE_ENTRIES qty<=0
     guard); here we assert the injected stub IS qty=0 so that guard is what protects it.
  3. RANK-PRESERVING injection (Gemini fix #3) — capital/BP is consumed highest-rank first.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import runtime.lean_entry as lean_entry
from engine.context import PhaseContext
from runtime.lean_entry import BctEngineAlgorithm


class _Sym:
    def __init__(self, v: str) -> None:
        self.value = v

    def __hash__(self) -> int:
        return hash(self.value)

    def __eq__(self, o: object) -> bool:
        return isinstance(o, _Sym) and o.value == self.value


class _Hold:
    def __init__(self, invested: bool) -> None:
        self.invested = invested


class _Portfolio(dict):
    def __getitem__(self, k: Any) -> _Hold:
        return self.get(k) or _Hold(False)  # type: ignore[return-value]


class _OS:  # fake OrderStatus (real enum absent in the dev venv)
    Filled = "filled"
    PartiallyFilled = "partial"
    Canceled = "canceled"
    Invalid = "invalid"
    Submitted = "submitted"


class _OE:
    def __init__(self, sym: Any, status: Any) -> None:
        self.symbol = sym
        self.status = status


def _qc(order: list[str], *, invested: tuple[str, ...] = (), pending: tuple[str, ...] = ()) -> Any:
    """A bare BctEngineAlgorithm (initialize() NOT run — QCAlgorithm==object locally) with the
    injection inputs set: a RANK-ORDERED snapshot, holdings, and the pending-entry set."""
    syms = {v: _Sym(v) for v in order}
    qc = BctEngineAlgorithm()
    qc.time = datetime(2025, 2, 4)
    qc.logged = []
    qc.log = lambda m: qc.logged.append(m)  # type: ignore[method-assign,assignment]
    # insertion order == rank order (the rank-preserving contract)
    qc._candidate_snapshot = {
        syms[v]: {"signal_price": 100.0, "daily_kijun": 95.0, "decision_date": "T"} for v in order
    }
    qc._pending_entry_today = {syms[v] for v in pending}
    qc.portfolio = _Portfolio({syms[v]: _Hold(True) for v in invested})
    qc._syms = syms
    return qc


def _inject(qc: Any) -> list[str]:
    ictx = PhaseContext(qc=qc, time=qc.time, data=None)
    qc._inject_intraday_candidates(ictx)
    return [i.ticker for i in ictx.bar_state.sized_orders]


# ── injection eligibility ──

def test_injects_all_eligible_candidates_as_zero_qty_stubs() -> None:
    qc = _qc(["AAPL", "TSLA"])
    ictx = PhaseContext(qc=qc, time=qc.time, data=None)
    qc._inject_intraday_candidates(ictx)
    stubs = ictx.bar_state.sized_orders
    assert [s.ticker for s in stubs] == ["AAPL", "TSLA"]
    assert all(s.qty == 0 for s in stubs), "injected stubs are qty=0 — FIRE_ENTRIES's qty<=0 guard blocks them"


def test_held_overnight_invested_blocks_reinjection() -> None:
    # SG8 / Gemini #1: a held name is NOT re-injected as an entry (its exits run on the intraday
    # clock via exit_hard, not as a candidate).
    qc = _qc(["AAPL", "TSLA"], invested=("AAPL",))
    assert _inject(qc) == ["TSLA"]


def test_pending_entry_blocks_reinjection_double_entry() -> None:
    # Gemini #1: an entry IN-FLIGHT this session is not re-injected (no double-entry).
    qc = _qc(["AAPL", "TSLA"], pending=("AAPL",))
    assert _inject(qc) == ["TSLA"]


def test_rank_preserving_injection_order() -> None:
    # Gemini #3: injection iterates the snapshot in RANK order → on a capital-constrained tick,
    # sizing/BP is consumed highest-rank first.
    qc = _qc(["RANK1", "RANK2", "RANK3"])
    assert _inject(qc) == ["RANK1", "RANK2", "RANK3"]


def test_empty_snapshot_injects_nothing() -> None:
    qc = _qc([])
    assert _inject(qc) == []


# ── the PENDING-STATE machine (on_order_event) ──

def test_reject_replay_canceled_makes_candidate_reinjectable(monkeypatch) -> None:
    # THE Gemini #1 case: fired → pending → rejected (Canceled) → re-injectable next tick.
    monkeypatch.setattr(lean_entry, "OrderStatus", _OS)
    qc = _qc(["AAPL"], pending=("AAPL",))
    assert _inject(qc) == []                       # in-flight → skipped
    qc.on_order_event(_OE(qc._syms["AAPL"], _OS.Canceled))   # broker rejected the entry
    assert qc._syms["AAPL"] not in qc._pending_entry_today
    assert _inject(qc) == ["AAPL"]                 # re-injectable (transient reject, second chance)


def test_invalid_status_also_reinjectable(monkeypatch) -> None:
    monkeypatch.setattr(lean_entry, "OrderStatus", _OS)
    qc = _qc(["AAPL"], pending=("AAPL",))
    qc.on_order_event(_OE(qc._syms["AAPL"], _OS.Invalid))
    assert _inject(qc) == ["AAPL"]


def test_filled_drops_pending_then_invested_covers(monkeypatch) -> None:
    # Filled → drop from pending; re-injection is then blocked by the INVESTED check (not pending).
    monkeypatch.setattr(lean_entry, "OrderStatus", _OS)
    qc = _qc(["AAPL"], pending=("AAPL",))
    qc.on_order_event(_OE(qc._syms["AAPL"], _OS.Filled))
    assert qc._syms["AAPL"] not in qc._pending_entry_today  # pending cleared
    # now mark invested (as the real portfolio would post-fill) → still not re-injected
    qc.portfolio[qc._syms["AAPL"]] = _Hold(True)
    assert _inject(qc) == []


def test_nonterminal_status_keeps_pending(monkeypatch) -> None:
    # Submitted is NOT terminal → stays pending (entry still in-flight, don't re-inject).
    monkeypatch.setattr(lean_entry, "OrderStatus", _OS)
    qc = _qc(["AAPL"], pending=("AAPL",))
    qc.on_order_event(_OE(qc._syms["AAPL"], _OS.Submitted))
    assert qc._syms["AAPL"] in qc._pending_entry_today
    assert _inject(qc) == []


def test_order_event_for_unpending_sym_is_noop(monkeypatch) -> None:
    # an exit/stop fill on a sym NOT in pending must not touch the pending set.
    monkeypatch.setattr(lean_entry, "OrderStatus", _OS)
    qc = _qc(["AAPL"], pending=("AAPL",))
    qc.on_order_event(_OE(_Sym("OTHER"), _OS.Filled))
    assert qc._syms["AAPL"] in qc._pending_entry_today


def test_mark_entry_pending_adds_to_set() -> None:
    qc = _qc(["AAPL"])
    qc._mark_entry_pending(qc._syms["AAPL"])
    assert qc._syms["AAPL"] in qc._pending_entry_today


def test_session_clear_resets_pending() -> None:
    qc = _qc(["AAPL"], pending=("AAPL",))
    qc._clear_intraday_session_state()
    assert qc._pending_entry_today == set()
