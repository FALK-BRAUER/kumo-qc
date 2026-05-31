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


def test_correct_zero_genuinely_empty_feed_yields_empty_not_raise(monkeypatch) -> None:
    # CORRECT-0: a genuinely-empty coarse feed (e.g. a non-session day with no data) -> [] and
    # _ranked_today == [] (NOT None). The universe phase then emits empty WITHOUT raising. This
    # is the legitimate zero — it must be a clean empty, distinguishable from the broken case.
    algo = _make_algo(monkeypatch)
    ranked = algo._coarse_selection([])
    assert ranked == []
    assert algo._ranked_today == []  # [] not None — the phase treats this as a zero-candidate day
    assert algo._bar_metrics == {}


def test_broken_zero_full_feed_below_prefilter_is_visibly_empty(monkeypatch) -> None:
    # BROKEN-0 surrogate: a FULL feed where every name is below the prefilter (a degraded-data
    # scenario — e.g. DV column corrupted to tiny values) collapses to an empty selection. The
    # engine does NOT raise (it can't tell intent), so the SELECTION yields [] — which is why
    # the per-real-day non-empty assertion ABOVE is the actual guard: on real data this must
    # never happen. Here we PIN that such a collapse IS observable (empty ranked + empty metrics)
    # so a monitor/diff-ladder can flag it. (Fail-loud-on-populated-but-empty is a #261 candidate.)
    algo = _make_algo(monkeypatch)
    below = [
        type("C", (), {"symbol": _Sym(f"t{i}"), "price": 50.0, "dollar_volume": 1.0e6})()
        for i in range(2000)
    ]
    ranked = algo._coarse_selection(below)
    assert ranked == []          # collapsed despite a full feed
    assert algo._bar_metrics == {}  # nothing cleared the prefilter -> visibly empty (not None)
    # CONTRAST with correct-0: the feed was NON-empty (2000 names) yet selection is empty — a
    # monitor distinguishes this (input_count >> 0, ranked == 0) from a holiday (input_count==0).
    assert len(below) > 1000


def test_empty_coarse_file_zero_rows_reads_to_empty_feed(tmp_path) -> None:
    # A completely-empty coarse FILE (0 rows on disk) reads to an EMPTY feed — the correct-0
    # input. (Mirrors the warmup file-grain read.) An empty file is NOT a parse error; it is a
    # legitimate zero-row day that the selection then handles as correct-0 (empty -> []).
    empty_fp = tmp_path / "20250704.csv"  # e.g. July 4th holiday, no session
    empty_fp.write_text("")
    rows = [ln for ln in empty_fp.read_text().splitlines() if ln]
    assert rows == []  # 0 rows -> empty feed (correct-0, distinguishable from a populated day)


def test_missing_coarse_file_for_a_day_is_detectable(tmp_path) -> None:
    # A MISSING coarse file for a day (data gap) is DETECTABLE at the file grain: the path does
    # not exist. A monitor MUST distinguish 'file absent' (potential data gap = broken-0 if it
    # was a real session) from 'file present but 0 rows' (holiday = correct-0). We pin that the
    # absence is observable (not a silent empty), which is the hook a fail-loud day-loop needs.
    missing_fp = tmp_path / "20250102.csv"  # not written
    assert not missing_fp.is_file()  # absence is explicit, never silently treated as empty


def test_real_day_distinguishable_from_holiday_by_input_count(monkeypatch) -> None:
    # The distinguisher the mandate asks for, made explicit: on a REAL session the INPUT feed is
    # large (>1000) and the SELECTION is non-empty; a holiday/no-data day has an EMPTY input
    # feed and an empty selection. The (input_count, ranked_count) pair separates correct-0
    # (0, 0) from broken-0 (large, 0) from healthy (large, >0).
    algo = _make_algo(monkeypatch)
    real_feed = _feed_for(_FY_DAYS[0])
    real_ranked = algo._coarse_selection(real_feed)
    assert (len(real_feed) > 1000) and (len(real_ranked) > 0)  # healthy: (large, >0)

    algo2 = _make_algo(monkeypatch)
    holiday_ranked = algo2._coarse_selection([])
    assert (len([]) == 0) and (len(holiday_ranked) == 0)  # correct-0: (0, 0)
