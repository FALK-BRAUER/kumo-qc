"""#263 — ACTIVE-SET NON-EMPTY integration (the #173-class guard), REAL conformed coarse.

This complements tests/data/test_warmup_coarse.py (which asserts the on-disk warmup FILES are
non-empty + 8-col QC-native). THIS file goes one rung further: it DRIVES the real selection
gate `BctEngineAlgorithm._coarse_selection` over the REAL conformed coarse rows and asserts the
SELECTED ranked set (prefilter → maintained rolling-DV → apply_floors → rank_and_cap) is
non-empty across the warmup window AND the FY2025 window — the actual #173 failure mode (an
empty SELECTED universe starves indicator warmup → the fake −0.616 baseline), not merely an
empty file.

THE BROKEN-0 vs CORRECT-0 DISTINCTION (Falk's mandate): a zero-ranked day must be
distinguishable —
  - CORRECT-0: the coarse feed is genuinely empty (a market holiday / no data legitimately) →
    _coarse_selection returns [] and _ranked_today == [] (the universe phase then emits empty,
    no raise). Tested with a genuinely-empty feed.
  - BROKEN-0: a real trading day's coarse feed is present + full but the SELECTION collapses to
    empty → that is a data/wiring break the integration must catch (assert non-empty on every
    real day). A silent empty-universe on a populated day is exactly the −0.616 mirage.

If the local data tree is absent (CI without the gitignored data/), the tests SKIP with a
reason — a data-presence guard, not a unit of pure logic (those live in test_lean_entry).
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

import runtime.lean_entry as lean_entry
from engine.base import DegradedDataError
from runtime.lean_entry import BctEngineAlgorithm

_ROOT = Path(__file__).resolve().parents[2]
_COARSE = _ROOT / "data" / "equity" / "usa" / "fundamental" / "coarse"

# Sample real sessions: warmup-window span + FY2025 boundaries (each must SELECT non-empty).
_WARMUP_DAYS = ["20230620", "20231002", "20240701", "20241231"]
_FY_DAYS = ["20250102", "20250603", "20251231"]


def _have_local_data() -> bool:
    return _COARSE.is_dir() and any(_COARSE.glob("2025*.csv"))


pytestmark = pytest.mark.skipif(
    not _have_local_data(),
    reason="local LEAN coarse tree absent (gitignored data/) — data-presence guard skips",
)


# ---------------------------------------------------------------------------
# Drive the REAL _coarse_selection over real coarse rows. Stub only the QC Symbol
# factory (None in the dev venv) — every selection step (prefilter, rolling-DV,
# apply_floors, rank_and_cap) is the REAL engine code.
# ---------------------------------------------------------------------------
class _FakeSymbol:
    def __init__(self, value: str) -> None:
        self.value = value

    def __hash__(self) -> int:
        return hash(self.value)

    def __eq__(self, o: object) -> bool:
        return isinstance(o, _FakeSymbol) and o.value == self.value


class _SymbolFactory:
    @staticmethod
    def create(ticker, _sectype, _market):  # mimics Symbol.create(ticker, EQUITY, USA)
        return _FakeSymbol(ticker)


class _Sym:
    def __init__(self, value: str) -> None:
        self.value = value


class _CoarseRow:
    """Real 8-col QC-native row → the coarse-object shape _coarse_selection reads."""

    def __init__(self, row: str) -> None:
        cols = row.split(",")
        self.symbol = _Sym(cols[1])
        self.price = float(cols[2])
        self.dollar_volume = float(cols[4])


def _make_algo(monkeypatch) -> BctEngineAlgorithm:
    monkeypatch.setattr(lean_entry, "Symbol", _SymbolFactory)
    monkeypatch.setattr(lean_entry, "SecurityType", type("ST", (), {"EQUITY": 1}))
    monkeypatch.setattr(lean_entry, "Market", type("MK", (), {"USA": "usa"}))
    algo = BctEngineAlgorithm()  # QCAlgorithm == object locally
    algo._dv_windows = {}
    algo._dv_day_index = -1
    algo._ranked_today = []
    algo._trailing_dv = {}
    algo._bar_metrics = {}
    algo.time = dt.datetime(2025, 1, 2)
    algo.logged = []
    algo.log = lambda m: algo.logged.append(m)  # type: ignore[method-assign,assignment]
    return algo


def _feed_for(ymd: str) -> list[_CoarseRow]:
    rows = [ln for ln in (_COARSE / f"{ymd}.csv").read_text().splitlines() if ln]
    return [_CoarseRow(r) for r in rows]


# ── NON-EMPTY selection on every real day (the #173 guard at the SELECTION grain) ─


@pytest.mark.parametrize("ymd", _WARMUP_DAYS + _FY_DAYS)
def test_selection_nonempty_on_real_day(monkeypatch, ymd: str) -> None:
    # A populated real coarse day MUST select a non-empty ranked set. An empty selection on a
    # full feed is the BROKEN-0 (#173 empty-universe mirage) this guard exists to catch.
    algo = _make_algo(monkeypatch)
    feed = _feed_for(ymd)
    assert len(feed) > 1000, f"{ymd} coarse feed unexpectedly sparse ({len(feed)} rows)"
    ranked = algo._coarse_selection(feed)
    assert ranked, f"BROKEN-0: real day {ymd} selected an EMPTY universe from {len(feed)} rows"
    assert algo._ranked_today, f"{ymd}: _ranked_today empty on a populated feed"
    # the floors are real: the selected set is a strict subset of the input (liquidity bound).
    assert len(ranked) < len(feed)


def test_selection_nonempty_across_full_warmup_stream(monkeypatch) -> None:
    # Drive the warmup days IN SEQUENCE through one algo so the rolling-DV window accumulates
    # exactly as in a real run (each day's selection uses the maintained trailing mean). Every
    # day must remain non-empty — the empty-warmup mirage was a CONTIGUOUS empty stream.
    algo = _make_algo(monkeypatch)
    for ymd in _WARMUP_DAYS:
        ranked = algo._coarse_selection(_feed_for(ymd))
        assert ranked, f"BROKEN-0: warmup day {ymd} selected empty in-sequence"
    # the maintained windows accumulated across the streamed days (not reset each day).
    assert algo._dv_day_index == len(_WARMUP_DAYS) - 1


# ── CORRECT-0 vs BROKEN-0: the distinguishability the mandate requires ─────────


def test_empty_feed_on_trading_day_raises_loud(monkeypatch) -> None:
    # #261-5 (FLIPPED from the #263 "correct-0 = empty []" pin): an empty coarse feed reaching
    # _coarse_selection means QC fired the callback on a REAL trading day with MISSING data — a
    # data gap, NOT a legitimate holiday (QC does not fire the coarse callback on a non-session
    # day; the local conform purges non-session orphan files). Empty == ALWAYS broken here → it
    # MUST fail loud with the date, never silently select [] (the #173 empty-warmup mirage).
    # #261 OWNS this contract: there is no legitimate empty-feed case, so the prior correct-0
    # pin is replaced by this raise assertion.
    algo = _make_algo(monkeypatch)
    with pytest.raises(DegradedDataError) as ei:
        algo._coarse_selection([])
    msg = str(ei.value)
    assert "empty coarse feed on a trading day" in msg
    assert "2025-01-02" in msg  # the date context is in the message
    assert "#261-5" in msg


def test_broken_zero_full_feed_below_prefilter_raises_loud(monkeypatch) -> None:
    # #261-6 (FLIPPED from the #263 "visibly empty, not raise" pin): a FULL feed (2000 names)
    # where every name is below the prefilter/floor (degraded data — e.g. the DV column
    # corrupted to tiny values) COLLAPSES to a zero selection. This is the −0.616 mirage (full
    # feed in, empty universe out, nothing crashing). The (names_in, ranked) pair distinguishes
    # it from correct-0 (which already raised on names_in==0): here names_in >> 0 yet 0 selected
    # → RAISE broken-0 with the input count, never a silent empty universe.
    algo = _make_algo(monkeypatch)
    below = [
        type("C", (), {"symbol": _Sym(f"t{i}"), "price": 50.0, "dollar_volume": 1.0e6})()
        for i in range(2000)
    ]
    with pytest.raises(DegradedDataError) as ei:
        algo._coarse_selection(below)
    msg = str(ei.value)
    assert "broken-0 selection on a populated coarse feed" in msg
    assert "names_in=2000" in msg  # the input-count context distinguishes it from correct-0
    assert "#261-6" in msg


def test_empty_coarse_file_zero_rows_reads_to_empty_feed(tmp_path) -> None:
    # A completely-empty coarse FILE (0 rows on disk) reads to an EMPTY feed — the correct-0
    # input. (Mirrors the warmup file-grain read.) An empty file is NOT a parse error; it is a
    # legitimate zero-row day that the selection then handles as correct-0 (empty -> []).
    empty_fp = tmp_path / "20250704.csv"  # e.g. July 4th holiday, no session
    empty_fp.write_text("")
    rows = [ln for ln in empty_fp.read_text().splitlines() if ln]
    assert rows == []  # 0 rows -> empty feed (correct-0, distinguishable from a populated day)


# #261 RESOLUTION (was a #263 deferral): the MISSING-coarse-file-on-a-known-trading-day fail-loud
# case is now implemented in the selection gate itself. INVESTIGATION RESULT: QC drives
# CoarseFundamentalUniverseSelection off its OWN NYSE trading calendar — the callback fires once
# per real session and is NEVER invoked on a market holiday, regardless of stray files on disk.
# THAT CALENDAR is the guarantee. (clean_orphan_files is belt-and-suspenders meant to purge stale
# non-session files; the tree currently still carries ~14 US-holiday orphans — header-only or
# foreign-exchange tickers, no SPY bars — so do NOT rely on the purge having run; QC's calendar
# excludes those days anyway. Real FY2025 session feeds carry >10k rows each.) So the callback
# firing AT ALL means QC already determined it is a real session; an EMPTY feed at that point ==
# a data gap, not a holiday. The day-loop knowledge the #263 note wanted lives IN QC's callback
# contract — the gate can rely on it. The guard therefore lives in _coarse_selection (no external
# day-loop needed), tested by test_empty_feed_on_trading_day_raises_loud above (#261-5).


def test_real_day_distinguishable_from_degraded_by_input_count(monkeypatch) -> None:
    # The distinguisher the mandate asks for, made explicit AFTER #261: on a REAL session the
    # INPUT feed is large (>1000) and the SELECTION is non-empty (healthy: large, >0). Under
    # #261 there is NO silent-empty path — both degraded ends now RAISE: an empty input feed
    # (names_in==0, the missing-data gap, #261-5) and a full feed collapsing to zero (large, 0,
    # the broken-0, #261-6). The (input_count, ranked_count) pair still separates the cases; the
    # difference is the degraded ones fail loud rather than silently yielding [].
    algo = _make_algo(monkeypatch)
    real_feed = _feed_for(_FY_DAYS[0])
    real_ranked = algo._coarse_selection(real_feed)
    assert (len(real_feed) > 1000) and (len(real_ranked) > 0)  # healthy: (large, >0)

    # empty input is no longer a silent correct-0 — it is the #261-5 data-gap raise.
    algo2 = _make_algo(monkeypatch)
    with pytest.raises(DegradedDataError):
        algo2._coarse_selection([])
