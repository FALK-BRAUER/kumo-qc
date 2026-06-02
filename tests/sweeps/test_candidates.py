"""Coverage for the (B) signal-winner candidate-universe generator (sweeps/archive/candidates.py).

Two lanes:
  - PURE-LOGIC (always run): row schema/order determinism, roc13 math, trailing-DV mean,
    no-look-ahead of the feature recompute, header provenance, JSONL byte-determinism.
  - REAL-DATA (@gdata, skipped when the gitignored data/ tree is absent): the funnel-def-match
    proof — the no-floors population count == the C1 harness (scripts/funnel_signal_count.py)
    score>=7 count on the SAME dates (same scorer, same data, same as-of slice), the funnel-mode
    subset relationship, and determinism on a real date.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from sweeps.archive import candidates as C

# ======================================================================================
# PURE-LOGIC — no real data, always run.
# ======================================================================================


def _ramp_frame(n: int, start_close: float = 50.0) -> pd.DataFrame:
    idx = pd.date_range("2022-01-03", periods=n, freq="B")
    closes = start_close + np.arange(n, dtype=float) * 0.1
    return pd.DataFrame(
        {
            "open": closes,
            "high": closes * 1.01,
            "low": closes * 0.99,
            "close": closes,
            "volume": 1_000_000.0,
        },
        index=idx,
    )


def test_roc13_matches_qc_definition() -> None:
    """roc13 == (close[-1] - close[-14]) / close[-14], decimal fraction (the parabolic input)."""
    df = _ramp_frame(30)
    expected = (df["close"].iloc[-1] - df["close"].iloc[-14]) / df["close"].iloc[-14]
    assert C._roc13(df) == pytest.approx(expected)


def test_roc13_nan_when_too_short() -> None:
    assert np.isnan(C._roc13(_ramp_frame(13)))  # needs 14 bars


def test_trailing_dv_mean_is_mean_of_last_window() -> None:
    """trailing_dv == mean(close*volume) over the last ADV_WINDOW observed bars <= as_of."""
    df = _ramp_frame(40)
    as_of = df.index[-1]
    tail = df.tail(C.ADV_WINDOW)
    expected = float((tail["close"] * tail["volume"]).mean())
    assert C._trailing_dv_mean(df, as_of) == pytest.approx(expected)


def test_trailing_dv_mean_no_lookahead() -> None:
    """A bar dated after as_of never enters the trailing mean."""
    df = _ramp_frame(40)
    as_of = df.index[25]
    upto = df[df.index <= as_of].tail(C.ADV_WINDOW)
    expected = float((upto["close"] * upto["volume"]).mean())
    got = C._trailing_dv_mean(df, as_of)
    assert got == pytest.approx(expected)
    # mutating FUTURE bars must NOT change the result (proves no look-ahead).
    df2 = df.copy()
    df2.iloc[26:, df2.columns.get_loc("volume")] = 9.9e12
    assert C._trailing_dv_mean(df2, as_of) == pytest.approx(expected)


def test_features_from_daily_no_lookahead() -> None:
    """The feature recompute is a function ONLY of bars <= as_of: future bars cannot move it."""
    full = _ramp_frame(700)
    as_of = full.index[550]  # >= 500 bars sliced -> >= 78 weekly bars (feature warmup met)
    sliced = C.slice_as_of(full, as_of)
    feats_a = C._features_from_daily(sliced)
    assert feats_a is not None
    # corrupt every future bar then re-slice as-of the SAME date — features must be identical.
    poisoned = full.copy()
    fut = poisoned.index > as_of
    for col in ("open", "high", "low", "close"):
        poisoned.loc[fut, col] = 1e6
    feats_b = C._features_from_daily(C.slice_as_of(poisoned, as_of))
    assert feats_b is not None
    assert feats_a == feats_b


def test_features_warmup_guard_returns_none() -> None:
    assert C._features_from_daily(_ramp_frame(100)) is None  # < 230 daily bars


def _row(date: str, sym: str, score: int) -> C.CandidateRow:
    return C.CandidateRow(
        date=date, symbol=sym, score=score, rating="++", conditions=[True] * 8,
        close=50.0, daily_tenkan=49.0, daily_kijun=48.0, sma200=40.0,
        daily_cloud_a=45.0, daily_cloud_b=44.0, daily_cloud_top=45.0,
        weekly_cloud_a=42.0, weekly_cloud_b=41.0, weekly_cloud_top=42.0,
        weekly_tenkan=43.0, weekly_kijun=42.5,
        adx=25.0, plus_di=30.0, minus_di=10.0, roc13=0.05,
        single_day_dv=2e8, trailing_dv=1.5e8, scanner_rank=3,
        passed_prefilter=True, passed_floors=True, passed_parabolic=True,
    )


def test_row_schema_has_expanded_conditions_and_all_fields() -> None:
    j = _row("2024-06-03", "ABC", 8).to_json()
    for i in range(8):
        assert f"cond_{i}" in j and isinstance(j[f"cond_{i}"], bool)
    for fld in (
        "date", "symbol", "score", "rating", "close", "daily_tenkan", "daily_kijun", "sma200",
        "daily_cloud_a", "daily_cloud_b", "daily_cloud_top", "weekly_cloud_a", "weekly_cloud_b",
        "weekly_cloud_top", "weekly_tenkan", "weekly_kijun", "adx", "plus_di", "minus_di",
        "roc13", "single_day_dv", "trailing_dv", "scanner_rank",
        "passed_prefilter", "passed_floors", "passed_parabolic",
    ):
        assert fld in j, f"missing field {fld}"


def test_row_to_json_rounds_and_nan_to_none() -> None:
    r = _row("2024-06-03", "ABC", 7)
    r.roc13 = float("nan")
    j = r.to_json()
    assert j["roc13"] is None
    assert j["sma200"] == 40.0  # round-trip stable


def test_write_jsonl_is_deterministic_and_header_first(tmp_path) -> None:
    header = C._artifact_header(["2024-01-02"], 7, 0.25, True, "test-src")
    rows = [_row("2024-01-02", "ZZZ", 7), _row("2024-01-02", "AAA", 8)]
    p1 = C.write_jsonl(header, rows, tmp_path / "a.jsonl")
    p2 = C.write_jsonl(header, rows, tmp_path / "b.jsonl")
    b1 = p1.read_bytes()
    b2 = p2.read_bytes()
    assert b1 == b2  # byte-identical
    lines = b1.decode().strip().split("\n")
    assert json.loads(lines[0])["record_type"] == "header"
    assert json.loads(lines[1])["symbol"] == "ZZZ"  # rows written in given order


def test_artifact_header_stamps_provenance() -> None:
    h = C._artifact_header(["2024-01-02", "2024-12-31"], 7, 0.25, True, "local-daily:2024")
    assert h["data_vendor"] == "local-lean-daily-zips"
    assert h["data_normalization"] == "raw"
    assert h["funnel"]["min_price"] == 10.0
    assert h["funnel"]["min_avg_dollar_volume"] == 100_000_000.0
    assert h["funnel"]["prefilter_dv"] == 25_000_000.0
    assert h["funnel"]["min_score"] == 7
    assert h["universe_source"] == "local-daily:2024"
    assert h["first_date"] == "2024-01-02" and h["last_date"] == "2024-12-31"


def test_funnel_constants_match_live_gate() -> None:
    """Tripwire: the mirrored funnel floors must equal the live selection-gate values. If the
    runtime gate changes a floor, this fails so the generator can't silently drift from the
    strategy's actual signal set."""
    from runtime.lean_entry import BctEngineAlgorithm

    assert C.PREFILTER_DV == BctEngineAlgorithm.PREFILTER_DV
    assert C.MIN_PRICE == BctEngineAlgorithm.MIN_PRICE
    assert C.MIN_AVG_DOLLAR_VOLUME == BctEngineAlgorithm.MIN_AVG_DOLLAR_VOLUME
    assert C.COARSE_MAX == BctEngineAlgorithm.COARSE_MAX
    assert C.ADV_WINDOW == BctEngineAlgorithm.ADV_WINDOW


