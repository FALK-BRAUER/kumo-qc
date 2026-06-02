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
    def __init__(self, sym: Any, status: Any, order_id: Any = None) -> None:
        self.symbol = sym
        self.status = status
        self.order_id = order_id


class _Ticket:
    def __init__(self, order_id: Any) -> None:
        self.order_id = order_id


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
    qc._entered_today = set()  # initialize() sets this in prod; the local harness mirrors it
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


# ── #277 GTC-floor-fill cleanup (broker stop fires → pop _position_meta so re-entry is clean) ──

def test_floor_fill_pops_position_meta_and_clears_pending(monkeypatch) -> None:
    # the GTC protective stop (order_id 5) FILLS broker-side (floor fired) → pop meta + clear pending
    # → a later re-entry is clean (no GUARD-3 fail-loud on a stale ticket). The bug Rank-1 exposed.
    monkeypatch.setattr(lean_entry, "OrderStatus", _OS)
    qc = _qc(["AAPL"], pending=("AAPL",))
    sym = qc._syms["AAPL"]
    qc._position_meta = {sym: {"protective_stop_ticket": _Ticket(order_id=5), "entry_price": 100.0}}
    qc.on_order_event(_OE(sym, _OS.Filled, order_id=5))   # the floor ticket fills
    assert sym not in qc._position_meta                    # meta cleared → re-entry won't hit GUARD-3
    assert sym not in qc._pending_entry_today


def test_non_floor_fill_does_not_pop_meta(monkeypatch) -> None:
    # a DIFFERENT order filling (id 9 ≠ the floor's id 5 — e.g. the entry fill) must NOT pop the
    # floor meta (the position is live + protected; only the floor's own fill clears it).
    monkeypatch.setattr(lean_entry, "OrderStatus", _OS)
    qc = _qc(["AAPL"])
    sym = qc._syms["AAPL"]
    qc._position_meta = {sym: {"protective_stop_ticket": _Ticket(order_id=5), "entry_price": 100.0}}
    qc.on_order_event(_OE(sym, _OS.Filled, order_id=9))
    assert sym in qc._position_meta                        # floor meta intact (different order)


def test_floor_PARTIAL_fill_keeps_meta_intact_no_orphan(monkeypatch) -> None:
    # Gemini CRITICAL: a PARTIAL floor fill leaves the remainder LIVE at the broker → must NOT pop
    # meta (popping loses the ticket → orphan stop → over-sell). Floor-cleanup is Filled-ONLY.
    monkeypatch.setattr(lean_entry, "OrderStatus", _OS)
    qc = _qc(["AAPL"])
    sym = qc._syms["AAPL"]
    qc._position_meta = {sym: {"protective_stop_ticket": _Ticket(order_id=5), "entry_price": 100.0}}
    qc.on_order_event(_OE(sym, _OS.PartiallyFilled, order_id=5))  # partial floor fill
    assert sym in qc._position_meta, "PARTIAL floor fill must NOT pop meta (remainder still live)"


def test_runtime_exit_already_popped_meta_is_noop(monkeypatch) -> None:
    # the runtime FIRE_EXITS path already pops _position_meta; a subsequent event finds no meta →
    # the floor-cleanup is a harmless no-op (idempotent — no double-pop crash).
    monkeypatch.setattr(lean_entry, "OrderStatus", _OS)
    qc = _qc(["AAPL"])
    sym = qc._syms["AAPL"]
    qc._position_meta = {}  # FIRE_EXITS already popped it
    qc.on_order_event(_OE(sym, _OS.Filled, order_id=5))    # must not raise
    assert qc._position_meta == {}


# ── SHOP same-session re-entry guard (the churn fix) ──

