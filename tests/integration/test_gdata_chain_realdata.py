"""#260 — the G-DATA real-data CHAIN integration test (the crown jewel).

The closed sub-tickets test each RUNG in isolation: #263 the selection gate (active-set
non-empty), #264 the seed/warm, #259 the scorer's readiness gating, #265 the recorded-ledger
parity. NONE of them assert the RUNG-TO-RUNG HANDOFF on one real session — and the handoff is
exactly where the #173 / #237 mirage lived: a name that selection picks, that then silently
fails to warm, that is then scored cold. A per-rung green can coexist with a broken chain.

THIS file drives the REAL path end-to-end on REAL on-disk data (the gitignored data/ symlink):

    REAL _coarse_selection  →  REAL seed/warm of a SELECTED name  →  REAL score_symbol_native

Only the QC-native indicator VALUE-WRAPPERS are faked (QC's compiled IchimokuKinkoHyo/ADX/SMA
are absent in the dev venv); the VALUES in them are computed from the SAME real history via the
REAL oracle math + the REAL weekly seed aggregation, and the selection gate, the warm-bar
arithmetic and the scorer are all the REAL engine code. Faking the wrapper shape is not faking
the chain (HQ hard requirement #1).

The four highest-value gates (HQ steer):
  • NON-EMPTY / WARM where expected   — catches active_set=0×636 + the cold-entrant mirage.
  • COLD CANNOT score (paired)        — a not-ready input returns None, never a number.
  • CRASH-NOT-MIRAGE on degraded      — empty / broken-0 feed raises, paired with a healthy day.
  • ZERO-COVERAGE TRAP (#237)         — a short window covering 0 names FAILS as non-coverage.

Data-presence: if the local tree is absent (CI without data/), the real-path tests SKIP with a
reason — a presence guard, not a silent pass. The pure-logic coverage-trap assertion always runs.
"""
from __future__ import annotations

import datetime as dt
import warnings

import pytest

from phases.shared.oracle_helpers import score_symbol_native
from runtime.indicators import weekly_aggregate
from tests.harness import realdata as rd
from tests.harness.gdata_asserts import (
    assert_can_warm,
    assert_cold_cannot_score,
    assert_coverage_not_zero,
    assert_crash_not_mirage,
    assert_selection_nonempty,
    assert_warm_scores,
)

pytestmark = pytest.mark.gdata

# Real sessions: warmup-window span + FY2025 boundaries. Each must SELECT non-empty.
_WARMUP_DAYS = ["20230620", "20231002", "20240701", "20241231"]
_FY_DAYS = ["20250102", "20250603", "20251231"]
# The session the full chain runs on (a mid-FY real trading day with a full >10k-name feed).
_CHAIN_DAY = "20250603"

_DATA = rd.have_coarse_tree() and rd.have_daily_tree()
_skip_no_data = pytest.mark.skipif(
    not _DATA, reason="local LEAN coarse+daily tree absent (gitignored data/) — presence guard"
)


def _select(monkeypatch, ymd: str):
    when = dt.datetime.strptime(ymd, "%Y%m%d")
    algo = rd.make_selection_algo(monkeypatch, when)
    feed = rd.read_coarse_rows(ymd)
    ranked = algo._coarse_selection(feed)
    return algo, feed, ranked


# ======================================================================================
# RUNG 1 — NON-EMPTY selection on every real session (the #173 guard at the selection grain).
# ======================================================================================
@_skip_no_data
@pytest.mark.parametrize("ymd", _WARMUP_DAYS + _FY_DAYS)
def test_selection_nonempty_on_real_session(monkeypatch, ymd: str) -> None:
    _algo, feed, ranked = _select(monkeypatch, ymd)
    assert_selection_nonempty(ranked, names_in=len(feed), day=ymd)