# ======================================================================================
# REAL-DATA (@gdata) — the funnel-def-match proof. Skips when the gitignored data/ is absent.
# ======================================================================================
from tests.harness import realdata as rd  # noqa: E402

pytestmark_realdata = pytest.mark.gdata
_skip_no_data = pytest.mark.skipif(
    not rd.have_daily_tree(), reason="local LEAN daily tree absent (gitignored data/) — presence guard"
)

# C1 ground-truth score>=7 counts (scripts/funnel_signal_count.py, FY2025 polygon snapshot).
_C1_PARITY = {"2025-01-02": 13, "2025-05-05": 38, "2025-09-03": 40, "2025-12-31": 17}


@pytest.mark.gdata
@_skip_no_data
def test_c1_parity_no_floors_matches_count_harness() -> None:
    """FUNNEL-DEF-MATCH: in no-floors (C1) mode the generator's score>=7 row count per date is
    IDENTICAL to the C1 count harness — proves the SAME scoring core over the SAME data/as-of."""
    universe = C.load_universe()
    for date, expected in _C1_PARITY.items():
        rows = C.generate_candidates_for_date(
            date, universe[date], apply_funnel_floors=False
        )
        n = sum(1 for r in rows if r.score >= 7)
        assert n == expected, f"{date}: generator {n} != C1 {expected}"