def test_filled_entry_blocks_same_session_reentry_after_stopout(monkeypatch) -> None:
    # THE SHOP churn: entry FILLS → invested. Its #290 GTC floor fires same-minute → flat again
    # (not invested, not pending). WITHOUT the guard it was re-injectable → re-fired → instant
    # stop-out churn (SHOP 7× in 30min). The _entered_today guard: a filled entry is done for the
    # session even when flat.
    monkeypatch.setattr(lean_entry, "OrderStatus", _OS)
    qc = _qc(["SHOP"], pending=("SHOP",))
    assert _inject(qc) == []                                  # in-flight → skipped
    qc.on_order_event(_OE(qc._syms["SHOP"], _OS.Filled))      # entry filled
    assert qc._syms["SHOP"] in qc._entered_today
    # broker floor sells it back to flat: not invested, not pending — but entered THIS session
    assert _inject(qc) == [], "a filled-then-stopped name must NOT re-enter the same session"


def test_partial_fill_also_marks_entered(monkeypatch) -> None:
    monkeypatch.setattr(lean_entry, "OrderStatus", _OS)
    qc = _qc(["AAPL"], pending=("AAPL",))
    qc.on_order_event(_OE(qc._syms["AAPL"], _OS.PartiallyFilled))
    assert qc._syms["AAPL"] in qc._entered_today
    assert _inject(qc) == []


def test_reject_does_not_mark_entered_stays_reinjectable(monkeypatch) -> None:
    # a Canceled/Invalid reject is NOT a fill → must NOT enter _entered_today (retry-on-reject lives).
    monkeypatch.setattr(lean_entry, "OrderStatus", _OS)
    qc = _qc(["AAPL"], pending=("AAPL",))
    qc.on_order_event(_OE(qc._syms["AAPL"], _OS.Canceled))
    assert qc._syms["AAPL"] not in qc._entered_today
    assert _inject(qc) == ["AAPL"]                            # still re-injectable


def test_session_end_clears_entered_guard(monkeypatch) -> None:
    # next session re-allows entry (no T+2 bleed).
    monkeypatch.setattr(lean_entry, "OrderStatus", _OS)
    qc = _qc(["SHOP"], pending=("SHOP",))
    qc.on_order_event(_OE(qc._syms["SHOP"], _OS.Filled))
    assert _inject(qc) == []
    qc.on_end_of_day()
    assert qc._entered_today == set()
    assert _inject(qc) == ["SHOP"], "next session the name is entry-eligible again"


# ── #archive B2: the entry-context tag (the durable learn-substrate channel) ──

def test_build_entry_tag_emits_decision_context() -> None:
    from urllib.parse import parse_qs

    class _Vol:
        def __init__(self, vals: list) -> None: self._v = vals
        @property
        def count(self) -> int: return len(self._v)
        def __getitem__(self, i: int): return self._v[i]

    class _Bar: volume = 2000.0
    class _Cur:
        def __init__(self, v: float) -> None: self.value = v
    class _Tk:
        is_ready = True
        def __init__(self, v: float) -> None: self.current = _Cur(v)

    sym = _Sym("AAPL")
    a = BctEngineAlgorithm()
    a._candidate_snapshot = {sym: {"signal_price": 100.0, "score": 8,
                                   "conditions": [True, True, True, True, True, True, True, True]}}
    a._intraday = {sym: {"last_close": 104.0, "vol_window": _Vol([1000.0, 1000.0]),
                         "last_bar": _Bar(), "intraday_tenkan": _Tk(102.0)}}
    a._ranked_today = ["MSFT", "AAPL"]
    q = parse_qs(a._build_entry_tag(sym))
    assert q["decision_score"] == ["8"]
    assert q["decision_cond"] == ["11111111"]          # 8 bits, stable order
    assert q["decision_gap"] == ["0.0400"]             # (104-100)/100
    assert q["decision_vol"] == ["2.000"]              # 2000 / mean(1000,1000)
    assert q["decision_tdist"] == ["0.0192"]           # (104-102)/104
    assert q["decision_rank"] == ["1"]                 # index in _ranked_today


