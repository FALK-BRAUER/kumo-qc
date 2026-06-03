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
    assert h["authoritative"] is True  # default


def test_artifact_header_authoritative_flag() -> None:
    """The authoritative flag + universe_membership_uncertainty thread through to the header."""
    h = C._artifact_header(
        ["2022-01-03"], 7, 0.25, True, "local-daily-approx-NOT-AUTHORITATIVE:2022",
        authoritative=False,
        universe_membership_uncertainty={"generator_signal_winners": 9999, "instrumented": 7007},
    )
    assert h["authoritative"] is False
    assert h["universe_membership_uncertainty"]["instrumented"] == 7007


# --------------------------------------------------------------------------------------
# COARSE-CSV UNIVERSE SOURCE (#276b parity fix) — pure-logic with a fixture coarse CSV.
# --------------------------------------------------------------------------------------


def _write_coarse_csv(coarse_dir, ymd: str, rows: list[tuple[str, float, int, float]]) -> None:
    """Write a fixture LEAN coarse CSV (SID,ticker,close,volume,dollar_volume,has_fund,pf,sf)."""
    coarse_dir.mkdir(parents=True, exist_ok=True)
    lines = []
    for ticker, close, volume, dv in rows:
        lines.append(f"{ticker} XSID,{ticker},{close},{volume},{dv},True,1,1")
    (coarse_dir / f"{ymd}.csv").write_text("\n".join(lines) + "\n")


def test_read_coarse_csv_parses_ticker_close_dv(tmp_path) -> None:
    """read_coarse_csv yields {ticker_lower: (close, single_day_dv)} from the coarse CSV columns."""
    cd = tmp_path / "coarse"
    _write_coarse_csv(cd, "20240102", [("AAA", 50.0, 1_000_000, 50_000_000.0),
                                       ("BBB", 12.0, 2_000_000, 24_000_000.0)])
    m = C.read_coarse_csv("2024-01-02", coarse_dir=cd)
    assert m == {"aaa": (50.0, 50_000_000.0), "bbb": (12.0, 24_000_000.0)}
    # DV comes from the CSV column, NOT recomputed close*volume (49M != 50M proves the source).
    _write_coarse_csv(cd, "20240103", [("CCC", 100.0, 490_000, 999_999_999.0)])
    assert C.read_coarse_csv("2024-01-03", coarse_dir=cd)["ccc"] == (100.0, 999_999_999.0)


def test_read_coarse_csv_drops_nonfinite_and_missing(tmp_path) -> None:
    """A non-finite DV/close coarse row is dropped (mirrors lean_entry #261-2); missing file -> {}."""
    cd = tmp_path / "coarse"
    cd.mkdir(parents=True)
    (cd / "20240102.csv").write_text(
        "AAA XSID,AAA,50.0,1000000,50000000.0,True,1,1\n"
        "BAD XSID,BAD,nan,1000000,inf,True,1,1\n"
        "SHORT,SHORT,10.0\n"  # too few columns -> skipped
    )
    m = C.read_coarse_csv("2024-01-02", coarse_dir=cd)
    assert m == {"aaa": (50.0, 50_000_000.0)}
    assert C.read_coarse_csv("2099-01-01", coarse_dir=cd) == {}  # missing file


def test_coarse_csv_exists(tmp_path) -> None:
    cd = tmp_path / "coarse"
    _write_coarse_csv(cd, "20240102", [("AAA", 50.0, 1_000_000, 50_000_000.0)])
    assert C.coarse_csv_exists("2024-01-02", coarse_dir=cd)
    assert not C.coarse_csv_exists("2024-01-03", coarse_dir=cd)


def test_build_coarse_universe_membership_is_coarse_tickers(tmp_path) -> None:
    """The universe for a date == the coarse CSV's tickers that clear prefilter+floors; DV from CSV.

    AAA: huge DV, price 50 -> passes (prefilter 25M, price floor 10, trailing >= 100M).
    LOW: price 5 -> fails the MIN_PRICE floor (excluded).
    THIN: single-day DV 10M < prefilter 25M -> never builds a metric (excluded).
    """
    cd = tmp_path / "coarse"
    _write_coarse_csv(cd, "20240102", [
        ("AAA", 50.0, 1, 500_000_000.0),    # close>=10, dv>=prefilter, trailing>=100M -> in
        ("LOW", 5.0, 1, 500_000_000.0),     # close<10 -> floored out
        ("THIN", 80.0, 1, 10_000_000.0),    # single-day dv < prefilter -> no metric -> out
    ])
    univ, metrics = C.build_coarse_universe(2024, coarse_dir=cd)
    assert univ["2024-01-02"] == ["AAA"]  # only AAA clears prefilter+floors
    # metrics carry the coarse close + single-day DV + trailing (=sdv on first appearance).
    assert metrics["2024-01-02"]["aaa"] == (50.0, 500_000_000.0, 500_000_000.0)
    assert metrics["2024-01-02"]["thin"][1] == 10_000_000.0  # metric exists, just not ranked