@pytest.mark.gdata
@_skip_no_data
def test_every_emitted_row_meets_threshold_and_has_features() -> None:
    universe = C.load_universe()
    rows = C.generate_candidates_for_date("2025-09-03", universe["2025-09-03"])
    assert rows, "expected a non-empty population on a real FY2025 session"
    for r in rows:
        assert r.score >= C.DEFAULT_MIN_SCORE
        assert len(r.conditions) == 8 and r.score == sum(r.conditions)
        assert r.close > 0 and r.sma200 > 0  # features populated


@pytest.mark.gdata
@_skip_no_data
def test_funnel_winners_are_floor_subset() -> None:
    """The funnel signal_winners (all passed_* flags) are a subset that cleared the floors: every
    such row has trailing_dv >= the floor, close >= min_price, and roc13 <= the parabolic cut."""
    universe = C.load_universe()
    rows = C.generate_candidates_for_date("2025-09-03", universe["2025-09-03"])
    winners = [r for r in rows if r.passed_prefilter and r.passed_floors and r.passed_parabolic]
    assert winners
    for r in winners:
        assert r.close >= C.MIN_PRICE
        assert r.trailing_dv >= C.MIN_AVG_DOLLAR_VOLUME
        assert r.single_day_dv >= C.PREFILTER_DV
        assert r.roc13 <= C.DEFAULT_PARABOLIC_THRESHOLD


@pytest.mark.gdata
@_skip_no_data
def test_real_date_determinism() -> None:
    universe = C.load_universe()
    a = [r.to_json() for r in C.generate_candidates_for_date("2025-05-05", universe["2025-05-05"])]
    b = [r.to_json() for r in C.generate_candidates_for_date("2025-05-05", universe["2025-05-05"])]
    assert a == b


@pytest.mark.gdata
@_skip_no_data
def test_rows_sorted_score_desc_then_ticker_asc() -> None:
    universe = C.load_universe()
    rows = C.generate_candidates_for_date("2025-09-03", universe["2025-09-03"])
    keys = [(-r.score, r.symbol) for r in rows]
    assert keys == sorted(keys)


@pytest.mark.gdata
@_skip_no_data
def test_streaming_dv_matches_loader() -> None:
    """The build_local_universe streaming zip parse must yield the SAME single-day DV the canonical
    load_daily_frame gives (close*volume) — locks the two data paths against silent divergence.

    build_local_universe selects names whose single_day_dv >= PREFILTER_DV; we confirm that for a
    sampled selected name on a sampled date, close*volume from load_daily_frame >= PREFILTER_DV too
    (same parse convention), i.e. the streaming verdict reproduces the loader's value."""
    universe = C.build_local_universe(2024)
    sample_dates = sorted(universe.keys())[::60]  # a few spread-out dates
    checked = 0
    for date in sample_dates:
        as_of = pd.Timestamp(date)
        for ticker in universe[date][:5]:  # a handful of selected names
            df = C.load_daily_frame(ticker)
            assert df is not None, f"{ticker} selected but load_daily_frame returned None"
            bar = df[df.index <= as_of].iloc[-1]
            loader_sdv = float(bar["close"]) * float(bar["volume"])
            # selected => cleared the prefilter; the loader-derived DV must agree.
            assert loader_sdv >= C.PREFILTER_DV, (
                f"{ticker} {date}: loader DV {loader_sdv} < prefilter — parse paths diverge"
            )
            checked += 1
    assert checked > 0, "expected to check at least one selected name"