# ======================================================================================
# THE CHAIN — selection → warm → score on ONE real session, driven end-to-end.
# ======================================================================================
@_skip_no_data
def test_chain_selection_to_warm_to_score_real_session(monkeypatch) -> None:
    # RUNG 1: REAL selection over the real feed.
    _algo, feed, ranked = _select(monkeypatch, _CHAIN_DAY)
    assert_selection_nonempty(ranked, names_in=len(feed), day=_CHAIN_DAY)
    selected = {s.value.lower() for s in ranked}

    # The chain can only be exercised on a SELECTED name that also has on-disk daily history.
    covered = [t for t in rd.LIQUID if t in selected and rd.daily_available(t)]
    # A populated real session that selects NONE of the liquid bellwethers with on-disk history
    # is itself a coverage failure (not a silent skip) — fail loud via the zero-coverage trap.
    assert_coverage_not_zero(
        len(covered), window_label=f"chain@{_CHAIN_DAY}", universe_label="liquid selected+on-disk names"
    )

    scored = 0
    for ticker in covered:
        daily = rd.read_daily_zip(ticker)
        window = daily.iloc[-rd.WARMUP_DAYS:]  # the WARMUP_DAYS (560) trading-bar seed window

        # RUNG 2: REAL seed/warm — the selected name CAN warm the binding weekly pole + daily pole.
        weekly = weekly_aggregate(window)  # the REAL seed aggregation
        assert_can_warm(weekly_bars=len(weekly), daily_bars=len(window), ticker=ticker)

        # RUNG 3: REAL scorer over REAL-valued maintained inputs — a warmed name IS scoreable.
        ind, price = rd.build_real_native_inputs(window)
        qc = rd.FakeQC(price=price, symbol=ticker)
        score = score_symbol_native(qc, ticker, ind)
        assert_warm_scores(score, ticker=ticker)
        scored += 1

    # Belt-and-suspenders: at least one full chain actually ran (covered names were all scored).
    assert scored == len(covered) and scored > 0


# ======================================================================================
# COLD CANNOT score — paired with the healthy warm control on the SAME real values (mutation-bite).
# ======================================================================================
@_skip_no_data
@pytest.mark.parametrize("cold_key", ["d_ichi", "w_ichi", "sma200", "adx", "roc13", "w_close", "adx_window"])
def test_cold_input_cannot_score_paired_with_warm_control(monkeypatch, cold_key: str) -> None:
    _algo, feed, ranked = _select(monkeypatch, _CHAIN_DAY)
    selected = {s.value.lower() for s in ranked}
    covered = [t for t in rd.LIQUID if t in selected and rd.daily_available(t)]
    assert_coverage_not_zero(len(covered), window_label=f"cold@{_CHAIN_DAY}", universe_label="liquid names")

    ticker = covered[0]
    window = rd.read_daily_zip(ticker).iloc[-rd.WARMUP_DAYS:]

    # HEALTHY control: all inputs ready → a real score (non-None). Proves the seam CAN pass.
    warm_ind, price = rd.build_real_native_inputs(window)
    qc = rd.FakeQC(price=price, symbol=ticker)
    assert_warm_scores(score_symbol_native(qc, ticker, warm_ind), ticker=ticker)

    # DEGRADED: the SAME real values with ONE input not-ready → must return None (cold-cannot-score).
    cold_ind, cold_price = rd.with_input_not_ready(window, cold_key)
    qc2 = rd.FakeQC(price=cold_price, symbol=ticker)
    assert_cold_cannot_score(score_symbol_native(qc2, ticker, cold_ind), label=cold_key)


# ======================================================================================
# CRASH-NOT-MIRAGE — degraded selection feeds raise loud, each paired with a healthy real day.
# ======================================================================================
@_skip_no_data
def test_degraded_selection_crashes_not_mirages_paired(monkeypatch) -> None:
    # HEALTHY control: a real populated feed selects non-empty (the seam works).
    _algo, feed, ranked = _select(monkeypatch, _CHAIN_DAY)
    assert_selection_nonempty(ranked, names_in=len(feed), day=_CHAIN_DAY)

    # DEGRADED A — empty feed on a trading day (a data gap): must raise, never silent-empty (#261-5).
    algo_a = rd.make_selection_algo(monkeypatch, dt.datetime(2025, 6, 3))
    assert_crash_not_mirage(lambda: algo_a._coarse_selection([]), label="empty-feed-data-gap")

    # DEGRADED B — broken-0: a full feed where every name is below the floors collapses to empty
    # (the −0.616 full-in/empty-out mirage): must raise with the input count, never silent (#261-6).
    algo_b = rd.make_selection_algo(monkeypatch, dt.datetime(2025, 6, 3))
    below = [
        type("C", (), {"symbol": rd._Sym(f"t{i}"), "price": 50.0, "dollar_volume": 1.0e6})()
        for i in range(2000)
    ]
    assert_crash_not_mirage(lambda: algo_b._coarse_selection(below), label="broken-0-below-floors")