def test_build_entry_tag_omits_missing_pieces_never_fakes() -> None:
    # a sparse state → only the resolvable fields appear (no fabricated zeros).
    sym = _Sym("AAPL")
    a = BctEngineAlgorithm()
    a._candidate_snapshot = {sym: {"signal_price": 100.0, "score": 7, "conditions": []}}
    a._intraday = {sym: {}}
    a._ranked_today = []
    from urllib.parse import parse_qs
    q = parse_qs(a._build_entry_tag(sym))
    assert q["decision_score"] == ["7"]
    assert "decision_cond" not in q and "decision_gap" not in q and "decision_vol" not in q


def test_build_entry_tag_fails_loud_over_cap() -> None:
    from engine.base import DegradedDataError
    sym = _Sym("AAPL")
    a = BctEngineAlgorithm()
    a.ENTRY_TAG_MAX = 10  # force the cap
    a._candidate_snapshot = {sym: {"signal_price": 100.0, "score": 8,
                                   "conditions": [True] * 8}}
    a._intraday = {sym: {}}
    a._ranked_today = []
    try:
        a._build_entry_tag(sym)
        assert False, "must fail loud over the tag cap"
    except DegradedDataError as e:
        assert "truncate" in str(e)


# ── #276b-1 FIX3: rank resolves regardless of CASE (the cloud rank=None omit bug) ──
# On cloud _ranked_today holds LOWERCASE tickers (coarse-derived) but a QC Symbol's .value is
# UPPERCASE → the old `val in ranked` was ALWAYS False → rank omitted for EVERY entry. The fix
# normalizes both sides through canonical_symbol_key so rank resolves whatever the case.

def test_build_entry_tag_rank_resolves_when_ranked_today_is_lowercase() -> None:
    # the REAL cloud case: _ranked_today lowercase, sym.value uppercase. Rank must still populate.
    from urllib.parse import parse_qs

    sym = _Sym("AAPL")  # .value uppercase, as QC delivers
    a = BctEngineAlgorithm()
    a._candidate_snapshot = {sym: {"signal_price": 100.0, "score": 8, "conditions": []}}
    a._intraday = {sym: {}}
    a._ranked_today = ["msft", "aapl", "goog"]  # lowercase, as the coarse path stores
    q = parse_qs(a._build_entry_tag(sym))
    assert q["decision_rank"] == ["1"]  # aapl is at index 1 — resolved despite case mismatch


def test_build_entry_tag_rank_resolves_uppercase_ranked_too() -> None:
    # symmetric: an uppercase _ranked_today (older fixtures / a future keying) must also resolve.
    from urllib.parse import parse_qs

    sym = _Sym("AAPL")
    a = BctEngineAlgorithm()
    a._candidate_snapshot = {sym: {"signal_price": 100.0, "score": 8, "conditions": []}}
    a._intraday = {sym: {}}
    a._ranked_today = ["MSFT", "AAPL"]
    q = parse_qs(a._build_entry_tag(sym))
    assert q["decision_rank"] == ["1"]


def test_build_entry_tag_omits_rank_on_genuine_absence() -> None:
    # OMIT-on-genuine-absence preserved: a candidate truly NOT in _ranked_today → no rank (not faked).
    from urllib.parse import parse_qs

    sym = _Sym("TSLA")
    a = BctEngineAlgorithm()
    a._candidate_snapshot = {sym: {"signal_price": 100.0, "score": 8, "conditions": []}}
    a._intraday = {sym: {}}
    a._ranked_today = ["aapl", "msft"]  # TSLA absent
    q = parse_qs(a._build_entry_tag(sym))
    assert "decision_rank" not in q


def test_canonical_symbol_key_normalizes_symbol_and_string() -> None:
    from runtime.lean_entry import canonical_symbol_key

    assert canonical_symbol_key(_Sym("AAPL")) == "aapl"  # QC Symbol → lowercase .value
    assert canonical_symbol_key("MSFT") == "msft"        # raw string → lowercase
    assert canonical_symbol_key("goog") == "goog"        # already-lowercase stable