def test_build_coarse_universe_trailing_mean_over_appearances(tmp_path) -> None:
    """trailing_dv == mean of the single-day coarse DV over the last ADV_WINDOW appearances."""
    cd = tmp_path / "coarse"
    _write_coarse_csv(cd, "20240102", [("AAA", 50.0, 1, 200_000_000.0)])
    _write_coarse_csv(cd, "20240103", [("AAA", 50.0, 1, 400_000_000.0)])
    univ, metrics = C.build_coarse_universe(2024, coarse_dir=cd)
    # day 2 trailing = mean(200M, 400M) = 300M (window holds both appearances).
    assert metrics["2024-01-03"]["aaa"][2] == pytest.approx(300_000_000.0)


def test_build_coarse_universe_empty_when_no_csv(tmp_path) -> None:
    """A year with NO coarse CSVs -> empty universe/metrics (caller falls back to local-daily)."""
    cd = tmp_path / "coarse"
    cd.mkdir(parents=True)
    univ, metrics = C.build_coarse_universe(2022, coarse_dir=cd)
    assert univ == {} and metrics == {}


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


_skip_no_coarse = pytest.mark.skipif(
    not rd.have_coarse_tree(), reason="local LEAN coarse tree absent (gitignored data/) — presence guard"
)


@pytest.mark.gdata
@_skip_no_coarse
def test_coarse_universe_membership_equals_coarse_csv_tickers() -> None:
    """The authoritative universe for a real coarse session is drawn from THAT CSV's tickers, and
    every emitted DV equals the coarse CSV's own dollar_volume column (not local close*volume)."""
    univ, metrics = C.build_coarse_universe(2025)
    date = "2025-09-02"
    raw = C.read_coarse_csv(date)
    assert raw, "expected a real coarse CSV for 2025-09-02"
    # every ranked ticker came from the coarse CSV membership.
    for t in univ[date]:
        assert t.lower() in raw, f"{t} ranked but not in the coarse CSV membership"
    # the metric DV is the coarse CSV DV (authoritative source), not a recomputed value.
    for t in univ[date][:20]:
        close, sdv, _trailing = metrics[date][t.lower()]
        assert (close, sdv) == raw[t.lower()]


@pytest.mark.gdata
@_skip_no_coarse
def test_coarse_coverage_drives_authoritative_decision() -> None:
    """The authoritative decision is governed by coarse-CSV coverage (cheap to verify without the
    full per-name scoring run): FY2025 has a coarse CSV for every trading session (-> authoritative
    True); FY2022 has none (-> authoritative False, local-daily fallback)."""
    univ25, _ = C.build_coarse_universe(2025)
    assert len(univ25) > 200, "FY2025 should be fully coarse-covered (~250 sessions)"
    # FY2022 predates the coarse tree (starts 2023-06-20) -> no coarse universe -> fallback.
    univ22, metrics22 = C.build_coarse_universe(2022)
    assert univ22 == {} and metrics22 == {}
    # FY2023 is partial: coarse only from 2023-06-20 onward.
    univ23, _ = C.build_coarse_universe(2023)
    assert univ23, "FY2023 should have partial coarse coverage (from 2023-06-20)"
    assert min(univ23.keys()) >= "2023-06-20"


@pytest.mark.gdata
@_skip_no_coarse
def test_generate_candidates_uses_coarse_metrics_for_dv() -> None:
    """When coarse_metrics is supplied, the emitted single_day_dv == the coarse feed DV (the
    authoritative source), proving the universe/DV switch flows through to the row."""
    date = "2025-09-02"
    univ, metrics = C.build_coarse_universe(2025)
    rows = C.generate_candidates_for_date(
        date, univ[date], coarse_metrics=metrics[date]
    )
    assert rows
    for r in rows:
        coarse_sdv = metrics[date][r.symbol.lower()][1]
        assert r.single_day_dv == pytest.approx(coarse_sdv)