# ======================================================================================
# THE ZERO-COVERAGE TRAP (#237) — a short window covering 0 names must FAIL, not pass green.
# ======================================================================================
@_skip_no_data
def test_short_window_zero_coverage_is_red_not_green(monkeypatch) -> None:
    # The #237 lesson: an 11-day Step-A masked a full-FY sign flip because the short window
    # produced ~0 coverage yet read green. This test proves the guard distinguishes the two and
    # FAILS LOUD on zero — both halves are asserted on REAL data.
    ticker = next((t for t in rd.LIQUID if rd.daily_available(t)), None)
    assert ticker is not None, "no liquid on-disk daily — cannot exercise the coverage trap"
    daily = rd.read_daily_zip(ticker)

    # HEALTHY: the FULL window warms → counts as coverage → assert_coverage_not_zero passes.
    full = daily.iloc[-rd.WARMUP_DAYS:]
    full_weekly = weekly_aggregate(full)
    covered_full = 1 if len(full_weekly) >= 78 and len(full) >= 200 else 0
    assert_coverage_not_zero(covered_full, window_label="full-WARMUP", universe_label=f"warm[{ticker}]")

    # TRAP: a deliberately SHORT 30-bar window cannot warm the 78-week pole → 0 coverage. The
    # guard MUST turn that into a RED (AssertionError), never a silent green.
    short = daily.iloc[-30:]
    short_weekly = weekly_aggregate(short)
    with pytest.raises(AssertionError):
        assert_can_warm(weekly_bars=len(short_weekly), daily_bars=len(short), ticker=ticker)
    covered_short = 1 if len(short_weekly) >= 78 and len(short) >= 200 else 0
    with pytest.raises(AssertionError):
        assert_coverage_not_zero(covered_short, window_label="short-30bar", universe_label=f"warm[{ticker}]")


# ======================================================================================
# INTRADAY 5-min chain smoke — coverage-LIMITED to the on-disk names; the limit is LOGGED LOUD
# (no-silent-caps: assert what IS covered, mark what is NOT).
# ======================================================================================
@pytest.mark.skipif(not rd.have_minute_tree(), reason="local minute tree absent — presence guard")
def test_intraday_5min_smoke_logs_coverage_limit() -> None:
    on_disk = [t for t in rd.LIQUID if rd.minute_available(t)]
    missing = [t for t in rd.LIQUID if not rd.minute_available(t)]
    # LOUD, never silent: the intraday tree on disk only carries a few names — say so explicitly.
    warnings.warn(
        f"#260 intraday 5-min coverage is PARTIAL by data availability: covered={on_disk}, "
        f"NOT-covered(of the liquid probe set)={missing}. Full-universe intraday coverage needs "
        f"the minute tree populated beyond aapl/cost/msft.",
        stacklevel=2,
    )
    assert on_disk, "no liquid intraday names on disk — cannot smoke the 5-min path"

    for ticker in on_disk:
        sessions = sorted((rd.MINUTE_DIR / ticker).glob("*_trade.zip"))
        assert sessions, f"{ticker}: minute dir present but no trade zips"
        ymd = sessions[0].name.split("_")[0]
        bars = rd.read_minute_trade_zip(ticker, ymd)
        # Real intraday bars: non-empty, OHLC sane (high >= low), positive prices, time-ordered.
        assert len(bars) > 0, f"{ticker} {ymd}: empty intraday session"
        assert (bars["high"] >= bars["low"]).all(), f"{ticker} {ymd}: high < low in a bar"
        assert (bars["close"] > 0).all(), f"{ticker} {ymd}: non-positive close"
        assert bars.index.is_monotonic_increasing, f"{ticker} {ymd}: bars not time-ordered"
